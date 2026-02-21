## Context

Run #3 showed the agent beats the market on Brier score (-0.0113) across 20 trials with >$1M null-category markets at a 7-day horizon using Sonnet. But this is one model, one category slice, one volume tier, and only 20 trials. We need to vary model, category, volume tier, and temporal distance from training cutoffs, then test whether observed differences are statistically significant.

The existing simulation harness (`simulator.py`) runs a single model against randomly selected markets and persists results in `bt_simulation_runs` / `bt_simulation_trials`. The analysis library (`analysis.py`) provides per-category and per-volume-tier breakdowns but no cross-model comparison or statistical significance testing.

This design extends the harness to support multi-model evaluation with stratified sampling, temporal confidence weighting, and statistical comparison -- answering: which model, in which category and volume tier, genuinely beats the market after accounting for training data contamination?

## Goals / Non-Goals

**Goals:**
- Run the same market set through multiple models (Haiku, Sonnet, Opus) for paired comparison
- Sample markets across category and volume tier dimensions with minimum per-cell counts
- Discount Brier scores for markets that may be in a model's training window
- Produce confidence intervals and significance tests on Brier score differences
- Expose the full workflow through a single `backtest evaluate` CLI command
- Budget-aware execution: stop before blowing past a cost ceiling

**Non-Goals:**
- Prompt optimization (follow-up after we know which model/category combos have signal)
- Live/paper trading integration from evaluation results
- Automated model selection for production use (human reviews the report)
- Multi-horizon evaluation in a single run (each run uses one horizon; run multiple evaluations to compare horizons)

## Decisions

### 1. Model override via `run_simulation()` parameter, not global config

**Decision**: Add a `model` parameter to `run_simulation()`. When provided, it constructs the `LLMClient` and passes that model to `ProbabilityEstimator`. The model identifier is stored per trial in a new `model` column on `bt_simulation_trials`.

**Rationale**: The existing code path creates an `LLMClient()` inside `run_simulation()` and uses `settings.analysis_model` implicitly. Adding a parameter keeps the function self-contained. Storing the model per trial (not just per run) supports future mixed-model runs and makes queries simple.

**Implementation**:
```python
def run_simulation(
    markets: list[dict],
    horizon: int = DEFAULT_HORIZON,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    bankroll: float = DEFAULT_BANKROLL,
    fee_rate: float = DEFAULT_FEE_RATE,
    dry_run: bool = False,
    db_path: Path | None = None,
    model: str | None = None,         # NEW
    market_ids: list[str] | None = None,  # NEW: run against pre-selected IDs
) -> dict:
```

When `model` is provided:
- `LLMClient()` is created normally (single client, tracks usage)
- The `model` string is passed through to `estimator.estimate()` via a new `model` parameter on `ProbabilityEstimator.estimate()`, which forwards it to each `llm.complete_json()` call
- The `model` string is stored in `config` JSON and in each trial row
- If `model` is None, behavior is unchanged (uses `settings.analysis_model`)

`ProbabilityEstimator.estimate()` change:
```python
def estimate(self, market: Market, calibration_text: str | None = None,
             model: str | None = None) -> ProbabilityEstimate:
    # model is forwarded to each llm.complete_json(model=model) call
    # If None, complete_json() falls back to settings.analysis_model
```

This is safe because `LLMClient.complete()` already accepts an optional `model` parameter and falls back to `settings.analysis_model` when None.

### 2. Stratified market selection as a new function, not a modification of `select_markets()`

**Decision**: Add `select_markets_stratified()` alongside the existing `select_markets()`. The new function discovers category and volume tier dimensions from the database, then samples `n_per_cell` markets from each (category x volume_tier) cell.

**Rationale**: The existing `select_markets()` does simple random sampling with filters. Stratified sampling is a fundamentally different selection strategy -- bolting it onto the existing function would add complexity and risk breaking existing simulation runs.

**Volume tiers** (constants in `simulator.py`):
```python
VOLUME_TIERS = {
    ">10M":    (10_000_000, None),
    "1M-10M":  (1_000_000, 10_000_000),
    "100K-1M": (100_000, 1_000_000),
    "10K-100K": (10_000, 100_000),
}
```

These match the existing `simulation_by_volume_tier()` breakdowns in `analysis.py`.

**Category discovery**: Query distinct categories from `bt_markets` where the market is eligible (has_history=1, resolved YES/NO, price data at horizon). Include NULL as a category (the primary prediction market category).

**Function signature**:
```python
def select_markets_stratified(
    n_per_cell: int = 20,
    categories: list[str | None] | None = None,  # None = auto-discover
    volume_tiers: dict[str, tuple[float, float | None]] | None = None,  # None = defaults
    horizon: int = DEFAULT_HORIZON,
    db_path: Path | None = None,
) -> tuple[list[dict], dict]:
    """Select markets with stratified sampling across category x volume tier.

    Returns:
        (markets, cell_counts) where cell_counts is
        {(category, tier): {"requested": n, "available": m, "selected": k}}
    """
```

**SQL for category discovery**:
```sql
SELECT DISTINCT m.category
FROM bt_markets m
WHERE m.has_history = 1
  AND m.resolution_outcome IN ('YES', 'NO')
  AND EXISTS (
      SELECT 1 FROM bt_price_history p
      WHERE p.market_id = m.id
      AND p.timestamp <= CAST(strftime('%s', m.end_date, '-7 days') AS INTEGER)
  )
ORDER BY m.category NULLS FIRST
```

**SQL for cell sampling** (per category x volume tier):
```sql
SELECT m.id, m.question, m.description, m.category, m.end_date,
       m.volume, m.liquidity, m.resolution_outcome, m.yes_token,
       m.no_token, m.event_id
FROM bt_markets m
WHERE m.has_history = 1
  AND m.resolution_outcome IN ('YES', 'NO')
  AND m.volume >= ? AND (m.volume < ? OR ? IS NULL)
  AND (m.category IS ? OR (m.category IS NULL AND ? IS NULL))
  AND EXISTS (
      SELECT 1 FROM bt_price_history p
      WHERE p.market_id = m.id
      AND p.timestamp <= CAST(strftime('%s', m.end_date, '-{horizon} days') AS INTEGER)
  )
ORDER BY RANDOM()
LIMIT ?
```

**Min-per-cell enforcement**: If a cell has fewer than `n_per_cell` eligible markets, select all available and record the shortfall in `cell_counts`. The final report flags cells with < 20 trials as "insufficient data." No redistribution from sparse cells to dense cells -- that would bias the sample.

### 3. Progressive multi-model orchestration as a new function

**Decision**: Add `run_multi_model_evaluation()` in `simulator.py` that orchestrates running the same market set through models in cost order. This function calls `run_simulation()` for each model, not replacing it.

**Function signature**:
```python
def run_multi_model_evaluation(
    markets: list[dict],
    models: list[str] | None = None,
    horizon: int = DEFAULT_HORIZON,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    bankroll: float = DEFAULT_BANKROLL,
    fee_rate: float = DEFAULT_FEE_RATE,
    budget: float | None = None,
    progressive: bool = True,
    progress_callback: Callable | None = None,
    db_path: Path | None = None,
) -> dict:
    """Run evaluation across multiple models on the same market set.

    Args:
        models: Model IDs in execution order. Default: Haiku, Sonnet, Opus.
        budget: Maximum total LLM cost in USD. None = no limit.
        progressive: If True, yield intermediate results after each model
                     via progress_callback. The callback receives the model
                     name, run result, and cross-model comparison so far.
                     It returns True to continue, False to stop.
        progress_callback: Callable[[str, dict, dict], bool] for progressive mode.

    Returns:
        {"runs": {model: run_result}, "comparison": cross_model_comparison_dict}
    """
```

**Default model order** (by cost):
```python
EVALUATION_MODELS = [
    "claude-haiku-4-5-20251001",   # ~$0.005/trial
    "claude-sonnet-4-6",           # ~$0.023/trial
    "claude-opus-4-6",             # ~$0.12/trial
]
```

**Data flow**:
```
CLI evaluate command
    |
    v
select_markets_stratified()  -->  market set (frozen list of market dicts)
    |
    v
run_multi_model_evaluation(markets, models=[haiku, sonnet, opus])
    |
    +---> run_simulation(markets, model="haiku") --> run_id_1
    |         |
    |         v
    |     progress_callback("haiku", result_1, comparison_so_far)
    |         | returns True? continue : stop
    |         v
    +---> run_simulation(markets, model="sonnet") --> run_id_2
    |         |
    |         v
    |     progress_callback("sonnet", result_2, comparison_so_far)
    |         | returns True? continue : stop
    |         v
    +---> run_simulation(markets, model="opus") --> run_id_3
    |
    v
cross_model_comparison(run_ids=[1,2,3])  -->  final report
```

**Budget enforcement**: Before starting each model, estimate cost as `len(markets) * MODEL_COST_PER_TRIAL[model]`. If `spent + estimated > budget`, skip the model and log a warning. Remaining budget is recalculated after each model completes using actual cost from `run_simulation()` return value.

**Cost-per-trial estimates** (added to `simulator.py`):
```python
MODEL_COST_PER_TRIAL = {
    "claude-haiku-4-5-20251001": 0.005,
    "claude-sonnet-4-6": 0.023,
    "claude-opus-4-6": 0.12,
}
```

### 4. Temporal confidence weighting via training recency scores

**Decision**: Add `training_recency_score()` and `weighted_brier()` functions to `analysis.py`. The recency score is stored per trial in a new `training_recency_score` column on `bt_simulation_trials`.

**Model training cutoffs** (dict in `analysis.py`):
```python
MODEL_TRAINING_CUTOFFS = {
    "claude-haiku-4-5-20251001": "2025-04-01",
    "claude-sonnet-4-6": "2025-04-01",
    "claude-opus-4-6": "2025-04-01",
}
```

These are best-guess knowledge cutoff dates. They can be updated as Anthropic publishes official cutoffs. The dict is the single source of truth.

**Formula**: For a trial with model `m` and market resolution date `d`:
```
cutoff = MODEL_TRAINING_CUTOFFS[m]
days_after_cutoff = (d - cutoff).days

if days_after_cutoff <= 0:
    score = 0.0  # resolved during training window, fully suspect
elif days_after_cutoff >= 180:
    score = 1.0  # 6+ months after cutoff, fully clean
else:
    score = days_after_cutoff / 180.0  # linear interpolation
```

**Function signature**:
```python
def training_recency_score(
    resolution_date: str,
    model: str,
) -> float:
    """Compute training recency score (0.0 = in training window, 1.0 = clean).

    Linear interpolation from 0.0 to 1.0 over 180 days past the model's
    training cutoff date.
    """
```

**When it's computed**: Inside `run_simulation()`, after computing the trial's Brier scores. The score is computed from `market_dict["end_date"]` and the `model` parameter, then stored in the trial row.

**Weighted Brier aggregation**:
```python
def weighted_brier(
    trials: list[dict],
    weight_key: str = "training_recency_score",
) -> dict:
    """Compute weighted mean Brier score using per-trial weights.

    Returns {"agent_brier_weighted": float, "market_brier_weighted": float,
             "brier_diff_weighted": float, "total_weight": float,
             "trial_count": int}.
    """
    # weighted_mean = sum(w_i * brier_i) / sum(w_i)
```

### 5. Statistical comparison via bootstrap

**Decision**: Add `brier_confidence_interval()` and `cross_model_comparison()` to `analysis.py`. Use percentile bootstrap (no scipy dependency).

**Bootstrap implementation**:
```python
def brier_confidence_interval(
    agent_briers: list[float],
    market_briers: list[float],
    weights: list[float] | None = None,
    n_bootstrap: int = 10_000,
    confidence: float = 0.95,
    seed: int | None = None,
) -> dict:
    """Bootstrap confidence interval on Brier score difference.

    Computes paired differences (agent_brier[i] - market_brier[i]),
    then bootstraps the weighted mean of those differences.

    Returns:
        {"mean_diff": float, "ci_low": float, "ci_high": float,
         "p_value": float, "n": int, "significant": bool}
    """
```

**Pseudocode**:
```
diffs = [a - m for a, m in zip(agent_briers, market_briers)]
weights = weights or [1.0] * len(diffs)
observed_mean = weighted_mean(diffs, weights)

bootstrap_means = []
rng = random.Random(seed)
for _ in range(n_bootstrap):
    indices = rng.choices(range(len(diffs)), k=len(diffs))
    sample_diffs = [diffs[i] for i in indices]
    sample_weights = [weights[i] for i in indices]
    bootstrap_means.append(weighted_mean(sample_diffs, sample_weights))

bootstrap_means.sort()
alpha = 1 - confidence
ci_low = bootstrap_means[int(alpha/2 * n_bootstrap)]
ci_high = bootstrap_means[int((1 - alpha/2) * n_bootstrap)]

# Two-sided p-value: proportion of bootstrap means on wrong side of 0
if observed_mean < 0:
    p_value = sum(1 for b in bootstrap_means if b >= 0) / n_bootstrap
else:
    p_value = sum(1 for b in bootstrap_means if b <= 0) / n_bootstrap

significant = p_value < (1 - confidence)
```

**Cross-model comparison**:
```python
def cross_model_comparison(
    run_ids: list[int],
    db_path: Path | None = None,
) -> dict:
    """Compare Brier scores across simulation runs (typically different models on the same markets).

    Loads trials from each run, pairs them by market_id, computes:
    - Per-model aggregate Brier (unweighted and recency-weighted)
    - Pairwise Brier difference CIs between models
    - Per-cell (category x volume tier) breakdown with sample size warnings

    Returns:
        {"models": {model: summary},
         "pairwise": {(model_a, model_b): ci_dict},
         "by_category": {cat: {model: summary}},
         "by_volume_tier": {tier: {model: summary}},
         "by_cell": {(cat, tier): {model: summary, "n": int, "sufficient": bool}}}
    """
```

**Pairing logic**: For each pair of runs (A, B), find trials with the same `market_id`. Only paired trials are compared. Unpaired trials (e.g., one model failed estimation for a market) are excluded from the pairwise test but included in per-model aggregates.

**Output report format** (Rich tables, rendered by the CLI):

```
Model Comparison (n=80 paired trials)
+---------+--------+---------+--------+---------+------+
| Model   | Brier  | Wtd Brier| vs Mkt | 95% CI  | Sig? |
+---------+--------+---------+--------+---------+------+
| Haiku   | 0.1823 | 0.1756  | -0.005 | [-0.03, +0.02] | No  |
| Sonnet  | 0.1675 | 0.1601  | -0.011 | [-0.04, +0.01] | No  |
| Opus    | 0.1590 | 0.1520  | -0.020 | [-0.05, -0.00] | Yes |
+---------+--------+---------+--------+---------+------+

Pairwise Model Comparison
+------------------+--------+---------+------+
| Comparison       | Diff   | 95% CI  | Sig? |
+------------------+--------+---------+------+
| Sonnet vs Haiku  | -0.015 | [-0.03, +0.00] | No  |
| Opus vs Sonnet   | -0.009 | [-0.02, +0.01] | No  |
| Opus vs Haiku    | -0.023 | [-0.04, -0.01] | Yes |
+------------------+--------+---------+------+

By Category x Model (cells with n < 20 marked *)
+-------------+--------+---------+---------+---+
| Category    | Haiku  | Sonnet  | Opus    | n |
+-------------+--------+---------+---------+---+
| (null)      | -0.005 | -0.013  | -0.021  | 40|
| crypto      | +0.002 | -0.008  | -0.015  | 25|
| politics    | -0.010 | -0.015  | -0.022  | 12*|
+-------------+--------+---------+---------+---+
```

### 6. Database changes

**New columns on `bt_simulation_trials`**:
```sql
ALTER TABLE bt_simulation_trials ADD COLUMN model TEXT;
ALTER TABLE bt_simulation_trials ADD COLUMN training_recency_score REAL;
```

**Migration strategy**: Use `ALTER TABLE ... ADD COLUMN` which is safe for SQLite (no table recreation, no data loss). These are nullable columns, so existing rows get NULL. The migration runs in `init_backtest_db()` using a try/except pattern to handle the case where columns already exist:

```python
def _migrate_simulation_trials(conn: sqlite3.Connection) -> None:
    """Add model and training_recency_score columns if not present."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(bt_simulation_trials)")}
    if "model" not in existing:
        conn.execute("ALTER TABLE bt_simulation_trials ADD COLUMN model TEXT")
    if "training_recency_score" not in existing:
        conn.execute(
            "ALTER TABLE bt_simulation_trials ADD COLUMN training_recency_score REAL"
        )
```

This is called from `init_backtest_db()` after `executescript(SCHEMA_SQL)`. The SCHEMA_SQL itself is updated to include the new columns in the CREATE TABLE statement (so fresh databases get the columns directly).

**New index** (for cross-model queries):
```sql
CREATE INDEX IF NOT EXISTS idx_bt_sim_trials_model ON bt_simulation_trials(model);
```

**Model costs update** in `llm_client.py`:
```python
MODEL_COSTS = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},   # NEW
}
```

### 7. CLI `evaluate` command

**Click command signature**:
```python
@backtest.command("evaluate")
@click.option("--models", "-m", multiple=True,
              help="Models to evaluate (default: haiku, sonnet). "
                   "Specify multiple times: -m haiku -m sonnet -m opus")
@click.option("--trials-per-cell", type=int, default=20,
              help="Minimum trials per category x volume cell (default: 20)")
@click.option("--categories", multiple=True,
              help="Categories to include (default: auto-discover). "
                   "Use 'null' for null-category markets.")
@click.option("--horizon", type=int, default=7,
              help="Days before resolution (default: 7)")
@click.option("--budget", type=float, default=None,
              help="Maximum total LLM cost in USD")
@click.option("--all-at-once", is_flag=True,
              help="Run all models without intermediate prompts (default: progressive)")
@click.option("--dry-run", is_flag=True,
              help="Preview market selection and cost estimate without running")
def evaluate_backtest(
    models: tuple[str, ...],
    trials_per_cell: int,
    categories: tuple[str, ...],
    horizon: int,
    budget: float | None,
    all_at_once: bool,
    dry_run: bool,
):
    """Run multi-model evaluation with stratified sampling and statistical comparison."""
```

**Interactive flow (progressive mode, the default)**:

```
$ polymarket backtest evaluate --budget 50

Evaluation Plan
  Categories: (null), crypto, politics (auto-discovered)
  Volume tiers: >10M, 1M-10M, 100K-1M, 10K-100K
  Trials per cell: 20
  Total cells: 12 (3 categories x 4 tiers)
  Horizon: 7 days

Market Selection
  (null) x >10M:     20 available, 20 selected
  (null) x 1M-10M:   145 available, 20 selected
  (null) x 100K-1M:  312 available, 20 selected
  (null) x 10K-100K: 87 available, 20 selected
  crypto x >10M:     5 available, 5 selected  [!]
  crypto x 1M-10M:   42 available, 20 selected
  ...
  [!] Cells with < 20 markets will be flagged as "insufficient data"

Total markets: 210

Cost Estimate
  Model              | Cost/trial | Trials | Estimated
  -------------------|-----------|--------|----------
  Haiku              | $0.005    | 210    | $1.05
  Sonnet             | $0.023    | 210    | $4.83
  Opus               | $0.120    | 210    | $25.20
  -------------------|-----------|--------|----------
  Total                                    | $31.08

Budget: $50.00 -- all models fit within budget.

Proceed with evaluation? [Y/n] y

--- Stage 1: Haiku ---
Running 210 trials...
[progress bar]

Haiku Results (Run #4)
  Agent Brier: 0.1923 | Market Brier: 0.1788 | Diff: +0.0135
  Weighted Brier (recency-adjusted): 0.1856
  95% CI on diff: [-0.01, +0.04]
  Cost: $0.98
  Remaining budget: $49.02

Continue to Sonnet (~$4.83)? [Y/n] y

--- Stage 2: Sonnet ---
Running 210 trials...
[progress bar]

Sonnet Results (Run #5)
  Agent Brier: 0.1675 | Market Brier: 0.1788 | Diff: -0.0113
  Weighted Brier (recency-adjusted): 0.1601
  95% CI on diff: [-0.04, +0.01]
  Cost: $4.52
  Remaining budget: $44.50

Sonnet vs Haiku: -0.0248 [-0.05, -0.01] *significant*

Continue to Opus (~$25.20)? [Y/n] n

--- Final Report ---
[Rich tables as shown in Decision 5]
```

**Dry-run mode**: Runs `select_markets_stratified()`, prints the cell counts and cost estimate, then exits without calling any LLM.

**Model name resolution**: The CLI accepts short names (`haiku`, `sonnet`, `opus`) and resolves them to full model IDs via a lookup dict:

```python
MODEL_ALIASES = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}
```

If no `--models` specified, defaults to `["haiku", "sonnet"]` (Opus is opt-in due to cost).

## Integration with Existing Code

### Modified functions (new parameters only, backward-compatible)

| Function | Module | Change |
|----------|--------|--------|
| `run_simulation()` | `simulator.py` | Add `model: str \| None = None` parameter. When None, behavior is unchanged. |
| `ProbabilityEstimator.estimate()` | `estimator.py` | Add `model: str \| None = None` parameter. Forwarded to `llm.complete_json(model=model)`. When None, behavior is unchanged. |
| `init_backtest_db()` | `database.py` | Call `_migrate_simulation_trials()` after schema creation. |

### New functions

| Function | Module | Purpose |
|----------|--------|---------|
| `select_markets_stratified()` | `simulator.py` | Stratified sampling by category x volume tier |
| `run_multi_model_evaluation()` | `simulator.py` | Multi-model orchestration with budget/progressive gates |
| `training_recency_score()` | `analysis.py` | Compute per-trial contamination weight |
| `weighted_brier()` | `analysis.py` | Weighted Brier aggregation |
| `brier_confidence_interval()` | `analysis.py` | Bootstrap CI on Brier differences |
| `cross_model_comparison()` | `analysis.py` | Full cross-model comparison report |
| `_migrate_simulation_trials()` | `database.py` | Add new columns to existing tables |
| `evaluate_backtest()` | `cli/main.py` | CLI command for multi-model evaluation |

### New constants

| Constant | Module | Purpose |
|----------|--------|---------|
| `VOLUME_TIERS` | `simulator.py` | Volume tier boundaries for stratified sampling |
| `EVALUATION_MODELS` | `simulator.py` | Default model list in cost order |
| `MODEL_COST_PER_TRIAL` | `simulator.py` | Per-model cost estimates for budget planning |
| `MODEL_TRAINING_CUTOFFS` | `analysis.py` | Training data cutoff dates by model |
| `MODEL_ALIASES` | `cli/main.py` | Short name to full model ID mapping |
| Opus entry in `MODEL_COSTS` | `llm_client.py` | Opus pricing for cost tracking |

### Backward compatibility guarantees

- Existing `select_markets()` is untouched. New code uses `select_markets_stratified()`.
- `run_simulation()` with no `model` parameter behaves exactly as before (uses `settings.analysis_model`).
- Existing `bt_simulation_trials` rows have `model = NULL` and `training_recency_score = NULL`. All new analysis functions handle NULL gracefully (treat NULL model as "unknown", NULL recency as 1.0).
- Existing CLI commands (`backtest simulate`, `backtest results`) are unchanged.
- No new pip dependencies. Bootstrap uses `random.choices()` from stdlib.

## Risks / Trade-offs

**[Paired comparison requires identical market sets]** All models must run against the exact same markets for paired tests to be valid. If one model fails estimation for a market (e.g., JSON parse error), that trial is excluded from pairwise comparison but included in per-model aggregates. Risk: if failure rates differ by model, paired sample shrinks. Mitigation: the JSON extraction + retry logic in `LLMClient.complete_json()` keeps failure rates near zero across all models.

**[Training cutoff dates are approximate]** The `MODEL_TRAINING_CUTOFFS` dict contains best-guess dates. If the actual cutoff is earlier, we over-weight contaminated trials. If later, we under-weight clean ones. Mitigation: the 180-day linear ramp is deliberately conservative -- even a 2-month error in cutoff estimation only shifts scores by ~0.33 on the weight scale, not a binary flip.

**[Opus cost is high]** At $0.12/trial, 210 trials costs ~$25. A full 3-model evaluation is ~$31. Mitigation: progressive mode lets the operator stop after Haiku+Sonnet ($6) if those already answer the question. Budget cap prevents accidental overruns.

**[Stratified sampling may produce small cells]** Some (category x volume_tier) combinations may have fewer than 20 eligible markets. Mitigation: the sampler reports cell counts upfront. The report flags cells with < 20 trials. The operator can reduce the number of categories or tiers to concentrate samples.

**[Bootstrap is slower than parametric tests]** 10K resamples x multiple comparisons takes ~0.5s on typical hardware. This is negligible compared to the minutes spent on LLM calls. No mitigation needed.
