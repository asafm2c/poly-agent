## Purpose

Extend the simulation runner to accept an optional `hypothesis_id` parameter that links simulation runs to hypotheses and auto-populates evidence records on completion. This enables the hypothesis lifecycle to gather evidence through targeted simulations without modifying the core simulation logic.

## MODIFIED Requirements

### Requirement: Hypothesis-linked simulation runs
The `run_simulation()` function SHALL accept an optional `hypothesis_id` parameter (default None). When provided, the hypothesis ID SHALL be included in the `config` JSON written to the `bt_simulation_runs` record.

#### Scenario: Simulation run with hypothesis_id
- **GIVEN** a hypothesis with ID 2 in `testing` status
- **WHEN** `run_simulation(markets, hypothesis_id=2)` is called
- **THEN** the `bt_simulation_runs.config` JSON includes `"hypothesis_id": 2`

#### Scenario: Simulation run without hypothesis_id
- **GIVEN** a standard simulation invocation
- **WHEN** `run_simulation(markets)` is called without `hypothesis_id`
- **THEN** the simulation runs identically to the current behavior and no hypothesis evidence is recorded

### Requirement: Auto-record hypothesis evidence on completion
When `hypothesis_id` is not None and the simulation completes, the runner SHALL automatically record evidence by calling `record_evidence()` with the simulation's aggregate metrics: `agent_brier`, `market_brier`, `brier_diff`, `simulated_pnl`, `trial_count`, `p_value`, `effect_size`, and computed `supports_hypothesis`.

#### Scenario: Evidence auto-recorded after successful simulation
- **GIVEN** a simulation run linked to hypothesis ID 2 that completes with `agent_brier=0.15`, `market_brier=0.20`, 35 valid trials
- **WHEN** the simulation run completes
- **THEN** a `bt_hypothesis_evidence` row is inserted with `hypothesis_id=2`, `run_id` matching the simulation, `brier_diff=-0.05`, `trial_count=35`, `supports_hypothesis=1`, and computed `p_value` and `effect_size`

#### Scenario: Evidence records supports_hypothesis correctly
- **GIVEN** a simulation run linked to a hypothesis that completes with `agent_brier=0.22`, `market_brier=0.18` (agent worse)
- **WHEN** evidence is auto-recorded
- **THEN** `brier_diff=0.04` and `supports_hypothesis=0`

#### Scenario: Evidence with insufficient trials is inconclusive
- **GIVEN** a simulation run linked to a hypothesis with only 3 valid trials
- **WHEN** evidence is auto-recorded
- **THEN** `supports_hypothesis=NULL` and `p_value=NULL`

### Requirement: Paired t-test computation for evidence
The simulation runner SHALL compute a paired t-test p-value and Cohen's d effect size from per-trial Brier scores when the number of valid trials is >= 5. The p-value SHALL use a normal approximation (via `math.erfc`) to avoid requiring scipy as a dependency.

#### Scenario: P-value computed for hypothesis evidence
- **GIVEN** a simulation run with 40 trials, each having `agent_brier` and `market_brier`
- **WHEN** `_compute_paired_stats(run_id, db_path)` is called
- **THEN** a paired t-test is computed from per-trial Brier differences, and `(p_value, effect_size)` is returned

#### Scenario: Insufficient trials for p-value
- **GIVEN** a simulation run with only 4 valid trials
- **WHEN** `_compute_paired_stats()` is called
- **THEN** `(None, None)` is returned

### Requirement: Hypothesis evidence does not block simulation
If recording hypothesis evidence fails (e.g., hypothesis row deleted, database error), the simulation results SHALL still be persisted to `bt_simulation_runs` and `bt_simulation_trials`. Evidence recording errors SHALL be logged as warnings, not raised as exceptions.

#### Scenario: Evidence recording failure is non-fatal
- **GIVEN** a simulation linked to a hypothesis that has been deleted from the database
- **WHEN** the simulation completes and `_record_hypothesis_evidence()` raises an error
- **THEN** the simulation run and trials are still persisted, a warning is logged, and the function returns normally
