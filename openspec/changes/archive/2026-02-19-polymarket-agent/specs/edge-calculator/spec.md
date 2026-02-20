## ADDED Requirements

### Requirement: Compute expected edge
The system SHALL compute the edge as the difference between the agent's probability estimate and the market's implied probability, adjusted by the agent's confidence.

#### Scenario: Positive edge detected
- **WHEN** the agent estimates P(YES) = 0.60 and the market price is 0.40
- **THEN** the raw edge is 0.20 and the adjusted edge accounts for the confidence band

#### Scenario: No edge detected
- **WHEN** the agent's estimate is within a configurable tolerance of the market price
- **THEN** the edge is considered zero and no trade is recommended

### Requirement: Kelly criterion position sizing
The system SHALL compute position sizes using fractional Kelly criterion (default half-Kelly), subject to hard caps on per-market and portfolio exposure.

#### Scenario: Position size calculation
- **WHEN** a trade has positive adjusted edge
- **THEN** the system computes half-Kelly fraction and translates it to a dollar amount, capped at the per-market maximum

#### Scenario: Position size exceeds per-market cap
- **WHEN** the Kelly-optimal size exceeds the configured per-market maximum
- **THEN** the position size is clamped to the per-market maximum

### Requirement: Trade recommendation output
The system SHALL produce a trade recommendation containing: market ID, direction (YES/NO), edge magnitude, recommended position size, limit price, and the reasoning summary.

#### Scenario: Trade recommended
- **WHEN** adjusted edge exceeds the minimum threshold AND risk checks pass
- **THEN** a trade recommendation is produced with all required fields

#### Scenario: No trade recommended
- **WHEN** adjusted edge is below the minimum threshold OR risk checks fail
- **THEN** no trade recommendation is produced and the reason is logged

### Requirement: Minimum edge threshold
The system SHALL only recommend trades when the adjusted edge exceeds a configurable minimum threshold (default 0.10).

#### Scenario: Edge above threshold
- **WHEN** adjusted edge is 0.15 and threshold is 0.10
- **THEN** the trade passes the edge filter

#### Scenario: Edge below threshold
- **WHEN** adjusted edge is 0.07 and threshold is 0.10
- **THEN** the trade is rejected by the edge filter

### Requirement: Minimum trade size
The system SHALL enforce a minimum trade size of $1.00. If the Kelly-computed size falls below this floor, no trade recommendation is produced (the edge is too small to be worth executing).

#### Scenario: Size below minimum
- **WHEN** the Kelly-computed trade size is less than $1.00
- **THEN** no trade recommendation is produced
