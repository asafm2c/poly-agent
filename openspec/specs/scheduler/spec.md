## MODIFIED Requirements

### Requirement: Periodic market scanning
The system SHALL run market scanning at a configurable interval (default every 15 minutes) to discover new markets, detect price events, record price snapshots, and detect market resolutions.

#### Scenario: Scheduled scan execution
- **WHEN** the scan interval elapses
- **THEN** the market scanner runs, updates the market database, records price snapshots for tracked markets (with open positions or unresolved predictions), identifies candidates for analysis, and checks for resolved markets with open positions or predictions

#### Scenario: Resolution detected during scan
- **WHEN** the scan detects a market with `resolved=True` that has open positions or unresolved predictions
- **THEN** the system calls `update_prediction_outcome()` for that market's predictions and `resolve_positions()` for that market's open positions, logging each resolution

#### Scenario: Resolution outcome mapping
- **WHEN** a market resolves with `resolution_outcome` of "YES"
- **THEN** `update_prediction_outcome()` is called with outcome=1.0 and `resolve_positions()` is called with outcome="YES"

#### Scenario: Resolution outcome mapping for NO
- **WHEN** a market resolves with `resolution_outcome` of "NO"
- **THEN** `update_prediction_outcome()` is called with outcome=0.0 and `resolve_positions()` is called with outcome="NO"

### Requirement: Periodic position re-evaluation
The system SHALL re-evaluate open positions at a configurable interval (default every 4 hours) using a tiered decision framework: cheap edge computation first, expensive LLM re-analysis only when needed. Positions marked for exit SHALL be closed in paper mode.

#### Scenario: Position re-evaluation with exit signals
- **WHEN** the re-evaluation interval elapses and open positions exist
- **THEN** for each open position, the system retrieves the original prediction estimate and current market price, computes remaining edge, and applies the tiered decision framework (hold/exit/re-analyze)

#### Scenario: No open positions
- **WHEN** the re-evaluation interval elapses and no open positions exist
- **THEN** the cycle is skipped and logged

### Requirement: Daily portfolio report
The system SHALL generate a daily portfolio report at a configurable time (default 18:00 UTC) summarizing the day's activity, P&L, and calibration metrics. The report SHALL also compute and persist daily P&L to the `daily_pnl` table, and run price snapshot cleanup.

#### Scenario: Daily report generation
- **WHEN** the daily report time is reached
- **THEN** a comprehensive report is generated and logged, including: trades, resolutions, P&L (realized and unrealized using latest price snapshots), calibration update, and open positions

#### Scenario: Daily P&L persistence
- **WHEN** the daily report is generated
- **THEN** the system computes today's realized P&L (from positions closed today), unrealized P&L (mark-to-market using latest price snapshots), total P&L, portfolio value, and trade count, and writes them to the `daily_pnl` table via INSERT OR REPLACE

#### Scenario: Snapshot cleanup during daily report
- **WHEN** the daily report runs
- **THEN** the system deletes price snapshots older than `snapshot_retention_days` (default 30) and logs the count of deleted rows
