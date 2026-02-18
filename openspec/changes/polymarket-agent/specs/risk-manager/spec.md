## ADDED Requirements

### Requirement: Per-market position limits
The system SHALL enforce a configurable maximum position size per market (default $50) and reject any trade recommendation that would exceed this limit.

#### Scenario: Trade within per-market limit
- **WHEN** a trade recommendation of $30 is made for a market with no existing position and the per-market limit is $50
- **THEN** the trade passes the per-market risk check

#### Scenario: Trade exceeds per-market limit
- **WHEN** a trade recommendation of $40 is made for a market where the agent already holds a $20 position and the per-market limit is $50
- **THEN** the trade is rejected or reduced to fit within the limit

### Requirement: Portfolio exposure limits
The system SHALL enforce a configurable maximum total portfolio exposure (default $500) across all open positions and reject trades that would exceed this limit.

#### Scenario: Portfolio has capacity
- **WHEN** total open position value is $300 and portfolio limit is $500
- **THEN** new trades up to $200 are permitted

#### Scenario: Portfolio at capacity
- **WHEN** total open position value is $490 and portfolio limit is $500
- **THEN** only trades up to $10 are permitted

### Requirement: Category concentration limits
The system SHALL enforce a configurable maximum exposure per market category (e.g., max $200 in politics markets) to prevent over-concentration in a single domain.

#### Scenario: Category within limit
- **WHEN** the agent holds $150 in politics markets and the category limit is $200
- **THEN** new politics trades up to $50 are permitted

#### Scenario: Category at limit
- **WHEN** the agent holds $200 in politics markets and the category limit is $200
- **THEN** new politics trades are rejected

### Requirement: Daily loss limit
The system SHALL track daily realized + unrealized P&L and halt all new trading if the daily loss exceeds a configurable threshold (default -$50).

#### Scenario: Daily loss threshold breached
- **WHEN** daily P&L drops below the configured threshold
- **THEN** all new trade recommendations are rejected until the next trading day and an alert is sent

#### Scenario: Daily loss within limits
- **WHEN** daily P&L is above the configured threshold
- **THEN** trading continues normally

### Requirement: Kill switch
The system SHALL provide a manual kill switch that immediately halts all trading activity (no new orders placed) and optionally cancels all open orders.

#### Scenario: Kill switch activated
- **WHEN** the operator activates the kill switch via CLI
- **THEN** all scheduled trading is halted immediately, no new orders are placed, and the system logs the activation

#### Scenario: Kill switch with order cancellation
- **WHEN** the operator activates the kill switch with the cancel-orders flag
- **THEN** all open orders on the CLOB are cancelled in addition to halting new trading

### Requirement: Pre-trade liquidity check
The system SHALL verify that sufficient order book liquidity exists before recommending a trade, ensuring the position can be entered without excessive slippage.

#### Scenario: Sufficient liquidity
- **WHEN** the order book depth at the target price supports the position size within configured slippage tolerance
- **THEN** the trade passes the liquidity check

#### Scenario: Insufficient liquidity
- **WHEN** filling the position would move the price beyond the configured slippage tolerance
- **THEN** the trade is rejected or the size is reduced to what the book can support
