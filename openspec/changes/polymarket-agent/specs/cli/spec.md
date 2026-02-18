## ADDED Requirements

### Requirement: Market scanning command
The system SHALL provide a `scan` CLI command that runs the market scanner and displays filtered candidate markets in a table format.

#### Scenario: Scan with default filters
- **WHEN** the operator runs `polymarket scan`
- **THEN** the system scans all markets, applies default filters, and displays a table of candidate markets with columns: title, category, price, volume, days to resolution

#### Scenario: Scan with custom filters
- **WHEN** the operator runs `polymarket scan --category politics --min-volume 10000`
- **THEN** only markets matching the specified filters are displayed

### Requirement: Market analysis command
The system SHALL provide an `analyze` CLI command that runs the full research + estimation pipeline on a specific market and displays the results.

#### Scenario: Analyze a specific market
- **WHEN** the operator runs `polymarket analyze <market-id>`
- **THEN** the system gathers research, runs three-pass estimation, computes edge, and displays: market title, current price, agent estimate, edge, recommendation, and reasoning summary

### Requirement: Portfolio status command
The system SHALL provide a `portfolio` CLI command that displays current positions, P&L, and portfolio summary.

#### Scenario: View portfolio
- **WHEN** the operator runs `polymarket portfolio`
- **THEN** the system displays: total value, cash balance, open positions table (market, direction, size, entry price, current price, unrealized P&L), and aggregate metrics

### Requirement: Trade execution command
The system SHALL provide a `trade` CLI command for manual trade execution, with a confirmation prompt before placing real orders.

#### Scenario: Manual trade with confirmation
- **WHEN** the operator runs `polymarket trade <market-id> --side YES --amount 25`
- **THEN** the system displays the order details and asks for confirmation before placing the order

### Requirement: Report generation command
The system SHALL provide a `report` CLI command that generates a summary of recent activity, performance, and calibration metrics.

#### Scenario: Daily report
- **WHEN** the operator runs `polymarket report`
- **THEN** the system displays: trades placed today, positions resolved, P&L summary, calibration stats (if available), and active position count

### Requirement: Agent run command
The system SHALL provide a `run` CLI command that starts the automated agent loop (scheduler), running continuous scan-analyze-trade cycles.

#### Scenario: Start agent
- **WHEN** the operator runs `polymarket run`
- **THEN** the scheduler starts, executing periodic scans and analysis according to configured intervals, logging activity to the console

#### Scenario: Run in paper mode
- **WHEN** the operator runs `polymarket run --paper`
- **THEN** the agent operates in paper trading mode, recording virtual trades instead of placing real orders

### Requirement: Kill switch command
The system SHALL provide a `kill` CLI command that immediately halts all trading.

#### Scenario: Activate kill switch
- **WHEN** the operator runs `polymarket kill`
- **THEN** all trading is halted immediately and a confirmation message is displayed

### Requirement: Configuration display
The system SHALL provide a `config` CLI command that displays current configuration (risk limits, API status, filter settings, mode).

#### Scenario: View configuration
- **WHEN** the operator runs `polymarket config`
- **THEN** all current settings are displayed in a readable format with sensitive values (API keys) masked
