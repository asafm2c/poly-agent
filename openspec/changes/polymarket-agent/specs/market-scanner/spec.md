## ADDED Requirements

### Requirement: Discover active markets
The system SHALL fetch all active markets from the Polymarket Gamma API and store them locally with metadata (title, description, category, resolution criteria, end date, volume, liquidity).

#### Scenario: Initial market discovery
- **WHEN** the scanner runs a discovery cycle
- **THEN** all active Polymarket markets are fetched from the Gamma API and stored in the local database with their metadata

#### Scenario: Incremental updates
- **WHEN** the scanner runs after an initial discovery
- **THEN** only new or changed markets are updated in the database (not a full refetch of unchanged data)

### Requirement: Filter markets by tradeability criteria
The system SHALL filter markets based on configurable criteria: minimum volume, minimum liquidity, price range (exclude near-certain >0.90 or near-impossible <0.10), time to resolution (min and max days), and market status (active, not resolved).

#### Scenario: Market meets all filter criteria
- **WHEN** a market has volume >= configured minimum AND liquidity >= configured minimum AND price between configured bounds AND resolution date within configured range
- **THEN** the market is included in the candidate set for analysis

#### Scenario: Market fails a filter criterion
- **WHEN** a market fails any one of the configured filter criteria
- **THEN** the market is excluded from the candidate set

### Requirement: Detect market events
The system SHALL detect notable events on tracked markets: significant price movements (configurable threshold), volume spikes, new markets in tracked categories, and markets approaching resolution.

#### Scenario: Price movement detected
- **WHEN** a market's price changes by more than the configured threshold since last check
- **THEN** the market is flagged as having a price event with the magnitude and direction recorded

#### Scenario: New market in tracked category
- **WHEN** a new market appears in a category the agent is configured to track (e.g., politics, crypto)
- **THEN** the market is flagged as a new market event for priority screening

### Requirement: Fetch market pricing data
The system SHALL fetch current prices, order book depth, and price history from the CLOB API for candidate markets.

#### Scenario: Price and order book retrieval
- **WHEN** a market is selected for analysis
- **THEN** the system fetches the current best bid/ask, midpoint price, and order book depth from the CLOB API

#### Scenario: Price history retrieval
- **WHEN** a market is selected for analysis
- **THEN** the system fetches available price history from the CLOB API to provide trend context
