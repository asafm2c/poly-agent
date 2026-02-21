## Purpose

Orchestrates running the same frozen market set through multiple LLM models in cost order (Haiku, Sonnet, Opus), with intermediate result reporting and gate checks between stages. Enables the operator to stop early if a cheaper model already answers the question, or proceed to more expensive models for confirmation. Supports both progressive (interactive) and batch (all-at-once) execution modes. Budget enforcement prevents accidental cost overruns.

## Requirements

### 1. Default model ordering by cost
`run_multi_model_evaluation()` in `simulator.py` MUST use `EVALUATION_MODELS` as the default model list, ordered by ascending cost per trial: `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-opus-4-6`.

### 2. Same market set across all models
`run_multi_model_evaluation()` MUST pass the identical `markets` list to each `run_simulation()` call so that trials are paired by `market_id` across models for valid statistical comparison.

### 3. Per-model cost estimates
`MODEL_COST_PER_TRIAL` dict in `simulator.py` MUST provide cost estimates for each model: Haiku at $0.005, Sonnet at $0.023, Opus at $0.12. These estimates MUST be used for budget planning before each stage begins.

### 4. Budget enforcement before each stage
When a `budget` parameter is provided, `run_multi_model_evaluation()` MUST estimate the cost of the next model as `len(markets) * MODEL_COST_PER_TRIAL[model]` before starting it. If `spent + estimated > budget`, the model MUST be skipped and a warning logged. Remaining budget MUST be recalculated after each model completes using the actual cost from the `run_simulation()` return value, not the estimate.

### 5. Progressive mode with callback
When `progressive=True` (the default), `run_multi_model_evaluation()` MUST invoke `progress_callback(model_name, run_result, comparison_so_far)` after each model completes. If the callback returns `False`, execution MUST stop and no further models are run. If the callback returns `True`, execution MUST continue to the next model.

### 6. Batch mode
When `progressive=False`, `run_multi_model_evaluation()` MUST run all models in sequence without invoking the callback between stages. Budget enforcement still applies.

### 7. Return structure
`run_multi_model_evaluation()` MUST return a dict with keys `"runs"` (mapping model name to its `run_simulation()` result dict) and `"comparison"` (the output of `cross_model_comparison()` across all completed runs).

### 8. Intermediate comparison
After each model completes (except the first), the function SHOULD compute a partial `cross_model_comparison()` using all run IDs completed so far and pass it to the callback.

### 9. Model override forwarding
Each call to `run_simulation()` within the orchestrator MUST pass the current model via the `model` parameter so trials are tagged with the correct model identifier.

### 10. Graceful handling of all models skipped
If budget enforcement causes all models to be skipped, `run_multi_model_evaluation()` MUST return `{"runs": {}, "comparison": {}}` and log a warning that the budget was insufficient for any model.

### 11. Custom model lists
When the `models` parameter is provided, `run_multi_model_evaluation()` MUST use that list in the given order instead of `EVALUATION_MODELS`. The function MUST NOT reorder user-provided model lists.

## Scenarios

### Scenario: Progressive execution with early stop
- **GIVEN** a market set of 100 markets and `progressive=True` with a callback
- **WHEN** Haiku completes and the callback returns `False`
- **THEN** only one run is recorded in `"runs"`, Sonnet and Opus are never invoked, and `"comparison"` contains only Haiku's results

### Scenario: Budget prevents Opus from running
- **GIVEN** `budget=10.0`, a market set of 200 markets, and default models
- **WHEN** Haiku completes (actual cost $0.95) and Sonnet completes (actual cost $4.40)
- **THEN** before starting Opus, the function estimates 200 * $0.12 = $24.00, finds $0.95 + $4.40 + $24.00 > $10.00, skips Opus with a warning, and returns results for Haiku and Sonnet only

### Scenario: Budget recalculated from actual costs
- **GIVEN** `budget=8.0` and estimated Sonnet cost of $4.60
- **WHEN** Haiku actual cost is $0.80 (under estimate of $1.00)
- **THEN** remaining budget before Sonnet is $8.00 - $0.80 = $7.20, and Sonnet proceeds because $4.60 < $7.20

### Scenario: Batch mode runs all models
- **GIVEN** `progressive=False` and no budget constraint
- **WHEN** `run_multi_model_evaluation()` is called with default models
- **THEN** all three models run in sequence without any interactive prompts, and the final `"comparison"` includes all three

### Scenario: Custom model list respected
- **GIVEN** `models=["claude-sonnet-4-6", "claude-opus-4-6"]` (no Haiku)
- **WHEN** `run_multi_model_evaluation()` is called
- **THEN** only Sonnet and Opus are run, in that order

### Scenario: Budget insufficient for any model
- **GIVEN** `budget=0.50` and a market set of 200 markets
- **WHEN** `run_multi_model_evaluation()` is called
- **THEN** even Haiku (200 * $0.005 = $1.00) exceeds the budget, all models are skipped, and the function returns `{"runs": {}, "comparison": {}}`
