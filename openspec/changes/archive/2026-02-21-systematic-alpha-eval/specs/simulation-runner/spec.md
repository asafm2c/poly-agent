## Purpose

Delta spec for the existing simulation-runner capability. Extends `run_simulation()` with model override support and per-trial model tagging, adds `select_markets_stratified()` for stratified sampling, and adds `run_multi_model_evaluation()` for multi-model orchestration. All changes are backward-compatible: existing calls with no new parameters behave identically.

## MODIFIED Requirements

### Requirement: Model override parameter on run_simulation()
`run_simulation()` in `simulator.py` MUST accept a new optional parameter `model: str | None = None`. When `model` is provided, it MUST be forwarded to `ProbabilityEstimator.estimate(model=model)`, which in turn forwards it to each `llm.complete_json(model=model)` call. When `model` is None, behavior MUST be unchanged (uses `settings.analysis_model`).

#### Scenario: Explicit model override
- **GIVEN** `run_simulation()` is called with `model="claude-haiku-4-5-20251001"`
- **WHEN** the estimator runs for each market
- **THEN** all LLM calls use `claude-haiku-4-5-20251001` instead of `settings.analysis_model`

#### Scenario: No model override (backward compatibility)
- **GIVEN** `run_simulation()` is called without the `model` parameter
- **WHEN** the estimator runs for each market
- **THEN** LLM calls use `settings.analysis_model` exactly as before this change

### Requirement: Model stored per trial
When `model` is provided to `run_simulation()`, the model identifier MUST be stored in the `model` column of each `bt_simulation_trials` row. When `model` is None, the `model` column MUST be set to `settings.analysis_model` (not NULL), so all new trials have an explicit model identifier.

#### Scenario: Model column populated
- **GIVEN** `run_simulation()` is called with `model="claude-sonnet-4-6"`
- **WHEN** trials are persisted
- **THEN** each trial row has `model = "claude-sonnet-4-6"`

#### Scenario: Default model recorded
- **GIVEN** `run_simulation()` is called without `model`
- **WHEN** trials are persisted
- **THEN** each trial row has `model` set to the value of `settings.analysis_model`

### Requirement: Model stored in run config
The `model` parameter MUST be included in the `config` JSON stored in `bt_simulation_runs`. If multiple models are run via `run_multi_model_evaluation()`, each individual `run_simulation()` call records its own model.

#### Scenario: Config includes model
- **GIVEN** `run_simulation()` is called with `model="claude-opus-4-6"`
- **WHEN** the run record is created
- **THEN** the `config` JSON includes `"model": "claude-opus-4-6"`

### Requirement: Pre-selected market set support
`run_simulation()` MUST accept an optional `market_ids: list[str] | None = None` parameter. When provided, the function MUST run trials only for those market IDs (loaded from the database), skipping the `select_markets()` step. This enables paired comparisons where multiple models evaluate identical markets.

#### Scenario: Market IDs provided
- **GIVEN** `run_simulation()` is called with `market_ids=["id1", "id2", "id3"]`
- **WHEN** the simulation runs
- **THEN** exactly those 3 markets are evaluated, in the order provided

#### Scenario: Market IDs not provided (backward compatibility)
- **GIVEN** `run_simulation()` is called without `market_ids`
- **WHEN** the simulation runs
- **THEN** markets are selected via `select_markets()` as before

### Requirement: Training recency score computation
When `model` is provided (or defaulted), `run_simulation()` MUST compute `training_recency_score(market["end_date"], model)` for each trial and store it in the `training_recency_score` column. This MUST happen after the trial's Brier scores are computed and before the trial row is persisted.

#### Scenario: Recency score stored
- **GIVEN** a market with `end_date="2025-09-01"` and model `claude-sonnet-4-6`
- **WHEN** the trial completes
- **THEN** `training_recency_score` is approximately 0.85 (153 days / 180) in the persisted trial row

### Requirement: ProbabilityEstimator.estimate() model forwarding
`ProbabilityEstimator.estimate()` in `estimator.py` MUST accept a new optional parameter `model: str | None = None`. When provided, it MUST be forwarded to each `llm.complete_json(model=model)` call in the estimation pipeline. When None, `complete_json()` falls back to `settings.analysis_model`.

#### Scenario: Model forwarded through estimation pipeline
- **GIVEN** `estimate(market, model="claude-haiku-4-5-20251001")` is called
- **WHEN** the 4-pass pipeline runs (base rate, Bayesian update, adversarial, calibration)
- **THEN** all 4 LLM calls use `claude-haiku-4-5-20251001`

## ADDED Requirements

### Requirement: New constants for evaluation
`simulator.py` MUST define `VOLUME_TIERS`, `EVALUATION_MODELS`, and `MODEL_COST_PER_TRIAL` as module-level constants as specified in the stratified-market-selection and progressive-multi-model-evaluation specs.

### Requirement: Backward compatibility guarantee
All existing calls to `run_simulation()` and `ProbabilityEstimator.estimate()` that do not provide the new parameters MUST produce identical behavior and results to the pre-change versions. No existing function signatures are broken.

#### Scenario: Existing simulation CLI works unchanged
- **GIVEN** the existing `backtest simulate` CLI command
- **WHEN** invoked with its current flags (no `--model` flag)
- **THEN** it runs identically to before, using `settings.analysis_model`

## Scenarios

### Scenario: Full multi-model flow
- **GIVEN** `select_markets_stratified()` returns 200 markets
- **WHEN** `run_multi_model_evaluation(markets, models=["haiku", "sonnet"])` is called
- **THEN** `run_simulation()` is called twice with the same 200 markets: once with `model="claude-haiku-4-5-20251001"` and once with `model="claude-sonnet-4-6"`, producing two run IDs with paired trials

### Scenario: Estimation failure does not crash run
- **GIVEN** `run_simulation()` is processing 100 markets with `model="claude-opus-4-6"`
- **WHEN** the estimator raises an exception on market 47
- **THEN** the trial is recorded with `agent_estimate = NULL`, `model = "claude-opus-4-6"`, the error is logged, and the simulation continues to market 48
