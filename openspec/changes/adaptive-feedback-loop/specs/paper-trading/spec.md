## MODIFIED Requirements

### Requirement: Automatic position resolution
The system SHALL automatically resolve paper positions when market resolution is detected during a scan. The existing `resolve_positions()` method SHALL be called from the scheduler's resolution detection step, rather than requiring manual invocation.

#### Scenario: Auto-resolution on scan
- **WHEN** the scan job detects a resolved market that has open paper positions
- **THEN** `resolve_positions(market_id, outcome)` is called automatically, closing positions, computing P&L, and crediting cash

#### Scenario: No open positions for resolved market
- **WHEN** a market resolves but has no open paper positions
- **THEN** no position changes are made (prediction outcomes are still updated separately)

## ADDED Requirements

### Requirement: Exit trade recording
The system SHALL record a sell trade in the `trades` table when a position is closed, whether by market resolution or by re-evaluation exit signal. The trade SHALL have `action='sell'`, the exit price, and the position's share count.

#### Scenario: Sell trade on resolution
- **WHEN** a position is closed due to market resolution with outcome YES and the position was YES
- **THEN** a trade is recorded with action='sell', price=1.0 (winning payout), size=position shares

#### Scenario: Sell trade on re-evaluation exit
- **WHEN** a position is closed due to a re-evaluation exit signal at current market price $0.55
- **THEN** a trade is recorded with action='sell', price=0.55, size=position shares

### Requirement: Paper exit at market price
The system SHALL support closing a paper position at a given price (not just at resolution payouts of 0.0/1.0). This enables re-evaluation exits at the current market price, where realized P&L is `(exit_price - entry_price) * shares` for YES positions and `((1 - exit_price) - (1 - entry_price)) * shares` for NO positions.

#### Scenario: Paper exit for YES position
- **WHEN** a YES position of 100 shares at entry price $0.40 is exited at market price $0.55
- **THEN** realized P&L is (0.55 - 0.40) * 100 = $15.00 and cash is credited 100 * 0.55 = $55.00

#### Scenario: Paper exit for NO position
- **WHEN** a NO position of 100 shares at entry price $0.60 is exited when market YES price is $0.45 (NO price = $0.55)
- **THEN** realized P&L is (0.55 - 0.60) * 100 = -$5.00 and cash is credited 100 * 0.55 = $55.00
