## Purpose

Delta spec for the existing analysis-library capability. Adds cross-model comparison functions, training-recency-weighted aggregation, bootstrap confidence intervals, and per-cell breakdowns. All new functions are additive -- existing functions (`simulation_summary()`, `simulation_by_category()`, `simulation_by_volume_tier()`, `load_markets()`, etc.) remain unchanged.

## ADDED Requirements

### Requirement: Training recency score computation
The analysis library MUST provide a `training_recency_score(resolution_date, model)` function as specified in the temporal-confidence-weighting spec. This function MUST be defined in `analysis.py` alongside the `MODEL_TRAINING_CUTOFFS` constant.

#### Scenario: Function importable from analysis module
- **WHEN** `from polymarket_agent.backtest.analysis import training_recency_score` is executed
- **THEN** the import succeeds and the function is callable

### Requirement: Weighted Brier aggregation
The analysis library MUST provide a `weighted_brier(trials, weight_key)` function as specified in the temporal-confidence-weighting spec. It MUST handle NULL weights, zero total weight, and mixed-weight scenarios.

#### Scenario: Weighted Brier with full-weight trials
- **GIVEN** 20 trials all with `training_recency_score = 1.0`
- **WHEN** `weighted_brier(trials)` is called
- **THEN** `agent_brier_weighted` equals the unweighted mean agent Brier score

### Requirement: Bootstrap confidence interval
The analysis library MUST provide a `brier_confidence_interval(agent_briers, market_briers, ...)` function as specified in the statistical-comparison spec. It MUST use only Python standard library for bootstrap resampling.

#### Scenario: CI computed for typical run
- **GIVEN** 50 paired Brier scores
- **WHEN** `brier_confidence_interval(agent_briers, market_briers, seed=42)` is called
- **THEN** the function returns `mean_diff`, `ci_low`, `ci_high`, `p_value`, `n=50`, and `significant` (bool)

### Requirement: Cross-model comparison
The analysis library MUST provide a `cross_model_comparison(run_ids, db_path)` function as specified in the statistical-comparison spec. It MUST load trials from the database, match by `market_id`, and produce per-model summaries, pairwise CIs, and per-cell breakdowns.

#### Scenario: Two-model comparison
- **GIVEN** run IDs 4 (Haiku) and 5 (Sonnet) with 80 paired trials
- **WHEN** `cross_model_comparison(run_ids=[4, 5])` is called
- **THEN** `"models"` has 2 entries, `"pairwise"` has 1 entry (Haiku vs Sonnet), and `"by_cell"` has entries for each (category, tier) with at least one trial

### Requirement: Per-cell breakdown with sufficiency flag
The `"by_cell"` output of `cross_model_comparison()` MUST include `"n"` (trial count) and `"sufficient"` (bool, True if n >= 20) for each cell. Cells with `"sufficient": False` MUST be clearly distinguishable in the output.

#### Scenario: Mixed sufficiency across cells
- **GIVEN** cell (null, "1M-10M") has 25 trials and cell (crypto, ">10M") has 8 trials
- **WHEN** `cross_model_comparison()` returns
- **THEN** `by_cell[(None, "1M-10M")]["sufficient"]` is `True` and `by_cell[("crypto", ">10M")]["sufficient"]` is `False`

### Requirement: Recency-weighted aggregation in cross-model comparison
`cross_model_comparison()` MUST compute both unweighted and recency-weighted Brier scores for each model by calling `weighted_brier()` on each model's trials. Both values MUST appear in the per-model summary.

#### Scenario: Weighted and unweighted differ
- **GIVEN** a model's trials include some with low recency scores (near training cutoff)
- **WHEN** `cross_model_comparison()` computes the model summary
- **THEN** `agent_brier_weighted` differs from `agent_brier` because low-recency trials are down-weighted

## MODIFIED Requirements

(None. Existing functions are unchanged. All changes are additive.)

## Backward Compatibility

### Requirement: Existing functions unmodified
`simulation_summary()`, `simulation_by_category()`, `simulation_by_volume_tier()`, `load_markets()`, `efficiency_index()`, `category_calibration()`, `price_momentum()`, `cross_market_arbitrage()`, `market_baseline_brier()`, and `regime_comparison()` MUST continue to work with their existing signatures and return the same structures. No existing function is modified.

#### Scenario: Existing simulation_summary still works
- **GIVEN** a completed simulation run from before this change
- **WHEN** `simulation_summary(run_id=3)` is called
- **THEN** the function returns the same result as before, with no errors from NULL `model` or `training_recency_score` columns

### Requirement: Analysis functions callable from any context
All new analysis functions (`training_recency_score`, `weighted_brier`, `brier_confidence_interval`, `cross_model_comparison`) MUST work when called from Python scripts, CLI commands, or Jupyter notebooks. They MUST accept standard Python arguments and return structured dictionaries, not print to stdout.

#### Scenario: New functions used in notebook
- **WHEN** `from polymarket_agent.backtest.analysis import brier_confidence_interval, cross_model_comparison` is executed in a Jupyter notebook
- **THEN** both functions are importable and return dict results suitable for further analysis
