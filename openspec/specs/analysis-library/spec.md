## Purpose

Extend the analysis library with functions to query hypothesis evidence alongside simulation results, and to compute hypothesis-specific metrics from trial data. These additions enable hypothesis-aware aggregation -- filtering and grouping simulation results by the hypothesis they were run to test.

## MODIFIED Requirements

### Requirement: Hypothesis evidence aggregation
The analysis library SHALL provide a `hypothesis_evidence_summary()` function that loads all evidence records for a given hypothesis ID and returns aggregate metrics: total trial count, weighted Brier diff, weighted confidence, number of supporting vs contradicting evidence records, and the most recent evidence date.

#### Scenario: Summary for hypothesis with multiple evidence records
- **GIVEN** a hypothesis with ID 1 that has 3 evidence records from different simulation runs
- **WHEN** `hypothesis_evidence_summary(hypothesis_id=1)` is called
- **THEN** the function returns a dict with `total_trial_count`, `weighted_brier_diff`, `weighted_confidence`, `supporting_count`, `contradicting_count`, `inconclusive_count`, `latest_evidence_date`, and `evidence_count`

#### Scenario: Summary for hypothesis with no evidence
- **GIVEN** a hypothesis with ID 5 that has zero evidence records (status='proposed')
- **WHEN** `hypothesis_evidence_summary(hypothesis_id=5)` is called
- **THEN** the function returns a dict with all counts at 0, `weighted_brier_diff=0.0`, `weighted_confidence=0.0`, and `latest_evidence_date=None`

### Requirement: Hypothesis-filtered simulation metrics
The analysis library SHALL provide a `simulation_by_hypothesis()` function that groups trial results from all simulation runs linked to a specific hypothesis, returning aggregate metrics across those runs.

#### Scenario: Metrics across hypothesis-linked runs
- **GIVEN** a hypothesis with ID 2 linked to 3 simulation runs totaling 80 trials
- **WHEN** `simulation_by_hypothesis(hypothesis_id=2)` is called
- **THEN** the function returns a dict with `agent_brier`, `market_brier`, `brier_diff`, `trial_count`, `simulated_pnl`, `trade_count`, and `win_rate` aggregated across all 80 trials from those 3 runs

#### Scenario: No linked simulation runs
- **GIVEN** a hypothesis with ID 3 that has no linked simulation runs
- **WHEN** `simulation_by_hypothesis(hypothesis_id=3)` is called
- **THEN** the function returns a dict with `trial_count=0` and all metrics as None

### Requirement: Paired statistical comparison
The analysis library SHALL provide a `compute_paired_stats()` function that computes a paired t-test p-value and Cohen's d effect size from per-trial Brier scores for a given simulation run. This function SHALL use a normal approximation for the p-value (no scipy dependency) and SHALL require a minimum of 5 trials.

#### Scenario: Sufficient trials for paired test
- **GIVEN** a simulation run with 40 trials that all have `agent_brier` and `market_brier` values
- **WHEN** `compute_paired_stats(run_id=1)` is called
- **THEN** the function returns a tuple of `(p_value, effect_size)` where `p_value` is a float in [0, 1] and `effect_size` (Cohen's d) is a float

#### Scenario: Insufficient trials
- **GIVEN** a simulation run with only 3 valid trials
- **WHEN** `compute_paired_stats(run_id=1)` is called
- **THEN** the function returns `(None, None)`

#### Scenario: All trials agree (zero variance edge case)
- **GIVEN** a simulation run where all per-trial Brier diffs are identical
- **WHEN** `compute_paired_stats()` is called
- **THEN** the function handles the zero-variance case gracefully (uses a small epsilon for standard deviation) and returns a valid p_value and effect_size
