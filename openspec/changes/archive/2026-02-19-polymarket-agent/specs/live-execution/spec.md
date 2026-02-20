## ADDED Requirements

### Requirement: Place orders via CLOB API
The system SHALL place limit orders on the Polymarket CLOB using the py-clob-client SDK, signing orders with the configured wallet private key.

#### Scenario: Successful limit order placement
- **WHEN** the agent recommends a trade and all risk checks pass
- **THEN** a limit order is placed on the CLOB with the recommended price and size, and the order ID is recorded

#### Scenario: Order placement failure
- **WHEN** an order submission fails (API error, network issue, insufficient balance)
- **THEN** the error is logged, the trade is marked as failed, and no retry is attempted automatically

### Requirement: Monitor order status
The system SHALL track the status of placed orders (open, partially filled, filled, cancelled, expired) and update position records accordingly.

#### Scenario: Order fully filled
- **WHEN** a placed order is fully filled
- **THEN** the position record is updated with the fill price and quantity, and the portfolio is adjusted

#### Scenario: Order not filled within timeout
- **WHEN** a limit order remains unfilled for longer than a configurable timeout
- **THEN** the order is cancelled via the CLOB API and logged as expired

### Requirement: Wallet and balance management
The system SHALL check USDC.e balance and token allowances before placing orders, and report insufficient funds or allowance issues clearly.

#### Scenario: Sufficient balance and allowances
- **WHEN** the wallet has enough USDC.e and token allowances are set
- **THEN** the order proceeds normally

#### Scenario: Insufficient USDC balance
- **WHEN** the wallet USDC.e balance is less than the order cost
- **THEN** the order is rejected with a clear "insufficient USDC balance" message

### Requirement: Position exit capability
The system SHALL support selling existing positions by placing sell orders on the CLOB, enabling early exit from positions before market resolution.

#### Scenario: Sell position
- **WHEN** the agent or operator decides to exit a position early
- **THEN** a sell limit order is placed for the held shares at the specified price

### Requirement: Execution logging
The system SHALL log every order placed, filled, cancelled, or failed with full details: timestamp, market, direction, price, size, order ID, status, and fill details.

#### Scenario: Trade execution audit trail
- **WHEN** any order state change occurs
- **THEN** the event is logged to the database and optionally to a structured log file
