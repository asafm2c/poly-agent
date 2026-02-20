## ADDED Requirements

### Requirement: Virtual portfolio management
The system SHALL maintain a virtual portfolio with a configurable starting balance, tracking virtual positions, cash balance, and total portfolio value.

#### Scenario: Initial portfolio creation
- **WHEN** paper trading is started for the first time
- **THEN** a virtual portfolio is created with the configured starting balance and zero positions

#### Scenario: Portfolio value calculation
- **WHEN** the portfolio status is requested
- **THEN** the system calculates total value as cash + sum of (position_size * current_market_price) for all open positions

### Requirement: Simulate trade execution
The system SHALL record virtual trades when the agent produces trade recommendations, deducting from virtual cash and creating virtual positions. Trades use the market's current midpoint price (no actual orders placed).

#### Scenario: Virtual buy execution
- **WHEN** the agent recommends buying YES shares on a market
- **THEN** a virtual position is created, virtual cash is reduced by the cost, and the trade is logged with timestamp, price, and size

#### Scenario: Insufficient virtual cash
- **WHEN** a trade recommendation exceeds available virtual cash
- **THEN** the trade is skipped and logged as rejected due to insufficient funds

### Requirement: Position resolution tracking
The system SHALL automatically resolve virtual positions when their corresponding Polymarket markets resolve, recording profit or loss.

#### Scenario: Market resolves in favor of position
- **WHEN** a market resolves YES and the agent holds YES shares
- **THEN** virtual cash increases by the number of shares (each pays $1) and the position is closed with profit recorded

#### Scenario: Market resolves against position
- **WHEN** a market resolves NO and the agent holds YES shares
- **THEN** the position is closed with the full cost recorded as a loss

### Requirement: P&L tracking and reporting
The system SHALL track realized P&L (from resolved positions), unrealized P&L (from open positions at current prices), and total return on the virtual portfolio.

#### Scenario: Daily P&L report
- **WHEN** a daily report is generated
- **THEN** it includes: total portfolio value, cash balance, number of open positions, realized P&L, unrealized P&L, total return percentage, and list of recent trades

### Requirement: Trade history log
The system SHALL maintain a complete log of all virtual trades with timestamps, market details, entry price, size, direction, and resolution outcome (when resolved).

#### Scenario: Trade log query
- **WHEN** the operator queries trade history
- **THEN** all virtual trades are returned with full details, ordered by timestamp
