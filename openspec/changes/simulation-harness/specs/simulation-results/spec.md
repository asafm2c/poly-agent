## ADDED Requirements

### Requirement: Simulation results schema
The backtest database SHALL include `bt_simulation_runs` and `bt_simulation_trials` tables to persist simulation outcomes. The runs table SHALL store run-level configuration and aggregate metrics. The trials table SHALL store per-market results including agent estimate, market price, outcome, Brier scores, edge, simulated trade details, reasoning, LLM cost, and duration.

#### Scenario: Run record schema
- **WHEN** a simulation run is persisted
- **THEN** the `bt_simulation_runs` record includes: `id` (autoincrement), `started_at`, `completed_at`, `config` (JSON), `market_count`, `agent_brier`, `market_brier`, `simulated_pnl`, `total_cost`

#### Scenario: Trial record schema
- **WHEN** a simulation trial is persisted
- **THEN** the `bt_simulation_trials` record includes: `id` (autoincrement), `run_id` (FK), `market_id` (FK), `horizon_days`, `market_price_at_horizon`, `agent_estimate`, `confidence_low`, `confidence_high`, `outcome`, `agent_brier`, `market_brier`, `edge`, `simulated_trade` (JSON or NULL), `reasoning`, `llm_cost`, `duration_ms`

### Requirement: Brier score comparison report
The results module SHALL compute and report agent Brier score vs market baseline Brier score for a given run. The comparison SHALL include the difference (agent - market, negative = agent is better), the count of trials, and a 95% confidence interval on the difference using bootstrap resampling.

#### Scenario: Agent beats market
- **WHEN** the agent's Brier score is 0.18 and the market's is 0.22 across 50 trials
- **THEN** the report shows agent Brier = 0.18, market Brier = 0.22, difference = -0.04 (agent better), with confidence interval

#### Scenario: Agent worse than market
- **WHEN** the agent's Brier score is 0.25 and the market's is 0.20
- **THEN** the report shows difference = +0.05 (agent worse) and flags this as a concern

#### Scenario: Insufficient trials for confidence
- **WHEN** fewer than 10 trials exist in a run
- **THEN** the report displays results but notes "insufficient sample size for reliable comparison"

### Requirement: Category breakdown report
The results module SHALL break down simulation performance by market category, showing agent Brier, market Brier, trial count, and simulated P&L per category.

#### Scenario: Multi-category breakdown
- **WHEN** a run contains trials from multiple categories
- **THEN** each category is listed with its own Brier comparison and P&L, sorted by trial count descending

#### Scenario: Single category run
- **WHEN** all trials are from the same category
- **THEN** only that category is shown with no breakdown table

### Requirement: Volume tier breakdown report
The results module SHALL break down simulation performance by volume tier (>10M, 1M-10M, 100K-1M, 10K-100K), showing agent Brier, market Brier, trial count, and simulated P&L per tier.

#### Scenario: Volume tier comparison
- **WHEN** a run contains trials across volume tiers
- **THEN** each tier shows its own metrics, enabling comparison of agent performance in efficient vs inefficient markets

### Requirement: Simulated P&L summary
The results module SHALL report total simulated P&L for a run, including: gross P&L, total fees deducted, net P&L, number of trades taken (where edge exceeded threshold), win rate, and average trade P&L.

#### Scenario: Profitable simulation
- **WHEN** the simulated net P&L is positive
- **THEN** the report shows gross P&L, fees, net P&L, trade count, win rate, and average P&L per trade

#### Scenario: No trades taken
- **WHEN** no trials exceeded the edge threshold
- **THEN** the report notes "no trades simulated — agent found no edge above threshold" and suggests lowering the threshold or expanding the sample
