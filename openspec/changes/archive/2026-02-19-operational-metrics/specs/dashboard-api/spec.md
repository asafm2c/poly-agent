## ADDED Requirements

### Requirement: Metrics route module registration
The dashboard app SHALL include a metrics route module registered at the `/api/metrics` prefix, serving all metrics-related endpoints. The route module SHALL gracefully handle databases where the `metric_events` table does not exist by returning zero/empty responses.

#### Scenario: Metrics routes available
- **WHEN** the dashboard starts
- **THEN** all `/api/metrics/*` endpoints are registered and accessible

#### Scenario: Database without metric_events table
- **WHEN** the database was created before schema v3 and has no `metric_events` table
- **THEN** all metrics endpoints return valid empty/zero responses without errors

## MODIFIED Requirements

### Requirement: Read-only database access layer
The dashboard SHALL open the agent's SQLite database in read-only mode using the `file:{path}?mode=ro` URI parameter. The connection SHALL set `PRAGMA query_only=ON` and `PRAGMA busy_timeout=5000`. The dashboard SHALL NOT import any module from `polymarket_agent`. The `_Connection` wrapper SHALL support executing `PRAGMA` statements that return scalar values for storage metrics queries.

#### Scenario: Database opened in read-only mode
- **WHEN** the dashboard establishes a database connection
- **THEN** the connection uses `mode=ro` URI parameter and `PRAGMA query_only=ON`, making writes physically impossible

#### Scenario: Missing database file
- **WHEN** the configured database path does not exist
- **THEN** a `FileNotFoundError` is raised at startup with a descriptive message

#### Scenario: Schema version 1 database (no price_snapshots)
- **WHEN** the database is at schema version 1 (missing `price_snapshots` table)
- **THEN** all endpoints return valid responses, using `markets.last_price_yes` for current prices instead of snapshot data

#### Scenario: Missing optional columns
- **WHEN** the `predictions` table lacks `edge_at_prediction` or `threshold_at_prediction` columns
- **THEN** the predictions endpoint returns `null` for those fields instead of erroring

#### Scenario: PRAGMA queries for storage metrics
- **WHEN** the dashboard queries `PRAGMA page_count` or `PRAGMA page_size`
- **THEN** the scalar values are returned correctly through the read-only connection
