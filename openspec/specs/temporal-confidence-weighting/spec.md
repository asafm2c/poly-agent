## Purpose

Computes per-trial training recency scores that quantify how likely a market outcome was present in a model's training data. Markets that resolved during or shortly after a model's training window receive lower weight, while markets that resolved well after the cutoff receive full weight. This enables aggregate metrics to discount potentially contaminated trials, providing a more honest assessment of whether the agent has genuine predictive alpha versus memorized outcomes.

## Requirements

### 1. Model training cutoff registry
`MODEL_TRAINING_CUTOFFS` dict in `analysis.py` MUST map model identifiers to their best-guess training data cutoff dates as ISO-format date strings. Initial values: `"claude-haiku-4-5-20251001"` maps to `"2025-04-01"`, `"claude-sonnet-4-6"` maps to `"2025-04-01"`, `"claude-opus-4-6"` maps to `"2025-04-01"`.

### 2. Recency score function signature
`training_recency_score()` in `analysis.py` MUST accept `resolution_date: str` (ISO-format date) and `model: str`, and MUST return a float between 0.0 and 1.0 inclusive.

### 3. Score computation formula
The score MUST be computed as:
- If `resolution_date <= cutoff_date`: return 0.0 (resolved during training window)
- If `resolution_date >= cutoff_date + 180 days`: return 1.0 (fully clean)
- Otherwise: return `(resolution_date - cutoff_date).days / 180.0` (linear interpolation)

### 4. Unknown model handling
If the `model` string is not found in `MODEL_TRAINING_CUTOFFS`, `training_recency_score()` MUST return 1.0 (assume clean) and SHOULD log a warning.

### 5. Score persistence
The `training_recency_score` MUST be stored in the `training_recency_score` column of `bt_simulation_trials` when the trial is recorded. The score MUST be computed inside `run_simulation()` from the market's `end_date` and the `model` parameter.

### 6. Weighted Brier function signature
`weighted_brier()` in `analysis.py` MUST accept `trials: list[dict]` and `weight_key: str = "training_recency_score"`, and MUST return a dict with keys `"agent_brier_weighted"`, `"market_brier_weighted"`, `"brier_diff_weighted"`, `"total_weight"`, and `"trial_count"`.

### 7. Weighted mean formula
`weighted_brier()` MUST compute weighted means as `sum(w_i * brier_i) / sum(w_i)` for both agent and market Brier scores. The `"brier_diff_weighted"` MUST be `agent_brier_weighted - market_brier_weighted`.

### 8. NULL weight handling
When a trial has a NULL or missing `training_recency_score`, `weighted_brier()` MUST treat the weight as 1.0 (assume clean). This ensures backward compatibility with trials from runs that predate the training recency feature.

### 9. Zero total weight
If all trials have weight 0.0 (all resolved within training window), `weighted_brier()` MUST return `None` for the weighted scores and include `"total_weight": 0.0`.

### 10. Cutoff date updatability
The `MODEL_TRAINING_CUTOFFS` dict MUST be the single source of truth for training cutoff dates. Updating a date in this dict MUST be sufficient to change all downstream recency calculations for future runs.

## Scenarios

### Scenario: Market resolved during training window
- **GIVEN** model `claude-sonnet-4-6` with cutoff `2025-04-01`
- **WHEN** `training_recency_score("2025-03-15", "claude-sonnet-4-6")` is called
- **THEN** the score is 0.0

### Scenario: Market resolved well after training cutoff
- **GIVEN** model `claude-sonnet-4-6` with cutoff `2025-04-01`
- **WHEN** `training_recency_score("2025-12-01", "claude-sonnet-4-6")` is called
- **THEN** the score is 1.0 (244 days after cutoff, exceeds 180-day threshold)

### Scenario: Market resolved in the ramp-up period
- **GIVEN** model `claude-sonnet-4-6` with cutoff `2025-04-01`
- **WHEN** `training_recency_score("2025-07-01", "claude-sonnet-4-6")` is called
- **THEN** the score is approximately 0.506 (91 days / 180 days)

### Scenario: Unknown model returns clean score
- **GIVEN** model `claude-unknown-99` is not in `MODEL_TRAINING_CUTOFFS`
- **WHEN** `training_recency_score("2025-06-01", "claude-unknown-99")` is called
- **THEN** the score is 1.0 and a warning is logged

### Scenario: Weighted Brier with mixed recency
- **GIVEN** 3 trials: (agent_brier=0.10, weight=1.0), (agent_brier=0.30, weight=0.5), (agent_brier=0.20, weight=0.0)
- **WHEN** `weighted_brier(trials)` is called
- **THEN** the third trial (weight=0.0) is effectively excluded, and agent_brier_weighted = (0.10 * 1.0 + 0.30 * 0.5) / (1.0 + 0.5) = 0.167

### Scenario: All trials in training window
- **GIVEN** all trials have `training_recency_score = 0.0`
- **WHEN** `weighted_brier(trials)` is called
- **THEN** weighted scores are `None` and `"total_weight"` is 0.0

### Scenario: Legacy trials with NULL recency scores
- **GIVEN** trials from a run that predates the training recency feature have `training_recency_score = None`
- **WHEN** `weighted_brier(trials)` is called
- **THEN** those trials are treated as weight 1.0 and included at full weight

### Scenario: Score stored on trial creation
- **GIVEN** `run_simulation()` is called with `model="claude-sonnet-4-6"` for a market with `end_date="2025-08-15"`
- **WHEN** the trial is persisted to `bt_simulation_trials`
- **THEN** the `training_recency_score` column contains approximately 0.756 (136 days / 180)
