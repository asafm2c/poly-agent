## ADDED Requirements

### Requirement: Simulation results aggregation
The analysis library SHALL provide a `simulation_summary()` function that loads simulation trial data from the backtest DB for a given run ID and returns aggregate metrics: agent Brier score, market Brier score, Brier difference, simulated P&L, trade count, win rate, and total LLM cost.

#### Scenario: Summary for a completed run
- **WHEN** `simulation_summary(run_id=1)` is called for a completed run with 50 trials
- **THEN** the function returns a dict with `agent_brier`, `market_brier`, `brier_diff`, `simulated_pnl`, `trade_count`, `win_rate`, `total_cost`, and `trial_count`

#### Scenario: Summary for run with no trades
- **WHEN** a run has trials but none exceeded the edge threshold
- **THEN** `trade_count` is 0, `win_rate` is None, and `simulated_pnl` is 0.0

### Requirement: Simulation results by category
The analysis library SHALL provide a `simulation_by_category()` function that groups trial results by market category and returns per-category metrics.

#### Scenario: Multi-category breakdown
- **WHEN** `simulation_by_category(run_id=1)` is called
- **THEN** the function returns a dict keyed by category, each containing `agent_brier`, `market_brier`, `brier_diff`, `trial_count`, and `simulated_pnl`

### Requirement: Simulation results by volume tier
The analysis library SHALL provide a `simulation_by_volume_tier()` function that groups trial results by volume tier (>10M, 1M-10M, 100K-1M, 10K-100K) and returns per-tier metrics.

#### Scenario: Volume tier breakdown
- **WHEN** `simulation_by_volume_tier(run_id=1)` is called
- **THEN** the function returns a dict keyed by volume tier, each containing `agent_brier`, `market_brier`, `brier_diff`, `trial_count`, and `simulated_pnl`
