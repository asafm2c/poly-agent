## ADDED Requirements

### Requirement: Periodic market scanning
The system SHALL run market scanning at a configurable interval (default every 15 minutes) to discover new markets and detect price events.

#### Scenario: Scheduled scan execution
- **WHEN** the scan interval elapses
- **THEN** the market scanner runs, updates the market database, and identifies candidates for analysis

### Requirement: Periodic deep analysis
The system SHALL run deep analysis (research + estimation) on candidate markets at a configurable interval (default every 1 hour), processing markets flagged by the scanner.

#### Scenario: Scheduled analysis execution
- **WHEN** the analysis interval elapses and candidate markets exist
- **THEN** the research engine and probability estimator process each candidate, producing trade recommendations where edge exists

#### Scenario: No candidates available
- **WHEN** the analysis interval elapses but no candidate markets are flagged
- **THEN** the cycle is skipped and logged

### Requirement: Periodic position re-evaluation
The system SHALL re-evaluate open positions at a configurable interval (default every 4 hours) to check if edge has changed, risk limits are still met, and exits should be considered.

#### Scenario: Position re-evaluation
- **WHEN** the re-evaluation interval elapses
- **THEN** each open position is re-analyzed with current market data and research, and exit recommendations are generated if edge has reversed or risk limits are breached

### Requirement: Daily portfolio report
The system SHALL generate a daily portfolio report at a configurable time (default 18:00 UTC) summarizing the day's activity, P&L, and calibration metrics.

#### Scenario: Daily report generation
- **WHEN** the daily report time is reached
- **THEN** a comprehensive report is generated and logged, including: trades, resolutions, P&L, calibration update, and open positions

### Requirement: Graceful shutdown
The system SHALL handle shutdown signals (SIGTERM, SIGINT) gracefully, completing any in-progress analysis cycle before stopping and not placing orders during shutdown.

#### Scenario: Shutdown during idle
- **WHEN** a shutdown signal is received while no cycle is running
- **THEN** the scheduler stops immediately and logs the shutdown

#### Scenario: Shutdown during active cycle
- **WHEN** a shutdown signal is received during an active analysis cycle
- **THEN** the current cycle completes but no new orders are placed, and the scheduler stops after the cycle finishes

### Requirement: Missed cycle handling
The system SHALL detect and handle missed cycles (e.g., due to system sleep or long-running analysis) by running the missed cycle immediately rather than waiting for the next scheduled time.

#### Scenario: Missed scan cycle
- **WHEN** the scheduler detects that a scan cycle was missed
- **THEN** the scan runs immediately and the schedule resumes from the current time
