## 1. Database & Constants

- [ ] 1.1 Add `model TEXT` and `training_recency_score REAL` columns to `bt_simulation_trials` in `SCHEMA_SQL` (for fresh databases) and implement `_migrate_simulation_trials()` migration function that uses `PRAGMA table_info` to add columns if not present. Add `CREATE INDEX IF NOT EXISTS idx_bt_sim_trials_model ON bt_simulation_trials(model)` index. Call migration from `init_backtest_db()` after `executescript(SCHEMA_SQL)`.
  - Files: `src/polymarket_agent/backtest/database.py`
  - Specs: `simulation-runner` (model stored per trial), design decision 6

- [ ] 1.2 Add `MODEL_TRAINING_CUTOFFS` dict to `analysis.py` mapping model IDs to training cutoff date strings (`"claude-haiku-4-5-20251001": "2025-04-01"`, `"claude-sonnet-4-6": "2025-04-01"`, `"claude-opus-4-6": "2025-04-01"`).
  - Files: `src/polymarket_agent/backtest/analysis.py`
  - Specs: `temporal-confidence-weighting`, design decision 4

- [ ] 1.3 Add `VOLUME_TIERS` dict, `EVALUATION_MODELS` list, and `MODEL_COST_PER_TRIAL` dict as constants to `simulator.py`. `VOLUME_TIERS = {">10M": (10_000_000, None), "1M-10M": (1_000_000, 10_000_000), "100K-1M": (100_000, 1_000_000), "10K-100K": (10_000, 100_000)}`. `EVALUATION_MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-6"]`. `MODEL_COST_PER_TRIAL` per design decision 3.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `stratified-market-selection`, `progressive-multi-model-evaluation`, design decisions 2 and 3

- [ ] 1.4 Add Opus entry to `MODEL_COSTS` dict in `llm_client.py`: `"claude-opus-4-6": {"input": 15.00, "output": 75.00}`.
  - Files: `src/polymarket_agent/analyst/llm_client.py`
  - Specs: design decision 6

## 2. Stratified Market Selection

- [ ] 2.1 Implement `select_markets_stratified()` function in `simulator.py`. Signature: `(n_per_cell=20, categories=None, volume_tiers=None, horizon=DEFAULT_HORIZON, db_path=None) -> tuple[list[dict], dict]`. Returns `(markets, cell_counts)` where `cell_counts` is `{(category, tier): {"requested": n, "available": m, "selected": k}}`. When `categories=None`, auto-discover from database. Uses `VOLUME_TIERS` constant for tier boundaries.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `stratified-market-selection`, design decision 2

- [ ] 2.2 Implement category auto-discovery SQL query inside `select_markets_stratified()`: query distinct categories from `bt_markets` where `has_history=1`, `resolution_outcome IN ('YES','NO')`, and price data exists at horizon. Include NULL as a valid category. Order by category with NULLS FIRST.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `stratified-market-selection`, design decision 2

- [ ] 2.3 Implement per-cell SQL sampling inside `select_markets_stratified()`: for each (category, volume_tier) cell, query eligible markets with volume range and category filter (handling NULL category correctly with `IS NULL`), ordered by `RANDOM()`, limited to `n_per_cell`. Load price history for each selected market.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `stratified-market-selection`, design decision 2

- [ ] 2.4 Implement min-per-cell enforcement and shortfall reporting: if a cell has fewer than `n_per_cell` eligible markets, select all available and record the shortfall in `cell_counts`. Log warnings for cells with fewer than 20 markets. No redistribution from sparse to dense cells.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `stratified-market-selection`, design decision 2

## 3. Model Override & Training Recency

- [ ] 3.1 Add `model: str | None = None` parameter to `run_simulation()`. When provided, pass it through to `ProbabilityEstimator.estimate(model=model)`. Store the model string in the run `config` JSON and in each trial row's new `model` column. When `model` is None, behavior is unchanged (uses `settings.analysis_model`).
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `simulation-runner`, design decision 1

- [ ] 3.2 Add `model: str | None = None` parameter to `ProbabilityEstimator.estimate()`. Forward the model parameter to each `llm.complete_json(model=model)` call within the four-pass pipeline. When None, `complete_json()` falls back to `settings.analysis_model` (existing behavior).
  - Files: `src/polymarket_agent/analyst/estimator.py`
  - Specs: `simulation-runner`, design decision 1

- [ ] 3.3 Implement `training_recency_score()` function in `analysis.py`. Signature: `(resolution_date: str, model: str) -> float`. Uses `MODEL_TRAINING_CUTOFFS` dict. Returns 0.0 if resolved during/before training window, 1.0 if 180+ days after cutoff, linear interpolation between. Handle missing model gracefully (return 1.0 for unknown models).
  - Files: `src/polymarket_agent/backtest/analysis.py`
  - Specs: `temporal-confidence-weighting`, design decision 4

- [ ] 3.4 Compute and store `training_recency_score` per trial in `run_simulation()`. After computing Brier scores, call `training_recency_score(market_dict["end_date"], model)` and include the result in the trial INSERT. Handle case where model is None (store NULL for recency score).
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `temporal-confidence-weighting`, design decision 4

## 4. Statistical Comparison

- [ ] 4.1 Implement `brier_confidence_interval()` in `analysis.py`. Signature: `(agent_briers, market_briers, weights=None, n_bootstrap=10_000, confidence=0.95, seed=None) -> dict`. Computes paired differences, bootstraps weighted mean using `random.choices()` (no scipy). Returns `{"mean_diff": float, "ci_low": float, "ci_high": float, "p_value": float, "n": int, "significant": bool}`. Two-sided p-value: proportion of bootstrap means on wrong side of zero.
  - Files: `src/polymarket_agent/backtest/analysis.py`
  - Specs: `statistical-comparison`, design decision 5

- [ ] 4.2 Implement `weighted_brier()` in `analysis.py`. Signature: `(trials: list[dict], weight_key="training_recency_score") -> dict`. Computes weighted mean Brier score using per-trial weights. Returns `{"agent_brier_weighted": float, "market_brier_weighted": float, "brier_diff_weighted": float, "total_weight": float, "trial_count": int}`. Handle NULL weights gracefully (treat as 1.0).
  - Files: `src/polymarket_agent/backtest/analysis.py`
  - Specs: `temporal-confidence-weighting`, design decision 4

- [ ] 4.3 Implement `cross_model_comparison()` in `analysis.py`. Signature: `(run_ids: list[int], db_path=None) -> dict`. Loads trials from each run, pairs by `market_id`, computes per-model aggregate Brier (unweighted and recency-weighted via `weighted_brier()`), pairwise Brier difference CIs via `brier_confidence_interval()`, and per-cell (category x volume tier) breakdowns. Returns `{"models": {...}, "pairwise": {...}, "by_category": {...}, "by_volume_tier": {...}, "by_cell": {...}}`. Flag cells with n < 20 as `"sufficient": False`.
  - Files: `src/polymarket_agent/backtest/analysis.py`
  - Specs: `statistical-comparison`, design decision 5

## 5. Progressive Multi-Model Orchestration

- [ ] 5.1 Implement `run_multi_model_evaluation()` in `simulator.py`. Signature: `(markets, models=None, horizon, edge_threshold, bankroll, fee_rate, budget=None, progressive=True, progress_callback=None, db_path=None) -> dict`. Default models from `EVALUATION_MODELS`. Calls `run_simulation()` for each model on the same market set. Returns `{"runs": {model: run_result}, "comparison": cross_model_comparison_dict}`.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `progressive-multi-model-evaluation`, design decision 3

- [ ] 5.2 Implement progressive mode in `run_multi_model_evaluation()`: after each model completes, call `progress_callback(model_name, run_result, comparison_so_far)`. If callback returns False, stop and skip remaining models. When `progressive=False`, run all models without callbacks.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `progressive-multi-model-evaluation`, design decision 3

- [ ] 5.3 Implement budget tracking in `run_multi_model_evaluation()`: before starting each model, estimate cost as `len(markets) * MODEL_COST_PER_TRIAL[model]`. If `spent + estimated > budget`, skip the model and log a warning. After each model completes, update spent from actual cost in `run_simulation()` return value. When `budget=None`, no limit.
  - Files: `src/polymarket_agent/backtest/simulator.py`
  - Specs: `progressive-multi-model-evaluation`, design decision 3

## 6. CLI

- [ ] 6.1 Add `MODEL_ALIASES` dict to `cli/main.py`: `{"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-6"}`. Implement model name resolution helper that accepts short names and resolves to full model IDs.
  - Files: `src/polymarket_agent/cli/main.py`
  - Specs: `backtest-cli`, design decision 7

- [ ] 6.2 Implement `backtest evaluate` Click command with options: `--models/-m` (multiple, default haiku+sonnet), `--trials-per-cell` (default 20), `--categories` (multiple, default auto-discover), `--horizon` (default 7), `--budget` (optional float), `--all-at-once` (flag), `--dry-run` (flag).
  - Files: `src/polymarket_agent/cli/main.py`
  - Specs: `backtest-cli`, design decision 7

- [ ] 6.3 Implement evaluation plan display: show discovered categories, volume tiers, trials per cell, total cells, market selection cell counts (with `[!]` for shortfall cells), total markets, and cost estimate table (cost/trial, trials, estimated total per model, grand total). Show budget comparison if `--budget` provided. Prompt for confirmation in progressive mode.
  - Files: `src/polymarket_agent/cli/main.py`
  - Specs: `backtest-cli`, design decision 7

- [ ] 6.4 Implement dry-run mode for `backtest evaluate`: run `select_markets_stratified()`, print cell counts and cost estimate, then exit without calling any LLM.
  - Files: `src/polymarket_agent/cli/main.py`
  - Specs: `backtest-cli`, design decision 7

- [ ] 6.5 Implement progressive execution flow: run models in order, show intermediate results after each model (Brier scores, weighted Brier, cost, remaining budget), show pairwise comparison with prior models, prompt "Continue to [next model] (~$X.XX)? [Y/n]". When `--all-at-once`, skip prompts.
  - Files: `src/polymarket_agent/cli/main.py`
  - Specs: `backtest-cli`, design decision 7

- [ ] 6.6 Implement final Rich table report: Model Comparison table (Model, Brier, Wtd Brier, vs Mkt, 95% CI, Sig?), Pairwise Model Comparison table (Comparison, Diff, 95% CI, Sig?), By Category x Model table (cells with n < 20 marked with `*`). Use `cross_model_comparison()` output to populate tables.
  - Files: `src/polymarket_agent/cli/main.py`
  - Specs: `backtest-cli`, design decision 7

## 7. Tests

- [ ] 7.1 Unit test `select_markets_stratified()`: verify stratified sampling across category x volume tier cells, correct cell_counts dict structure, min-per-cell enforcement (shortfall when fewer markets available than requested), auto-discovery of categories from test data.
  - Files: `tests/test_backtest.py`
  - Specs: `stratified-market-selection`

- [ ] 7.2 Unit test `training_recency_score()`: verify 0.0 for dates during training window, 1.0 for dates 180+ days after cutoff, linear interpolation for dates between, 1.0 for unknown models.
  - Files: `tests/test_backtest.py`
  - Specs: `temporal-confidence-weighting`

- [ ] 7.3 Unit test `brier_confidence_interval()`: verify correct mean_diff computation, CI contains true mean with seeded RNG, p_value and significant flag, edge case with identical scores (diff=0), weights parameter affects result.
  - Files: `tests/test_backtest.py`
  - Specs: `statistical-comparison`

- [ ] 7.4 Unit test `weighted_brier()`: verify weighted mean computation, handling of NULL weights (treated as 1.0), correct return dict structure.
  - Files: `tests/test_backtest.py`
  - Specs: `temporal-confidence-weighting`

- [ ] 7.5 Unit test `cross_model_comparison()`: verify pairing logic by market_id across runs, per-model aggregates, pairwise CI computation, per-cell breakdowns with sufficient/insufficient flags, handling of unpaired trials (excluded from pairwise, included in per-model).
  - Files: `tests/test_backtest.py`
  - Specs: `statistical-comparison`

- [ ] 7.6 Integration test `run_multi_model_evaluation()` with mocked LLM: verify all models run against the same market set, progressive callback is invoked after each model, budget gate skips over-budget models, results contain all run_ids and comparison dict.
  - Files: `tests/test_backtest.py`
  - Specs: `progressive-multi-model-evaluation`

- [ ] 7.7 CLI smoke test for `backtest evaluate --dry-run`: invoke via Click test runner, verify market selection and cost estimate are printed, no LLM calls made, exit code 0.
  - Files: `tests/test_backtest.py`
  - Specs: `backtest-cli`

- [ ] 7.8 Test `run_simulation()` with `model` parameter: verify model is stored in trial rows and in run config JSON, verify model is passed through to estimator.
  - Files: `tests/test_backtest.py`
  - Specs: `simulation-runner`
