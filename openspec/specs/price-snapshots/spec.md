## ADDED Requirements

### Requirement: Record price snapshots for tracked markets on every scan
The system SHALL record a price snapshot for every tracked market (those with open positions or unresolved predictions) during each scan cycle. Each snapshot SHALL include the market ID, timestamp, YES price, NO price, and volume. Snapshots are append-only and SHALL NOT modify the existing `markets` table. Only tracked markets are snapshotted to keep storage bounded; all-market snapshotting may be added later if pre-trade price history proves valuable.

#### Scenario: Scan records snapshots for tracked markets
- **WHEN** a scan job completes and there are M tracked markets (with open positions or unresolved predictions) among the fetched markets
- **THEN** M rows are inserted into the `price_snapshots` table with the current timestamp, one per tracked market

#### Scenario: Snapshot schema
- **WHEN** a price snapshot is recorded
- **THEN** it contains `market_id` (TEXT), `timestamp` (TEXT ISO-8601), `price_yes` (REAL), `price_no` (REAL), and `volume` (REAL)

### Requirement: Query price history for a market
The system SHALL provide a function to retrieve price snapshots for a given market, optionally filtered by time range. Results SHALL be ordered by timestamp ascending.

#### Scenario: Retrieve full history
- **WHEN** price history is requested for a market with no time filter
- **THEN** all snapshots for that market are returned in chronological order

#### Scenario: Retrieve windowed history
- **WHEN** price history is requested with a `since` timestamp
- **THEN** only snapshots on or after that timestamp are returned

### Requirement: Query latest prices for multiple markets
The system SHALL provide a function to retrieve the most recent price snapshot for each market in a given set of market IDs. This supports efficient portfolio mark-to-market.

#### Scenario: Latest prices for open positions
- **WHEN** latest prices are requested for market IDs ["A", "B", "C"]
- **THEN** the most recent snapshot for each market is returned as a dict mapping market_id to price_yes

### Requirement: Snapshot retention cleanup
The system SHALL periodically delete price snapshots older than a configurable retention period (default: 30 days). Cleanup SHALL run during the daily report job.

#### Scenario: Cleanup removes old snapshots
- **WHEN** the daily report job runs and snapshots exist older than the retention period
- **THEN** those snapshots are deleted and the count of deleted rows is logged

#### Scenario: Retention period is configurable
- **WHEN** `snapshot_retention_days` is set to 14 in configuration
- **THEN** snapshots older than 14 days are deleted during cleanup

### Requirement: Database schema for price snapshots
The system SHALL create a `price_snapshots` table via a schema migration (version 2). The table SHALL have a composite index on `(market_id, timestamp)` for efficient queries.

#### Scenario: Migration creates table
- **WHEN** the database is initialized or migrated from version 1
- **THEN** the `price_snapshots` table is created with columns: `id` (INTEGER PRIMARY KEY), `market_id` (TEXT NOT NULL REFERENCES markets(id)), `timestamp` (TEXT NOT NULL), `price_yes` (REAL), `price_no` (REAL), `volume` (REAL)
- **AND** an index `idx_snapshots_market_time` on `(market_id, timestamp)` is created
