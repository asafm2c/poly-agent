## ADDED Requirements

### Requirement: Simulation trial cost tracks per-trial LLM spend
The simulation harness SHALL record the per-trial LLM cost as the delta between the cumulative cost before and after each trial's estimation call. The `bt_simulation_trials.llm_cost` column SHALL contain only the cost incurred by that specific trial, not the running total.

#### Scenario: Per-trial cost is accurate
- **WHEN** a simulation run processes 3 markets costing $0.03, $0.04, and $0.05 respectively
- **THEN** `bt_simulation_trials.llm_cost` contains 0.03, 0.04, and 0.05 (not 0.03, 0.07, 0.12)

#### Scenario: Run-level total matches sum of trials
- **WHEN** a simulation run completes
- **THEN** `bt_simulation_runs.total_cost` equals the sum of all `bt_simulation_trials.llm_cost` values for that run

### Requirement: CLI analyze command correctly handles no-trade case
The `analyze` CLI command SHALL unpack the 3-tuple returned by `build_recommendation()` and SHALL display "no trade recommended" when the recommendation is `None` (edge below threshold).

#### Scenario: Edge below threshold shows no recommendation
- **WHEN** a user runs `polymarket analyze <market-id>` and the adjusted edge is below the required threshold
- **THEN** the CLI displays "No trade recommended (edge below threshold)" and does NOT show trade details

#### Scenario: Edge above threshold shows recommendation
- **WHEN** a user runs `polymarket analyze <market-id>` and the adjusted edge exceeds the required threshold
- **THEN** the CLI displays the trade recommendation with side, edge, size, and limit price
