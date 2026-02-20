## 1. Data Model

- [ ] 1.1 Add `bt_hypotheses` CREATE TABLE to `database.py` SCHEMA_SQL with columns: id, name (UNIQUE), description, status (CHECK constraint for proposed/testing/confirmed/rejected/invalidated), confidence_score, category_filter, volume_min, volume_max, model_filter, temporal_filter (JSON), proposed_at, first_tested_at, confirmed_at, last_evaluated_at, invalidated_at, decay_half_life_days (default 90), retest_threshold (default 0.50), proposed_by, notes
  - File: `src/polymarket_agent/backtest/database.py`
  - Spec: `hypothesis-data-model`

- [ ] 1.2 Add `bt_hypothesis_evidence` CREATE TABLE to SCHEMA_SQL with columns: id, hypothesis_id (FK to bt_hypotheses), run_id (FK to bt_simulation_runs), recorded_at, trial_count, agent_brier, market_brier, brier_diff, simulated_pnl, p_value, effect_size, supports_hypothesis (1/0/NULL), evaluation_notes
  - File: `src/polymarket_agent/backtest/database.py`
  - Spec: `hypothesis-data-model`

- [ ] 1.3 Add `bt_hypothesis_actions` CREATE TABLE to SCHEMA_SQL with columns: id, hypothesis_id (FK to bt_hypotheses), action_type (CHECK constraint for edge_override/category_target/category_avoid/model_preference/weight_adjustment), config (JSON), base_strength (default 1.0), active (default 0), created_at, activated_at, deactivated_at
  - File: `src/polymarket_agent/backtest/database.py`
  - Spec: `hypothesis-data-model`

- [ ] 1.4 Add indexes to SCHEMA_SQL: `idx_bt_hypotheses_status` on status, `idx_bt_hyp_evidence_hyp` on hypothesis_id, `idx_bt_hyp_evidence_run` on run_id, `idx_bt_hyp_actions_hyp` on hypothesis_id, `idx_bt_hyp_actions_active` on active
  - File: `src/polymarket_agent/backtest/database.py`
  - Spec: `hypothesis-data-model`

- [ ] 1.5 Implement `seed_hypotheses()` in hypothesis.py for the 4 initial hypotheses: probable-no-alpha, mid-volume-sweet-spot, high-volume-efficient, sports-no-alpha. Each with appropriate filter criteria and pre-defined inactive actions. Only seeds if `bt_hypotheses` table is empty
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-data-model` (Decision 7)

- [ ] 1.6 Call `seed_hypotheses()` from `init_backtest_db()` after schema creation and regime seeding. Use lazy import to avoid circular dependencies
  - File: `src/polymarket_agent/backtest/database.py`
  - Spec: `hypothesis-data-model` (Decision 7)

## 2. Hypothesis CRUD & Core Engine

- [ ] 2.1 Create `src/polymarket_agent/backtest/hypothesis.py` module with imports, module-level constants for confirmation/rejection thresholds (CONFIRM_MIN_TRIALS=30, CONFIRM_BRIER_DIFF=-0.02, CONFIRM_P_VALUE=0.05, REJECT_MIN_TRIALS=30, REJECT_BRIER_DIFF=0.02, REJECT_CONSECUTIVE_CONTRARY=2)
  - File: `src/polymarket_agent/backtest/hypothesis.py` (new)
  - Spec: `hypothesis-lifecycle` (Decision 2)

- [ ] 2.2 Implement `propose()` — insert hypothesis row with status='proposed', proposed_at=now, confidence_score=0.0. Validate name uniqueness. If actions list provided, insert inactive `bt_hypothesis_actions` rows. Return hypothesis ID
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-lifecycle` (Decision 2, `propose()`)

- [ ] 2.3 Implement `record_evidence()` — insert into `bt_hypothesis_evidence` with hypothesis_id, run_id, recorded_at, trial_count, agent_brier, market_brier, brier_diff, simulated_pnl, p_value, effect_size, supports_hypothesis, evaluation_notes
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-lifecycle` (Decision 2)

- [ ] 2.4 Implement `evaluate()` — load all evidence rows for a hypothesis, compute recency-weighted metrics via `_compute_weighted_confidence()` and `_compute_weighted_brier_diff()`, apply confirmation/rejection/demotion/inconclusive logic, transition status, activate/deactivate actions as appropriate, update confidence_score and last_evaluated_at. Return evaluation summary dict
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-lifecycle` (Decision 2, `evaluate()`)

- [ ] 2.5 Implement `_compute_weighted_confidence()` — recency-weighted confidence from evidence rows. Weight = 1/(1 + age_days/30). Signal maps brier_diff via sigmoid-like clamped formula. Scale by sample size (n_factor up to 2x at n=100). Return value in [0.0, 1.0]
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-lifecycle` (Decision 3)

- [ ] 2.6 Implement `_compute_weighted_brier_diff()` — recency-weighted average Brier diff and effective trial count. Return (weighted_brier_diff, effective_trial_count) tuple
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-lifecycle` (Decision 3)

## 3. Iterability & Decay

- [ ] 3.1 Implement `test()` — load hypothesis row, validate status is in (proposed, testing, confirmed, invalidated), extract filter criteria (category_filter, volume_min, volume_max, temporal_filter), call `select_markets()` with hypothesis filters, transition proposed->testing with first_tested_at=now, call `run_simulation()` with hypothesis_id. Return run summary dict
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-lifecycle` (Decision 2, `test()`)

- [ ] 3.2 Implement `retest()` — call `test()` then `evaluate()`. New evidence gets higher recency weight than old evidence. Return evaluation result dict
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-lifecycle` (Decision 2, `retest()`)

- [ ] 3.3 Implement `decay_check()` — query all confirmed hypotheses, load latest evidence recorded_at, compute decayed confidence using exponential half-life formula (base_confidence * 0.5^(days_elapsed / half_life_days)), update confidence_score on hypothesis row, update active action effective strength. Flag hypotheses below retest_threshold. Invalidate hypotheses below critical 0.25 threshold (deactivate actions). Return list of flagged hypothesis dicts
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-lifecycle` (Decision 2, `decay_check()`)

- [ ] 3.4 Implement demotion logic within `evaluate()` — if last REJECT_CONSECUTIVE_CONTRARY evidence records all have supports_hypothesis=0, transition confirmed->invalidated, set invalidated_at=now, deactivate all actions (active=0, deactivated_at=now)
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-lifecycle` (Decision 2, `evaluate()` demotion path)

## 4. Action System

- [ ] 4.1 Implement action activation in `evaluate()` — when hypothesis transitions to confirmed, set active=1 and activated_at=now on all `bt_hypothesis_actions` for that hypothesis_id
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-actions` (Decision 4)

- [ ] 4.2 Implement action deactivation — when hypothesis transitions to invalidated or rejected, or when decay_check drops confidence below critical 0.25, set active=0 and deactivated_at=now on all actions for that hypothesis_id
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-actions` (Decision 4)

- [ ] 4.3 Implement `load_active_hypothesis_actions()` — JOIN bt_hypothesis_actions (active=1) with bt_hypotheses (status='confirmed'), compute effective_strength = base_strength * confidence_score, parse config JSON, return list of dicts with hypothesis_id, hypothesis_name, action_type, config, base_strength, effective_strength, hypothesis_confidence
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-actions` (Decision 4, `load_active_hypothesis_actions()`)

- [ ] 4.4 Implement `load_confirmed_hypotheses()` — query bt_hypotheses where status='confirmed', return list of dicts with id, name, description, confidence_score, category_filter, volume_min, volume_max
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-actions` (Decision 5e)

- [ ] 4.5 Implement `get_confirmed_hypotheses_summary()` — generate markdown text summary of confirmed hypotheses for LLM prompts. Return formatted string or None if no confirmed hypotheses
  - File: `src/polymarket_agent/backtest/hypothesis.py`
  - Spec: `hypothesis-actions` (Decision 5d)

## 5. Integration — Strategy & Edge

- [ ] 5.1 Modify `load_strategy_config()` in strategy.py to import and call `load_active_hypothesis_actions()` after loading YAML, then call `_merge_hypothesis_actions(config, actions)`. Wrap in try/except with logger.warning on failure
  - File: `src/polymarket_agent/backtest/strategy.py`
  - Spec: `strategy-config` (Decision 5b)

- [ ] 5.2 Implement `_merge_hypothesis_actions()` helper in strategy.py — merge category_target into market_selection.target_categories, category_avoid into market_selection.avoid_categories, edge_override into edge_thresholds.category_overrides (with strength scaling, minimum 0.1 strength to apply, don't override user-set values), store all actions in hypothesis_actions key. Return modified config
  - File: `src/polymarket_agent/backtest/strategy.py`
  - Spec: `strategy-config` (Decision 5b)

- [ ] 5.3 Modify `build_recommendation()` in edge.py to check strategy_config for hypothesis_actions with action_type='weight_adjustment'. Apply Kelly multiplier scaling: effective_multiplier = 1.0 + (kelly_multiplier - 1.0) * effective_strength. Scale the computed position size accordingly
  - File: `src/polymarket_agent/trading/edge.py`
  - Spec: `edge-computation` (Decision 5c)

## 6. Integration — Simulator, Calibration & Scheduler

- [ ] 6.1 Add `hypothesis_id: int | None = None` parameter to `run_simulation()` in simulator.py. Include hypothesis_id in config JSON written to bt_simulation_runs
  - File: `src/polymarket_agent/backtest/simulator.py`
  - Spec: `simulation-runner` (Decision 5a)

- [ ] 6.2 Implement `_record_hypothesis_evidence()` helper in simulator.py — compute brier_diff, call `_compute_paired_stats()` for p_value and effect_size, determine supports_hypothesis (1 if brier_diff < 0, 0 if > 0, NULL if == 0 or trial_count < 5), call `record_evidence()` from hypothesis module
  - File: `src/polymarket_agent/backtest/simulator.py`
  - Spec: `simulation-runner` (Decision 5a)

- [ ] 6.3 Implement `_compute_paired_stats()` helper in simulator.py — query per-trial Brier scores from bt_simulation_trials, compute paired t-test statistic, compute two-tailed p-value using math.erfc normal approximation, compute Cohen's d effect size. Return (p_value, effect_size) tuple
  - File: `src/polymarket_agent/backtest/simulator.py`
  - Spec: `simulation-runner` (Decision 5a)

- [ ] 6.4 Add auto-evidence recording after simulation completes in `run_simulation()` — if hypothesis_id is not None, call `_record_hypothesis_evidence()` with run results
  - File: `src/polymarket_agent/backtest/simulator.py`
  - Spec: `simulation-runner` (Decision 5a)

- [ ] 6.5 Modify `export_calibration_for_llm()` in calibration.py — after category breakdown section, import and call `get_confirmed_hypotheses_summary()`, append result to lines if not None. Wrap in try/except to gracefully handle uninitialized hypothesis system
  - File: `src/polymarket_agent/trading/calibration.py`
  - Spec: `calibration-tracker` (Decision 5d)

- [ ] 6.6 Modify `_check_strategy_drift()` in scheduler.py — after existing per-category Brier analysis, import and call `load_confirmed_hypotheses()`, cross-reference each hypothesis's category_filter against live calibration data, log warning if live Brier > 0.25 on >= 20 predictions for a hypothesis's target category. Wrap in try/except
  - File: `src/polymarket_agent/cli/scheduler.py`
  - Spec: `calibration-tracker` (Decision 5e)

## 7. CLI Commands

- [ ] 7.1 Add `@backtest.group() hypothesis` Click group to main.py under the existing `backtest` group with docstring "Manage testable hypotheses about agent performance."
  - File: `src/polymarket_agent/cli/main.py`
  - Spec: `hypothesis-cli` (Decision 6)

- [ ] 7.2 Implement `hypothesis list` command — Rich table with columns: ID, Name, Status, Confidence, Evidence Count, Last Evaluated, Category Filter, Volume Range. Support `--status` filter option (proposed/testing/confirmed/rejected/invalidated/all). Color-code by status (green=confirmed, red=rejected, yellow=testing, dim=proposed, strikethrough=invalidated)
  - File: `src/polymarket_agent/cli/main.py`
  - Spec: `hypothesis-cli` (Decision 6, `hypothesis list`)

- [ ] 7.3 Implement `hypothesis propose` command — options: --name (required), --description (required), --category, --volume-min, --volume-max, --regime, --horizon, --half-life (default 90). Call `propose()`, display Rich panel with created hypothesis details and next-step instructions
  - File: `src/polymarket_agent/cli/main.py`
  - Spec: `hypothesis-cli` (Decision 6, `hypothesis propose`)

- [ ] 7.4 Implement `hypothesis test` command — argument: hypothesis_id. Options: --count (default 50), --dry-run. Call `test()`, show hypothesis being tested, delegate to simulation progress, show evidence recorded and evaluation status on completion
  - File: `src/polymarket_agent/cli/main.py`
  - Spec: `hypothesis-cli` (Decision 6, `hypothesis test`)

- [ ] 7.5 Implement `hypothesis evaluate` command — argument: hypothesis_id. Call `evaluate()`, display Rich panel with all evidence records table, weighted metrics, status transition, confidence score, and active actions if confirmed
  - File: `src/polymarket_agent/cli/main.py`
  - Spec: `hypothesis-cli` (Decision 6, `hypothesis evaluate`)

- [ ] 7.6 Implement `hypothesis retest` command — argument: hypothesis_id. Options: --count (default 50). Call `retest()`, show test output then evaluation output
  - File: `src/polymarket_agent/cli/main.py`
  - Spec: `hypothesis-cli` (Decision 6, `hypothesis retest`)

- [ ] 7.7 Implement `hypothesis actions` command — call `load_active_hypothesis_actions()`, display Rich table with columns: Hypothesis, Action Type, Config Summary, Base Strength, Effective Strength, Active Since. Group by hypothesis
  - File: `src/polymarket_agent/cli/main.py`
  - Spec: `hypothesis-cli` (Decision 6, `hypothesis actions`)

- [ ] 7.8 Implement `hypothesis decay-check` command — call `decay_check()`, display Rich table with columns: Name, Original Confidence, Current (Decayed) Confidence, Days Since Evidence, Retest Threshold, Recommendation (OK/RETEST/INVALIDATE)
  - File: `src/polymarket_agent/cli/main.py`
  - Spec: `hypothesis-cli` (Decision 6, `hypothesis decay-check`)

## 8. Tests

- [ ] 8.1 Test hypothesis CRUD: propose creates row with status='proposed' and correct fields, propose with actions creates inactive action rows, propose with duplicate name raises error, query hypothesis by ID returns correct data
  - File: `tests/test_backtest.py`
  - Spec: `hypothesis-lifecycle`

- [ ] 8.2 Test hypothesis status transitions: proposed->testing on first test(), testing->confirmed when thresholds met, testing->rejected when rejection thresholds met, confirmed->invalidated on consecutive contrary evidence, rejected cannot be re-tested without reset
  - File: `tests/test_backtest.py`
  - Spec: `hypothesis-lifecycle`

- [ ] 8.3 Test confidence decay formula: confirmed hypothesis at 0.80 with 90-day half-life decays to ~0.40 after 90 days, ~0.20 after 180 days. Verify exponential decay math
  - File: `tests/test_backtest.py`
  - Spec: `hypothesis-lifecycle` (Decision 3)

- [ ] 8.4 Test evidence recording: record_evidence inserts correct row, supports_hypothesis set correctly (1 for negative brier_diff, 0 for positive, NULL for zero or small sample)
  - File: `tests/test_backtest.py`
  - Spec: `hypothesis-lifecycle`

- [ ] 8.5 Test `_compute_weighted_confidence()`: evidence from today has weight 1.0, evidence from 30 days ago has weight 0.5, negative brier_diff maps to high signal, positive brier_diff maps to low signal, empty evidence returns 0.0
  - File: `tests/test_backtest.py`
  - Spec: `hypothesis-lifecycle` (Decision 3)

- [ ] 8.6 Test `_compute_weighted_brier_diff()`: single evidence returns its brier_diff, multiple evidence records weighted by recency, None brier_diff records are skipped
  - File: `tests/test_backtest.py`
  - Spec: `hypothesis-lifecycle` (Decision 3)

- [ ] 8.7 Test action creation/deactivation lifecycle: actions created inactive, activated on hypothesis confirmation, deactivated on hypothesis invalidation, deactivated when decay drops below 0.25
  - File: `tests/test_backtest.py`
  - Spec: `hypothesis-actions`

- [ ] 8.8 Test `load_active_hypothesis_actions()`: returns only actions with active=1 and parent status='confirmed', effective_strength = base_strength * confidence_score, config JSON is parsed correctly, returns empty list when no active actions
  - File: `tests/test_backtest.py`
  - Spec: `hypothesis-actions`

- [ ] 8.9 Test `_merge_hypothesis_actions()` in strategy.py: category_target appends to target_categories, category_avoid appends to avoid_categories, edge_override adds to category_overrides with strength scaling, user-set overrides are not replaced, all actions stored in hypothesis_actions key
  - File: `tests/test_backtest.py`
  - Spec: `strategy-config`

- [ ] 8.10 Test `build_recommendation()` with hypothesis weight_adjustment actions in strategy_config: Kelly multiplier applied correctly at full strength, multiplier neutral at zero strength
  - File: `tests/test_backtest.py`
  - Spec: `edge-computation`

- [ ] 8.11 Test `export_calibration_for_llm()` with confirmed hypotheses: output contains "Validated Findings from Backtesting" section when hypotheses exist, omits section when no confirmed hypotheses
  - File: `tests/test_backtest.py`
  - Spec: `calibration-tracker`

- [ ] 8.12 Test `seed_hypotheses()`: creates 4 hypotheses with correct names and filters on empty table, is idempotent (no-op if hypotheses already exist), creates associated inactive actions
  - File: `tests/test_backtest.py`
  - Spec: `hypothesis-data-model`

- [ ] 8.13 CLI smoke tests: `hypothesis list` runs without error, `hypothesis propose` creates a hypothesis, `hypothesis actions` shows active actions table (may be empty)
  - File: `tests/test_backtest.py`
  - Spec: `hypothesis-cli`
