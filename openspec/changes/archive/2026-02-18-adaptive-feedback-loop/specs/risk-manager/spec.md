## MODIFIED Requirements

### Requirement: Daily loss limit
The system SHALL track daily realized + unrealized P&L and halt all new trading if the daily loss exceeds a configurable threshold (default -$50). The `daily_pnl` table SHALL be populated by the daily report job, providing real P&L data to this check.

#### Scenario: Daily loss threshold breached
- **WHEN** daily P&L (from the `daily_pnl` table) drops below the configured threshold
- **THEN** all new trade recommendations are rejected until the next trading day and a warning is logged

#### Scenario: Daily loss within limits
- **WHEN** daily P&L is above the configured threshold
- **THEN** trading continues normally

#### Scenario: No daily P&L data yet today
- **WHEN** the `daily_pnl` table has no entry for today (report hasn't run yet)
- **THEN** the daily loss check passes (assumes 0 P&L), allowing trading to proceed
