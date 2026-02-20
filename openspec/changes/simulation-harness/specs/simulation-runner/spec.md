## ADDED Requirements

### Requirement: Historical market selection
The simulation runner SHALL select markets from the backtest DB using configurable filters: category, volume range (min/max), regime, and resolution outcome. Markets SHALL be randomly sampled up to a configurable limit (default 50). Only markets with `has_history = 1` and a valid `resolution_outcome` (YES or NO) SHALL be eligible.

#### Scenario: Default market selection
- **WHEN** the simulation is run with no filters
- **THEN** up to 50 markets are randomly selected from null-category markets with volume >= 100,000 that have price history and a YES/NO resolution outcome

#### Scenario: Category-filtered selection
- **WHEN** the simulation specifies `--category crypto`
- **THEN** only markets with `category = 'crypto'` are eligible for selection

#### Scenario: Volume-filtered selection
- **WHEN** the simulation specifies `--min-volume 1000000`
- **THEN** only markets with `volume >= 1000000` are eligible for selection

#### Scenario: Insufficient eligible markets
- **WHEN** fewer markets match the filters than the requested sample size
- **THEN** all matching markets are used and the actual count is logged

### Requirement: Historical context construction
The simulation runner SHALL construct a research dossier for each market using only information available at the specified horizon (days before resolution). The dossier SHALL include a price history summary computed from `bt_price_history` data up to the horizon timestamp, market metadata (question, description, category, end date, volume), and an explicit note that web search is unavailable. The dossier SHALL NOT include web search results, Polymarket comments, order book data, or any information from after the horizon timestamp.

#### Scenario: Price history truncated to horizon
- **WHEN** a market is simulated at horizon 7 days before resolution
- **THEN** the dossier's price history summary uses only price data points with timestamps before (resolution_date - 7 days), and the "current price" in the summary is the last available price before that cutoff

#### Scenario: Price history summary format
- **WHEN** a dossier is constructed from historical price data
- **THEN** the summary includes: opening price (first available), current price (at horizon), high, low, 7-day price change, and 30-day price change (when sufficient history exists)

#### Scenario: No price data at horizon
- **WHEN** no price history exists within 1 day of the target horizon timestamp
- **THEN** the market is skipped for this trial and logged as "insufficient data"

### Requirement: Estimation pipeline invocation
The simulation runner SHALL invoke the existing `ProbabilityEstimator` with a `HistoricalResearchGatherer` that returns the historical dossier instead of making live API calls. The estimator SHALL run its full multi-pass pipeline (base rate, Bayesian update, adversarial, calibration) using the historical context. The `Market` object passed to the estimator SHALL have `last_price_yes` set to the market price at the horizon timestamp.

#### Scenario: Full estimation pipeline runs
- **WHEN** a historical market is simulated
- **THEN** the estimator runs all passes (base rate, update, adversarial, calibration) and returns a `ProbabilityEstimate` with `final_estimate`, `confidence_low`, `confidence_high`, and `thesis`

#### Scenario: Estimation error handling
- **WHEN** the estimation pipeline raises an exception for a market
- **THEN** the trial is recorded with `agent_estimate = NULL`, the error is logged, and simulation continues to the next market

### Requirement: Simulated P&L computation
The simulation runner SHALL compute simulated profit/loss for each trial where the agent's edge exceeds the adaptive threshold. The trade side SHALL be YES if `agent_estimate > market_price`, NO otherwise. Position size SHALL use Kelly criterion with a normalized bankroll of $1,000. Taker fees SHALL be deducted at 2% round-trip (conservative default). The exit price SHALL be the resolution outcome (1.0 for YES, 0.0 for NO).

#### Scenario: Agent finds edge and trades
- **WHEN** the agent estimate is 0.70, market price is 0.55, and the adaptive threshold is 0.10
- **THEN** a simulated YES trade is recorded with edge = 0.15, position size computed by Kelly criterion, and P&L = (shares × (1.0 - entry_price)) - fees for a YES-resolved market

#### Scenario: Agent estimate below threshold
- **WHEN** the absolute edge is below the adaptive threshold
- **THEN** no trade is simulated and `simulated_trade` is NULL for that trial

#### Scenario: Agent trades wrong side
- **WHEN** the agent buys YES (estimate 0.70) but the market resolves NO
- **THEN** P&L is negative: -(shares × entry_price) - fees

### Requirement: Simulation run lifecycle
The simulation runner SHALL create a `bt_simulation_runs` record at start, update it with aggregate results on completion, and persist each trial to `bt_simulation_trials` as it completes. Progress SHALL be logged every 5 trials. The run record SHALL include total LLM cost, agent Brier score, market Brier score, and simulated P&L.

#### Scenario: Run start
- **WHEN** a simulation is started
- **THEN** a `bt_simulation_runs` record is created with `started_at`, `config` (JSON of all parameters), and `market_count`

#### Scenario: Trial completion
- **WHEN** a single market estimation completes
- **THEN** a `bt_simulation_trials` record is written immediately with all computed fields

#### Scenario: Run completion
- **WHEN** all trials in a run complete
- **THEN** the run record is updated with `completed_at`, aggregate `agent_brier`, `market_brier`, `simulated_pnl`, and `total_cost`

#### Scenario: Progress reporting
- **WHEN** every 5 trials complete
- **THEN** a log message reports: trials completed/total, running agent Brier, running market Brier, elapsed time

### Requirement: Dry run mode
The simulation runner SHALL support a `--dry-run` flag that selects markets and displays what would be simulated without invoking the LLM or persisting results.

#### Scenario: Dry run output
- **WHEN** `--dry-run` is specified
- **THEN** the selected markets are listed with their question, category, volume, and price at horizon, but no LLM calls are made and no database records are created

### Requirement: CLI commands for simulation
The CLI SHALL provide `backtest simulate` to run a simulation and `backtest results` to display past run results.

#### Scenario: Run simulation from CLI
- **WHEN** `polymarket backtest simulate` is invoked with optional `--horizon`, `--count`, `--category`, `--min-volume`, `--max-volume`, `--regime` flags
- **THEN** the simulation runs with those parameters, showing progress and a summary on completion

#### Scenario: Display results from CLI
- **WHEN** `polymarket backtest results` is invoked
- **THEN** the most recent simulation run's summary is displayed: agent vs market Brier score, simulated P&L, trial count, cost, and per-category breakdown

#### Scenario: Display specific run results
- **WHEN** `polymarket backtest results --run-id 3` is invoked
- **THEN** the summary for run ID 3 is displayed
