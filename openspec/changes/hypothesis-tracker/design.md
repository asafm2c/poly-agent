## Context

The simulation harness (Run #3, n=20) revealed actionable patterns: the agent beats the market on probable-NO markets by tempering overconfidence, performs well in the $100K-$1M volume tier, and is market-neutral on >$1M markets. These findings currently live only in MEMORY.md. There is no structured way to formulate these as testable hypotheses, track evidence for or against them, automatically feed confirmed hypotheses into the live trading pipeline, or detect when a hypothesis has gone stale.

The backtest DB already stores simulation runs and trials (`bt_simulation_runs`, `bt_simulation_trials`). The strategy config (`strategy.yaml`) drives market selection and edge thresholds. The calibration tracker feeds LLM prompts. The scheduler monitors strategy drift. The hypothesis tracker bridges all of these: it formalizes findings as hypotheses, gathers evidence via targeted simulations, and translates confirmed hypotheses into parameter adjustments that flow through the existing pipeline.

## Goals / Non-Goals

**Goals:**
- Persist hypotheses with testable filter criteria and a formal lifecycle (proposed -> testing -> confirmed/rejected/invalidated)
- Link simulation runs to hypotheses as evidence, with statistical metrics
- Translate confirmed hypotheses into conservative pipeline actions (edge overrides, category targeting)
- Implement confidence decay so stale hypotheses lose influence over time
- Provide CLI commands for the full hypothesis workflow
- Seed the 4 initial hypotheses from our simulation findings

**Non-Goals:**
- Full experiment management platform (no A/B testing, no control groups)
- Automated hypothesis generation from data (hypotheses are human-proposed)
- Real-time hypothesis evaluation during live trading (evaluation is batch, post-simulation)
- Complex statistical testing beyond Brier comparison and paired t-tests

## Decisions

### 1. Data model: three tables in backtest.db

**Decision**: Add `bt_hypotheses`, `bt_hypothesis_evidence`, and `bt_hypothesis_actions` to the existing `SCHEMA_SQL` in `database.py`.

**Schema**:

```sql
CREATE TABLE IF NOT EXISTS bt_hypotheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'testing', 'confirmed', 'rejected', 'invalidated')),
    confidence_score REAL DEFAULT 0.0,
    -- Filter criteria: which markets does this hypothesis apply to?
    category_filter TEXT,            -- NULL = null-category (prediction markets), '*' = all
    volume_min REAL,                 -- NULL = no floor
    volume_max REAL,                 -- NULL = no ceiling
    model_filter TEXT,               -- NULL = current default model
    temporal_filter TEXT,            -- JSON: {"horizon_days": 7, "regime": "o1-era"} or NULL
    -- Lifecycle timestamps
    proposed_at TEXT NOT NULL,
    first_tested_at TEXT,
    confirmed_at TEXT,
    last_evaluated_at TEXT,
    invalidated_at TEXT,
    -- Decay parameters
    decay_half_life_days INTEGER DEFAULT 90,
    retest_threshold REAL DEFAULT 0.50,
    -- Metadata
    proposed_by TEXT DEFAULT 'user',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS bt_hypothesis_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis_id INTEGER NOT NULL REFERENCES bt_hypotheses(id),
    run_id INTEGER NOT NULL REFERENCES bt_simulation_runs(id),
    recorded_at TEXT NOT NULL,
    -- Statistical metrics from the simulation run
    trial_count INTEGER NOT NULL,
    agent_brier REAL,
    market_brier REAL,
    brier_diff REAL,                 -- agent_brier - market_brier (negative = agent better)
    simulated_pnl REAL,
    p_value REAL,                    -- paired t-test on per-trial Brier scores
    effect_size REAL,                -- Cohen's d
    -- Evaluation outcome
    supports_hypothesis INTEGER,     -- 1 = supports, 0 = contradicts, NULL = inconclusive
    evaluation_notes TEXT
);

CREATE TABLE IF NOT EXISTS bt_hypothesis_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis_id INTEGER NOT NULL REFERENCES bt_hypotheses(id),
    action_type TEXT NOT NULL
        CHECK (action_type IN (
            'edge_override', 'category_target', 'category_avoid',
            'model_preference', 'weight_adjustment'
        )),
    config TEXT NOT NULL,            -- JSON: action-specific parameters
    base_strength REAL NOT NULL DEFAULT 1.0,  -- Full-confidence strength multiplier
    active INTEGER NOT NULL DEFAULT 0,        -- 1 = active, 0 = inactive
    created_at TEXT NOT NULL,
    activated_at TEXT,
    deactivated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_bt_hypotheses_status ON bt_hypotheses(status);
CREATE INDEX IF NOT EXISTS idx_bt_hyp_evidence_hyp ON bt_hypothesis_evidence(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_bt_hyp_evidence_run ON bt_hypothesis_evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_bt_hyp_actions_hyp ON bt_hypothesis_actions(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_bt_hyp_actions_active ON bt_hypothesis_actions(active);
```

**Status enum values and their meanings:**
- `proposed`: Hypothesis created with filters, not yet tested
- `testing`: At least one simulation has been launched; awaiting sufficient evidence
- `confirmed`: Evidence meets confirmation thresholds (see Decision 3)
- `rejected`: Evidence meets rejection thresholds (hypothesis is wrong)
- `invalidated`: Was confirmed but new evidence or decay has invalidated it

**Rationale**: Individual columns for `category_filter`, `volume_min`, `volume_max`, `model_filter` because these are the primary query axes and benefit from direct SQL filtering. `temporal_filter` is JSON because it combines horizon and regime, which vary in structure. The `name` column is UNIQUE to prevent duplicate hypotheses. `confidence_score` lives on the hypothesis row (not computed on the fly) because it incorporates decay which depends on wall-clock time.

### 2. Hypothesis lifecycle engine in `backtest/hypothesis.py`

**Decision**: New module with five core functions that implement the hypothesis state machine.

#### `propose()` — Create a hypothesis

```python
def propose(
    name: str,
    description: str,
    category_filter: str | None = None,
    volume_min: float | None = None,
    volume_max: float | None = None,
    model_filter: str | None = None,
    temporal_filter: dict | None = None,
    decay_half_life_days: int = 90,
    retest_threshold: float = 0.50,
    actions: list[dict] | None = None,
    db_path: Path | None = None,
) -> int:
    """Create a new hypothesis with status='proposed'.

    If actions are provided, they are created as inactive bt_hypothesis_actions rows.
    Each action dict must have: action_type, config, base_strength.

    Returns the hypothesis ID.
    """
```

**Data flow**: Validates the name is unique. Inserts into `bt_hypotheses` with `status='proposed'`, `proposed_at=now()`, `confidence_score=0.0`. If `actions` is provided, inserts rows into `bt_hypothesis_actions` with `active=0`. Returns the new hypothesis ID.

#### `test()` — Run targeted simulation

```python
def test(
    hypothesis_id: int,
    count: int = 50,
    horizon: int | None = None,
    db_path: Path | None = None,
) -> dict:
    """Run a simulation matching the hypothesis filters.

    Transitions status from 'proposed' to 'testing' (or stays 'testing'/'confirmed').
    Calls select_markets() with the hypothesis filter criteria, then run_simulation()
    with hypothesis_id so evidence is auto-recorded.

    Returns the simulation run summary dict (same as run_simulation()).
    """
```

**Data flow**:
1. Load hypothesis row. Validate status is in (`proposed`, `testing`, `confirmed`, `invalidated`) — rejected hypotheses cannot be re-tested without first being manually reset.
2. Extract filter criteria: `category_filter` (NULL -> `category=None` for select_markets, `*` -> no category filter), `volume_min`, `volume_max`, `temporal_filter.regime`, `temporal_filter.horizon_days` (overrides the `horizon` argument if set).
3. Call `select_markets(count=count, category=..., volume_min=..., volume_max=..., regime=..., horizon=...)`.
4. If status is `proposed`, transition to `testing` and set `first_tested_at=now()`.
5. Call `run_simulation(markets, horizon=horizon, hypothesis_id=hypothesis_id)`.
6. The simulator (see Decision 6) auto-records evidence on completion.
7. Return the run summary.

#### `evaluate()` — Assess evidence and transition status

```python
# Confirmation thresholds (module-level constants)
CONFIRM_MIN_TRIALS = 30
CONFIRM_BRIER_DIFF = -0.02       # Agent must be at least 0.02 better
CONFIRM_P_VALUE = 0.05           # Paired t-test significance
REJECT_MIN_TRIALS = 30
REJECT_BRIER_DIFF = 0.02         # Agent is 0.02 worse
REJECT_CONSECUTIVE_CONTRARY = 2  # 2 consecutive runs contradicting -> reject/invalidate

def evaluate(
    hypothesis_id: int,
    db_path: Path | None = None,
) -> dict:
    """Evaluate all evidence for a hypothesis and transition status.

    Computes weighted confidence score across all evidence records.
    Applies recency weighting (newer evidence counts more).
    Transitions status based on statistical thresholds.

    Returns dict with: status, confidence_score, evidence_count,
    weighted_brier_diff, recommendation.
    """
```

**Data flow**:
1. Load all `bt_hypothesis_evidence` rows for this hypothesis, ordered by `recorded_at`.
2. Compute recency-weighted metrics (see Decision 3).
3. **Confirmation path**: If total weighted trial count >= `CONFIRM_MIN_TRIALS` AND weighted brier_diff <= `CONFIRM_BRIER_DIFF` AND latest evidence p_value <= `CONFIRM_P_VALUE`:
   - Set `status='confirmed'`, `confirmed_at=now()`, `confidence_score` from formula.
   - Activate all `bt_hypothesis_actions` where `hypothesis_id` matches: set `active=1`, `activated_at=now()`.
4. **Rejection path**: If total weighted trial count >= `REJECT_MIN_TRIALS` AND weighted brier_diff >= `REJECT_BRIER_DIFF`:
   - Set `status='rejected'`.
5. **Demotion path** (for currently confirmed hypotheses): If last `REJECT_CONSECUTIVE_CONTRARY` evidence records all have `supports_hypothesis=0`:
   - Set `status='invalidated'`, `invalidated_at=now()`.
   - Deactivate all actions: set `active=0`, `deactivated_at=now()`.
6. **Inconclusive**: Otherwise stay in current status, update `confidence_score` and `last_evaluated_at`.
7. Return evaluation summary.

**How `supports_hypothesis` is determined for each evidence record**: When evidence is recorded (by the simulator, see Decision 6), the `supports_hypothesis` field is set to:
- `1` if `brier_diff < 0` (agent outperformed market on the hypothesis's filter criteria)
- `0` if `brier_diff > 0` (market outperformed agent)
- `NULL` if `brier_diff == 0` or trial_count < 5 (inconclusive)

#### `retest()` — Fresh simulation with recency weighting

```python
def retest(
    hypothesis_id: int,
    count: int = 50,
    db_path: Path | None = None,
) -> dict:
    """Run a fresh simulation and re-evaluate with recency weighting.

    Same as test() but followed by evaluate(). The new evidence will have
    higher recency weight than old evidence, potentially shifting the outcome.

    Returns the evaluation result dict.
    """
```

**Data flow**: Calls `test(hypothesis_id, count)` then `evaluate(hypothesis_id)`. The new evidence row has a later `recorded_at` timestamp, so it receives higher recency weight in the evaluation.

#### `decay_check()` — Scan for decayed hypotheses

```python
def decay_check(
    db_path: Path | None = None,
) -> list[dict]:
    """Scan all confirmed hypotheses for confidence decay.

    For each confirmed hypothesis:
    1. Compute current confidence using time-decayed formula.
    2. If confidence < retest_threshold, flag for re-testing.

    Returns list of {hypothesis_id, name, confidence_score,
    decayed_confidence, days_since_last_evidence, recommendation}.
    """
```

**Data flow**:
1. Query all hypotheses with `status='confirmed'`.
2. For each, load latest evidence `recorded_at` timestamp.
3. Compute decayed confidence (see Decision 3).
4. Update `confidence_score` on the hypothesis row with the decayed value.
5. Update all active actions' effective strength (via confidence scaling).
6. If decayed confidence < `retest_threshold`, include in the return list with `recommendation='retest'`.
7. If decayed confidence < 0.25 (critical threshold), transition to `invalidated` and deactivate actions.

### 3. Confidence decay and recency weighting formulas

**Decision**: Exponential half-life decay on elapsed time, and inverse-age weighting for combining multiple evidence records.

#### Time-based confidence decay

The confidence score of a confirmed hypothesis decays from its evaluation-time value based on time elapsed since the most recent evidence:

```
decayed_confidence = base_confidence * (0.5 ^ (days_elapsed / half_life_days))
```

Where:
- `base_confidence` = the confidence score computed at the last `evaluate()` call
- `days_elapsed` = days since the `recorded_at` of the most recent evidence record
- `half_life_days` = per-hypothesis configurable, default 90

Example: A hypothesis confirmed at confidence 0.80, with 90-day half-life, after 90 days decays to 0.40. After 180 days, 0.20.

#### Recency weighting for evidence combination

When `evaluate()` combines multiple evidence records (from multiple simulation runs), each record is weighted by recency:

```
weight_i = 1.0 / (1.0 + age_days_i / 30.0)
```

Where `age_days_i` = days between `recorded_at` of evidence record `i` and the current time.

This means:
- Evidence from today: weight = 1.0
- Evidence from 30 days ago: weight = 0.5
- Evidence from 60 days ago: weight = 0.33
- Evidence from 90 days ago: weight = 0.25

#### Weighted confidence computation

```python
def _compute_weighted_confidence(evidence_rows: list[dict]) -> float:
    """Compute confidence from recency-weighted evidence.

    Returns value in [0.0, 1.0].
    """
    if not evidence_rows:
        return 0.0

    now = datetime.now(timezone.utc)
    total_weight = 0.0
    weighted_signal = 0.0

    for ev in evidence_rows:
        recorded = datetime.fromisoformat(ev["recorded_at"])
        age_days = (now - recorded).total_seconds() / 86400.0
        weight = 1.0 / (1.0 + age_days / 30.0)

        # Signal: maps brier_diff to [0, 1] range
        # brier_diff of -0.05 -> strong support (signal ~0.9)
        # brier_diff of 0.0 -> neutral (signal 0.5)
        # brier_diff of +0.05 -> strong contradiction (signal ~0.1)
        if ev["brier_diff"] is not None and ev["trial_count"] >= 5:
            # Sigmoid-like mapping: clamp brier_diff to [-0.10, +0.10]
            clamped = max(-0.10, min(0.10, ev["brier_diff"]))
            signal = 0.5 - (clamped / 0.20)  # maps [-0.10, +0.10] to [1.0, 0.0]

            # Scale by sample size (more trials = more weight, up to 2x at n=100)
            n_factor = min(2.0, 1.0 + ev["trial_count"] / 100.0)
            weight *= n_factor

            weighted_signal += signal * weight
            total_weight += weight

    if total_weight == 0:
        return 0.0

    return max(0.0, min(1.0, weighted_signal / total_weight))
```

#### Weighted Brier diff and p-value (for threshold comparisons)

```python
def _compute_weighted_brier_diff(evidence_rows: list[dict]) -> tuple[float, int]:
    """Compute recency-weighted average Brier diff and effective trial count.

    Returns (weighted_brier_diff, effective_trial_count).
    """
    now = datetime.now(timezone.utc)
    total_weight = 0.0
    weighted_diff = 0.0
    effective_n = 0.0

    for ev in evidence_rows:
        if ev["brier_diff"] is None:
            continue
        recorded = datetime.fromisoformat(ev["recorded_at"])
        age_days = (now - recorded).total_seconds() / 86400.0
        weight = 1.0 / (1.0 + age_days / 30.0)

        weighted_diff += ev["brier_diff"] * weight * ev["trial_count"]
        total_weight += weight * ev["trial_count"]
        effective_n += ev["trial_count"] * weight

    if total_weight == 0:
        return 0.0, 0

    return weighted_diff / total_weight, int(effective_n)
```

### 4. Action system

**Decision**: Confirmed hypotheses generate typed actions with JSON config. Action strength scales with hypothesis confidence. Actions are loaded at strategy/edge computation time.

#### Action types and their config schemas

**`edge_override`**: Override the base edge threshold for matching markets.
```json
{
    "base_threshold": 0.08,
    "applies_to": "category"
}
```
Effective threshold = `config.base_threshold * (1.0 + (1.0 - confidence * base_strength) * 0.5)`. At full confidence (1.0) and base_strength 1.0, the threshold equals `base_threshold`. As confidence decays, the threshold creeps back toward the system default.

**`category_target`**: Add a category to the strategy's target list.
```json
{
    "category": null,
    "reason": "Agent outperforms on null-category prediction markets"
}
```
Active only while hypothesis is confirmed. No strength scaling — binary on/off.

**`category_avoid`**: Add a category to the strategy's avoid list.
```json
{
    "category": "Match Winner",
    "reason": "Sports markets have no alpha"
}
```
Active only while hypothesis is confirmed. Binary on/off.

**`model_preference`**: Suggest a model for estimation on matching markets.
```json
{
    "model": "claude-sonnet-4-20250514",
    "reason": "Sonnet shows better calibration on this tier"
}
```
Advisory — logged but not enforced until model-switching is implemented.

**`weight_adjustment`**: Scale Kelly position sizing for matching markets.
```json
{
    "kelly_multiplier": 1.2,
    "reason": "Higher confidence in this tier justifies slightly larger positions"
}
```
Effective multiplier = `1.0 + (config.kelly_multiplier - 1.0) * confidence * base_strength`. At full confidence, applies the full multiplier. At zero confidence, multiplier is 1.0 (neutral).

#### Action activation and deactivation

Actions are activated when `evaluate()` confirms a hypothesis:
- Set `active=1`, `activated_at=now()` on all actions for that hypothesis.

Actions are deactivated when a hypothesis is demoted (invalidated) or when `decay_check()` drops confidence below the critical 0.25 threshold:
- Set `active=0`, `deactivated_at=now()`.

#### `load_active_hypothesis_actions()`

```python
def load_active_hypothesis_actions(
    db_path: Path | None = None,
) -> list[dict]:
    """Load all active hypothesis actions with current effective strength.

    Returns list of dicts, each containing:
    - hypothesis_id: int
    - hypothesis_name: str
    - action_type: str ('edge_override', 'category_target', etc.)
    - config: dict (parsed JSON)
    - base_strength: float
    - effective_strength: float (base_strength * hypothesis confidence_score)
    - hypothesis_confidence: float

    Only returns actions where active=1 and the parent hypothesis
    has status='confirmed'.
    """
```

**SQL**:
```sql
SELECT a.id, a.hypothesis_id, a.action_type, a.config, a.base_strength,
       h.name as hypothesis_name, h.confidence_score
FROM bt_hypothesis_actions a
JOIN bt_hypotheses h ON a.hypothesis_id = h.id
WHERE a.active = 1 AND h.status = 'confirmed'
ORDER BY h.confidence_score DESC
```

The `effective_strength` is computed in Python: `base_strength * confidence_score`.

### 5. Integration points

#### 5a. `simulator.py` — hypothesis_id parameter

**Changes to `run_simulation()`**:

```python
def run_simulation(
    markets: list[dict],
    horizon: int = DEFAULT_HORIZON,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    bankroll: float = DEFAULT_BANKROLL,
    fee_rate: float = DEFAULT_FEE_RATE,
    dry_run: bool = False,
    db_path: Path | None = None,
    hypothesis_id: int | None = None,  # NEW PARAMETER
) -> dict:
```

**Data flow**:
1. If `hypothesis_id` is not None, include it in the `config` JSON written to `bt_simulation_runs`.
2. After the simulation completes (after the `UPDATE bt_simulation_runs` block at the end), if `hypothesis_id` is not None, auto-record evidence:

```python
if hypothesis_id is not None:
    _record_hypothesis_evidence(
        hypothesis_id=hypothesis_id,
        run_id=run_id,
        avg_agent_brier=avg_agent_brier,
        avg_market_brier=avg_market_brier,
        total_pnl=total_pnl,
        valid_trials=valid_trials,
        db_path=path,
    )
```

**New helper in `simulator.py`**:

```python
def _record_hypothesis_evidence(
    hypothesis_id: int,
    run_id: int,
    avg_agent_brier: float | None,
    avg_market_brier: float | None,
    total_pnl: float,
    valid_trials: int,
    db_path: Path,
) -> None:
    """Auto-record evidence for a hypothesis after simulation."""
    from polymarket_agent.backtest.hypothesis import record_evidence

    brier_diff = None
    if avg_agent_brier is not None and avg_market_brier is not None:
        brier_diff = avg_agent_brier - avg_market_brier

    # Compute p-value from per-trial Brier scores
    p_value = None
    effect_size = None
    if valid_trials >= 5:
        p_value, effect_size = _compute_paired_stats(run_id, db_path)

    supports = None
    if brier_diff is not None and valid_trials >= 5:
        supports = 1 if brier_diff < 0 else 0

    record_evidence(
        hypothesis_id=hypothesis_id,
        run_id=run_id,
        trial_count=valid_trials,
        agent_brier=avg_agent_brier,
        market_brier=avg_market_brier,
        brier_diff=brier_diff,
        simulated_pnl=total_pnl,
        p_value=p_value,
        effect_size=effect_size,
        supports_hypothesis=supports,
        db_path=db_path,
    )


def _compute_paired_stats(run_id: int, db_path: Path) -> tuple[float | None, float | None]:
    """Compute paired t-test p-value and Cohen's d from per-trial Brier scores."""
    import math

    with get_backtest_db(db_path) as conn:
        rows = conn.execute(
            """SELECT agent_brier, market_brier
            FROM bt_simulation_trials
            WHERE run_id = ? AND agent_brier IS NOT NULL AND market_brier IS NOT NULL""",
            (run_id,),
        ).fetchall()

    if len(rows) < 5:
        return None, None

    diffs = [r["agent_brier"] - r["market_brier"] for r in rows]
    n = len(diffs)
    mean_diff = sum(diffs) / n
    var_diff = sum((d - mean_diff) ** 2 for d in diffs) / (n - 1)
    sd_diff = math.sqrt(var_diff) if var_diff > 0 else 0.001

    # t-statistic
    t_stat = mean_diff / (sd_diff / math.sqrt(n))

    # Two-tailed p-value approximation using normal distribution for large n
    # For small n, this is an approximation; acceptable given our minimum n=30 for confirmation
    z = abs(t_stat)
    # Approximation: p ~ 2 * exp(-0.5 * z^2) / (z * sqrt(2*pi)) for large z
    # Use a simple lookup / formula
    p_value = _approx_two_tailed_p(z, n - 1)

    # Cohen's d
    effect_size = mean_diff / sd_diff if sd_diff > 0 else 0.0

    return p_value, effect_size
```

Note: `_approx_two_tailed_p` will use `math.erfc` for the normal approximation. For sample sizes >= 30, this is sufficiently accurate. No external dependency needed.

#### 5b. `strategy.py` — Merge hypothesis actions into config

**Changes to `load_strategy_config()`**:

```python
def load_strategy_config(path: Path | None = None) -> dict:
    """Load strategy.yaml, then merge active hypothesis actions."""
    config_path = path or settings.strategy_config_path
    # ... existing YAML loading logic ...

    # Merge hypothesis-driven actions
    try:
        from polymarket_agent.backtest.hypothesis import load_active_hypothesis_actions
        actions = load_active_hypothesis_actions()
        config = _merge_hypothesis_actions(config, actions)
    except Exception as e:
        logger.warning("Failed to load hypothesis actions: %s", e)

    return config
```

**New helper**:

```python
def _merge_hypothesis_actions(config: dict, actions: list[dict]) -> dict:
    """Merge active hypothesis actions into strategy config.

    - category_target actions append to market_selection.target_categories
    - category_avoid actions append to market_selection.avoid_categories
    - edge_override actions add to edge_thresholds.category_overrides
      (with strength scaling applied)
    - weight_adjustment and model_preference are stored in a new
      'hypothesis_actions' key for downstream consumers

    Does not modify actions that conflict with explicit user config
    (user overrides always win).
    """
    ms = config.setdefault("market_selection", {})
    et = config.setdefault("edge_thresholds", {})
    ha = config.setdefault("hypothesis_actions", [])

    for action in actions:
        atype = action["action_type"]
        cfg = action["config"]
        strength = action["effective_strength"]

        if atype == "category_target":
            targets = ms.setdefault("target_categories", [])
            cat = cfg.get("category")
            if cat and cat not in targets:
                targets.append(cat)

        elif atype == "category_avoid":
            avoids = ms.setdefault("avoid_categories", [])
            cat = cfg.get("category")
            if cat and cat not in avoids:
                avoids.append(cat)

        elif atype == "edge_override":
            overrides = et.setdefault("category_overrides", {})
            applies_to = cfg.get("applies_to", "default")
            base_thresh = cfg.get("base_threshold", 0.10)
            # Scale: at full strength, use base_threshold
            # At zero strength, don't override
            if strength > 0.1:  # Minimum strength to apply
                effective = base_thresh * (1.0 + (1.0 - strength) * 0.5)
                if applies_to not in overrides:  # Don't override user-set values
                    overrides[applies_to] = round(effective, 4)

        # Store all actions for downstream consumers
        ha.append(action)

    return config
```

#### 5c. `edge.py` — Query hypothesis actions for per-market overrides

**Changes to `compute_required_edge()`**:

```python
def compute_required_edge(
    market: Market,
    confidence_width: float = 0.30,
    spread_width: float = 0.0,
    category_brier: float | None = None,
    strategy_config: dict | None = None,
) -> float:
```

No signature change. The hypothesis actions are already merged into `strategy_config` by `load_strategy_config()` (Decision 5b), so `edge_override` actions flow through the existing `category_overrides` lookup:

```python
# Existing code — already handles hypothesis-injected overrides
if strategy_config and market.category:
    overrides = strategy_config.get("edge_thresholds", {}).get("category_overrides", {})
    if market.category in overrides:
        base = float(overrides[market.category])
```

For `weight_adjustment` actions (Kelly multiplier scaling), `build_recommendation()` checks the `hypothesis_actions` key in the strategy config:

```python
# Addition to build_recommendation(), after computing `size`:
if strategy_config:
    for ha in strategy_config.get("hypothesis_actions", []):
        if ha["action_type"] == "weight_adjustment":
            cfg = ha["config"]
            strength = ha["effective_strength"]
            multiplier = 1.0 + (cfg.get("kelly_multiplier", 1.0) - 1.0) * strength
            size = round(size * multiplier, 2)
```

#### 5d. `calibration.py` — Append hypothesis summaries to LLM prompts

**Changes to `export_calibration_for_llm()`**:

After the existing category breakdown section, append confirmed hypothesis summaries:

```python
def export_calibration_for_llm(min_resolved: int = 20) -> str:
    # ... existing code through category breakdown ...

    # Hypothesis awareness
    try:
        from polymarket_agent.backtest.hypothesis import get_confirmed_hypotheses_summary
        hyp_text = get_confirmed_hypotheses_summary()
        if hyp_text:
            lines.append("")
            lines.append(hyp_text)
    except Exception:
        pass  # Hypothesis system not yet initialized or no confirmed hypotheses

    return "\n".join(lines)
```

**New function in `hypothesis.py`**:

```python
def get_confirmed_hypotheses_summary(db_path: Path | None = None) -> str | None:
    """Generate a text summary of confirmed hypotheses for LLM prompts.

    Returns markdown text or None if no confirmed hypotheses.
    """
    with get_backtest_db(path) as conn:
        rows = conn.execute(
            """SELECT name, description, confidence_score
            FROM bt_hypotheses WHERE status = 'confirmed'
            ORDER BY confidence_score DESC"""
        ).fetchall()

    if not rows:
        return None

    lines = [
        "## Validated Findings from Backtesting",
        "The following hypotheses have been confirmed through simulation:",
    ]
    for row in rows:
        lines.append(
            f"- **{row['name']}** (confidence: {row['confidence_score']:.0%}): "
            f"{row['description']}"
        )
    lines.append("")
    lines.append(
        "Consider these findings when calibrating your estimate. They represent "
        "statistically validated patterns in your own prediction performance."
    )

    return "\n".join(lines)
```

#### 5e. `scheduler.py` — Cross-reference hypotheses in drift check

**Changes to `_check_strategy_drift()`**:

After the existing per-category Brier analysis, add hypothesis cross-referencing:

```python
def _check_strategy_drift(self):
    """Compare per-category Brier scores against strategy expectations."""
    # ... existing code ...

    # Cross-reference confirmed hypotheses
    try:
        from polymarket_agent.backtest.hypothesis import load_confirmed_hypotheses
        hypotheses = load_confirmed_hypotheses()
        for hyp in hypotheses:
            # Check if live calibration data contradicts the hypothesis
            cat = hyp.get("category_filter")
            if cat and cat in {row["category"] for row in rows}:
                matching = [r for r in rows if r["category"] == cat]
                if matching:
                    live_brier = matching[0]["brier"]
                    live_count = matching[0]["count"]
                    if live_count >= 20 and live_brier > 0.25:
                        logger.warning(
                            "Hypothesis '%s' may be invalid: live Brier=%.4f "
                            "on %d predictions (expected agent advantage)",
                            hyp["name"], live_brier, live_count,
                        )
    except Exception as e:
        logger.debug("Hypothesis cross-reference skipped: %s", e)
```

**New helper in `hypothesis.py`**:

```python
def load_confirmed_hypotheses(db_path: Path | None = None) -> list[dict]:
    """Load all confirmed hypotheses as dicts.

    Returns list of dicts with: id, name, description, confidence_score,
    category_filter, volume_min, volume_max.
    """
```

### 6. CLI commands

**Decision**: Add a `hypothesis` subgroup under `backtest` with five commands.

All commands go in `cli/main.py` under the existing `backtest` group.

```python
@backtest.group()
def hypothesis():
    """Manage testable hypotheses about agent performance."""
    pass
```

#### `hypothesis list`

```python
@hypothesis.command("list")
@click.option("--status", "-s", type=click.Choice(
    ["proposed", "testing", "confirmed", "rejected", "invalidated", "all"]
), default="all", help="Filter by status")
def hypothesis_list(status: str):
    """List all hypotheses with their current status and confidence."""
```

**Output**: Rich table with columns: ID, Name, Status, Confidence, Evidence Count, Last Evaluated, Category Filter, Volume Range. Color-coded by status (green=confirmed, red=rejected, yellow=testing, dim=proposed, strikethrough=invalidated).

#### `hypothesis propose`

```python
@hypothesis.command("propose")
@click.option("--name", "-n", required=True, help="Short unique name")
@click.option("--description", "-d", required=True, help="Testable description")
@click.option("--category", "-c", default=None, help="Category filter (NULL for prediction markets, * for all)")
@click.option("--volume-min", type=float, default=None, help="Minimum volume")
@click.option("--volume-max", type=float, default=None, help="Maximum volume")
@click.option("--regime", "-r", default=None, help="Temporal regime filter")
@click.option("--horizon", type=int, default=None, help="Horizon days filter")
@click.option("--half-life", type=int, default=90, help="Confidence decay half-life in days")
def hypothesis_propose(name, description, category, volume_min, volume_max, regime, horizon, half_life):
    """Propose a new hypothesis about agent performance."""
```

**Output**: Rich panel showing the created hypothesis with all parameters, its ID, and instructions for next step (`polymarket backtest hypothesis test <id>`).

#### `hypothesis test`

```python
@hypothesis.command("test")
@click.argument("hypothesis_id", type=int)
@click.option("--count", "-n", type=int, default=50, help="Markets to simulate")
@click.option("--dry-run", is_flag=True, help="Preview market selection only")
def hypothesis_test(hypothesis_id: int, count: int, dry_run: bool):
    """Run targeted simulation to test a hypothesis."""
```

**Output**: Shows the hypothesis being tested, then delegates to the simulation progress display. On completion, shows the evidence recorded and current evaluation status.

#### `hypothesis evaluate`

```python
@hypothesis.command("evaluate")
@click.argument("hypothesis_id", type=int)
def hypothesis_evaluate(hypothesis_id: int):
    """Evaluate evidence and update hypothesis status."""
```

**Output**: Rich panel showing: all evidence records (table), weighted metrics, status transition (if any), confidence score, and active actions (if confirmed).

#### `hypothesis retest`

```python
@hypothesis.command("retest")
@click.argument("hypothesis_id", type=int)
@click.option("--count", "-n", type=int, default=50, help="Markets to simulate")
def hypothesis_retest(hypothesis_id: int, count: int):
    """Run fresh simulation and re-evaluate with recency weighting."""
```

**Output**: Same as `test` followed by `evaluate`.

#### `hypothesis actions`

```python
@hypothesis.command("actions")
def hypothesis_actions():
    """Display all active hypothesis-driven actions."""
```

**Output**: Rich table with columns: Hypothesis, Action Type, Config Summary, Base Strength, Effective Strength, Active Since. Grouped by hypothesis.

#### `hypothesis decay-check`

```python
@hypothesis.command("decay-check")
def hypothesis_decay_check():
    """Check confirmed hypotheses for confidence decay."""
```

**Output**: Rich table showing each confirmed hypothesis with: Name, Original Confidence, Current (Decayed) Confidence, Days Since Evidence, Retest Threshold, Recommendation (OK / RETEST / INVALIDATE).

### 7. Seed hypotheses

**Decision**: Implement seeding as a function in `hypothesis.py` called from `init_backtest_db()`, similar to how regimes are seeded via `_seed_regimes()`.

```python
SEED_HYPOTHESES = [
    {
        "name": "probable-no-alpha",
        "description": "Agent outperforms market on markets where the market price implies probable NO (price < 0.30), by tempering overconfidence on unlikely YES outcomes.",
        "category_filter": None,  # null-category prediction markets
        "volume_min": 100_000,
        "volume_max": None,
        "temporal_filter": json.dumps({"horizon_days": 7}),
        "actions": [
            {
                "action_type": "edge_override",
                "config": json.dumps({"base_threshold": 0.08, "applies_to": "probable_no"}),
                "base_strength": 1.0,
            }
        ],
    },
    {
        "name": "mid-volume-sweet-spot",
        "description": "Agent has alpha in the $100K-$1M volume tier where markets are liquid enough to be real but thin enough for mispricing.",
        "category_filter": None,
        "volume_min": 100_000,
        "volume_max": 1_000_000,
        "temporal_filter": json.dumps({"horizon_days": 7}),
        "actions": [
            {
                "action_type": "edge_override",
                "config": json.dumps({"base_threshold": 0.08, "applies_to": "100K-1M"}),
                "base_strength": 1.0,
            },
            {
                "action_type": "weight_adjustment",
                "config": json.dumps({"kelly_multiplier": 1.2, "reason": "Sweet spot tier"}),
                "base_strength": 0.8,
            },
        ],
    },
    {
        "name": "high-volume-efficient",
        "description": "Agent is market-neutral or slightly worse on >$1M volume markets, which are too efficient to beat.",
        "category_filter": None,
        "volume_min": 1_000_000,
        "volume_max": None,
        "temporal_filter": json.dumps({"horizon_days": 7}),
        "actions": [
            {
                "action_type": "edge_override",
                "config": json.dumps({"base_threshold": 0.12, "applies_to": ">1M"}),
                "base_strength": 1.0,
            },
            {
                "action_type": "weight_adjustment",
                "config": json.dumps({"kelly_multiplier": 0.8, "reason": "Efficient markets need smaller bets"}),
                "base_strength": 1.0,
            },
        ],
    },
    {
        "name": "sports-no-alpha",
        "description": "Agent has no demonstrated alpha on sports markets (named categories like Match Winner, O/U, Spread), likely due to specialized pricing by sports bettors.",
        "category_filter": "*",  # All categories (we test named ones specifically)
        "volume_min": 100_000,
        "volume_max": None,
        "temporal_filter": None,
        "actions": [
            {
                "action_type": "category_avoid",
                "config": json.dumps({"category": "Match Winner", "reason": "No demonstrated alpha"}),
                "base_strength": 1.0,
            },
        ],
    },
]


def seed_hypotheses(db_path: Path | None = None) -> int:
    """Seed initial hypotheses if the table is empty. Returns count seeded."""
    path = db_path or settings.backtest_db_path
    with get_backtest_db(path) as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM bt_hypotheses").fetchone()["c"]
        if count > 0:
            return 0

        seeded = 0
        for hyp in SEED_HYPOTHESES:
            actions = hyp.pop("actions", [])
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                """INSERT INTO bt_hypotheses
                (name, description, status, category_filter, volume_min, volume_max,
                 temporal_filter, proposed_at, proposed_by)
                VALUES (?, ?, 'proposed', ?, ?, ?, ?, ?, 'seed')""",
                (hyp["name"], hyp["description"], hyp.get("category_filter"),
                 hyp.get("volume_min"), hyp.get("volume_max"),
                 hyp.get("temporal_filter"), now),
            )
            hyp_id = cursor.lastrowid

            for action in actions:
                conn.execute(
                    """INSERT INTO bt_hypothesis_actions
                    (hypothesis_id, action_type, config, base_strength, active, created_at)
                    VALUES (?, ?, ?, ?, 0, ?)""",
                    (hyp_id, action["action_type"], action["config"],
                     action["base_strength"], now),
                )
            seeded += 1

    return seeded
```

**Integration with `init_backtest_db()`** in `database.py`:

```python
def init_backtest_db(db_path: Path | None = None) -> None:
    """Initialize the backtest database schema and seed data."""
    conn = get_backtest_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        _seed_regimes(conn)
        conn.commit()
    finally:
        conn.close()

    # Seed hypotheses (uses its own connection)
    from polymarket_agent.backtest.hypothesis import seed_hypotheses
    seed_hypotheses(db_path)
```

## Risks / Trade-offs

**[Small sample sizes in early evidence]** The confirmation threshold of n >= 30 means a single simulation run of 50 markets could confirm a hypothesis after just one test. This is by design — we want fast iteration — but the confidence score and decay mechanism provide the safety net. A hypothesis confirmed on n=30 starts with moderate confidence that decays unless reinforced.

**[Confidence decay may be too aggressive]** A 90-day half-life means a hypothesis loses half its influence every 3 months. For stable structural hypotheses (like "sports markets have no alpha"), this may be too fast. Mitigation: the half-life is per-hypothesis configurable. Structural hypotheses can have 180-day or longer half-lives.

**[Action strength scaling adds complexity to edge computation]** The multiplication chain (base_threshold * confidence * base_strength * scaling factors) could produce unexpected thresholds. Mitigation: all computed thresholds are still clamped to [floor, ceiling] in `compute_required_edge()`. The hypothesis system can only adjust within the existing guardrails.

**[Paired t-test p-value approximation]** Using normal approximation instead of scipy's t-distribution. For n >= 30 (the confirmation threshold), the normal approximation is accurate to within 1-2% of the true p-value. Avoids adding scipy as a dependency.

**[Strategy config merge ordering]** If both a user's `strategy.yaml` and hypothesis actions set a category override for the same category, the user's value wins (hypothesis actions only insert if key is absent). This is intentional — explicit user configuration always takes precedence over automated hypothesis actions.
