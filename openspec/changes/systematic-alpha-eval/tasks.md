## 1. Database & Constants

- [x] 1.1 Add `model TEXT` and `training_recency_score REAL` columns to `bt_simulation_trials` in `SCHEMA_SQL` (for fresh databases) and implement `_migrate_simulation_trials()` migration function that uses `PRAGMA table_info` to add columns if not present. Add `CREATE INDEX IF NOT EXISTS idx_bt_sim_trials_model ON bt_simulation_trials(model)` index. Call migration from `init_backtest_db()` before `executescript(SCHEMA_SQL)`.
  - Files: `src/polymarket_agent/backtest/database.py`
  - Specs: `simulation-runner` (model stored per trial), design decision 6

- [x] 1.2 Add `MODEL_TRAINING_CUTOFFS` dict to `analysis.py` mapping model IDs to training cutoff date strings (`"claude-haiku-4-5-20251001": "2025-04-01"`, `"claude-sonnet-4-6": "2025-04-01"`, `"claude-opus-4-6": "2025-04-01"`).
  - Files: `src/polymarket_agent/backtest/analysis.py`
  - Specs: `temporal-confidence-weighting`, design decision 4

- [x] 1.3 Add `VOLUME_TIERS` dict, `EVALUATION_MODELS` list, and `MODEL_COST_PER_TRIAL` dict as constants to `simulator.py`.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `stratified-market-selection`, `progressive-multi-model-evaluation`, design decisions 2 and 3

- [x] 1.4 Add Opus entry to `MODEL_COSTS` dict in `llm_client.py`: `"claude-opus-4-6": {"input": 15.00, "output": 75.00}`.
  - Files: `src/polymarket_agent/analyst/llm_client.py`
  - Specs: design decision 6

## 2. Stratified Market Selection

- [x] 2.1 Implement `select_markets_stratified()` function in `simulator.py`.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `stratified-market-selection`, design decision 2

- [x] 2.2 Implement category auto-discovery SQL query inside `select_markets_stratified()`.
  - Files: `src/polymarket_agent/backtest/simulator.py`

- [x] 2.3 Implement per-cell SQL sampling inside `select_markets_stratified()`.
  - Files: `src/polymarket_agent/backtest/simulator.py`

- [x] 2.4 Implement min-per-cell enforcement and shortfall reporting.
  - Files: `src/polymarket_agent/backtest/simulator.py`

## 3. Model Override & Training Recency

- [x] 3.1 Add `model: str | None = None` parameter to `run_simulation()`. Store `effective_model` (model or settings.analysis_model) in config and trial rows.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `simulation-runner`, design decision 1

- [x] 3.2 Add `model: str | None = None` parameter to `ProbabilityEstimator.estimate()`. Forward to each `llm.complete_json(model=model)` call in all 4 passes.
  - Files: `src/polymarket_agent/analyst/estimator.py`
  - Specs: `simulation-runner`, design decision 1

- [x] 3.3 Implement `training_recency_score()` function in `analysis.py`.
  - Files: `src/polymarket_agent/backtest/analysis.py`
  - Specs: `temporal-confidence-weighting`, design decision 4

- [x] 3.4 Compute and store `training_recency_score` per trial in `run_simulation()`. Always computed using effective_model.
  - Files: `src/polymarket_agent/backtest/simulator.py`

## 4. Statistical Comparison

- [x] 4.1 Implement `brier_confidence_interval()` in `analysis.py` with bootstrap (10K resamples, no scipy).
  - Files: `src/polymarket_agent/backtest/analysis.py`
  - Specs: `statistical-comparison`, design decision 5

- [x] 4.2 Implement `weighted_brier()` in `analysis.py`.
  - Files: `src/polymarket_agent/backtest/analysis.py`

- [x] 4.3 Implement `cross_model_comparison()` in `analysis.py` with by_cell breakdown.
  - Files: `src/polymarket_agent/backtest/analysis.py`
  - Specs: `statistical-comparison`, design decision 5

## 5. Progressive Multi-Model Orchestration

- [x] 5.1 Implement `run_multi_model_evaluation()` in `simulator.py`.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `progressive-multi-model-evaluation`, design decision 3

- [x] 5.2 Implement progressive mode with `progress_callback`.
  - Files: `src/polymarket_agent/backtest/simulator.py`

- [x] 5.3 Implement budget tracking with pre-stage estimation.
  - Files: `src/polymarket_agent/backtest/simulator.py`

## 6. CLI

- [x] 6.1 Add `MODEL_ALIASES` dict and `_resolve_model()` helper.
  - Files: `src/polymarket_agent/cli/main.py`

- [x] 6.2 Implement `backtest evaluate` Click command with all options.
  - Files: `src/polymarket_agent/cli/main.py`

- [x] 6.3 Implement evaluation plan display with cell counts and cost estimate tables.
  - Files: `src/polymarket_agent/cli/main.py`

- [x] 6.4 Implement dry-run mode.
  - Files: `src/polymarket_agent/cli/main.py`

- [x] 6.5 Implement progressive execution flow with intermediate results and confirmation prompts.
  - Files: `src/polymarket_agent/cli/main.py`

- [x] 6.6 Implement final Rich table report (Model Comparison, Pairwise Comparison).
  - Files: `src/polymarket_agent/cli/main.py`

## 7. Tests

- [ ] 7.1 Unit test `select_markets_stratified()`
  - Files: `tests/test_backtest.py`

- [ ] 7.2 Unit test `training_recency_score()`
  - Files: `tests/test_backtest.py`

- [ ] 7.3 Unit test `brier_confidence_interval()`
  - Files: `tests/test_backtest.py`

- [ ] 7.4 Unit test `weighted_brier()`
  - Files: `tests/test_backtest.py`

- [ ] 7.5 Unit test `cross_model_comparison()`
  - Files: `tests/test_backtest.py`

- [ ] 7.6 Integration test `run_multi_model_evaluation()` with mocked LLM
  - Files: `tests/test_backtest.py`

- [ ] 7.7 CLI smoke test for `backtest evaluate --dry-run`
  - Files: `tests/test_backtest.py`

- [ ] 7.8 Test `run_simulation()` with `model` parameter
  - Files: `tests/test_backtest.py`
