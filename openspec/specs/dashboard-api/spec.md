## Requirements

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

### Requirement: Portfolio summary endpoint
The dashboard SHALL expose `GET /api/portfolio/summary` returning a JSON object with current portfolio state including cash balance, mode, open position count, total position value (mark-to-market), total portfolio value, realized P&L, unrealized P&L, total return percentage, today's P&L, and kill switch status.

#### Scenario: Portfolio with open positions
- **WHEN** the portfolio has open positions and current price data is available
- **THEN** the response includes mark-to-market position values computed as `size * current_price` for YES positions and `size * (1 - current_price)` for NO positions

#### Scenario: Empty portfolio
- **WHEN** no portfolio record exists in the database
- **THEN** the response returns `cash_balance: 0.0`, `mode: "paper"`, and zero for all P&L fields

#### Scenario: Kill switch active
- **WHEN** the kill switch is active
- **THEN** `kill_switch_active` is `true` and `kill_switch_reason` contains the reason string

### Requirement: Equity curve endpoint
The dashboard SHALL expose `GET /api/portfolio/equity-curve` returning column-oriented arrays of daily P&L data: dates, portfolio_value, realized_pnl, unrealized_pnl, total_pnl, and trade_count, ordered chronologically.

#### Scenario: Multiple days of data
- **WHEN** the `daily_pnl` table contains multiple rows
- **THEN** the response includes all rows ordered by date ascending with matching array lengths

#### Scenario: No daily data yet
- **WHEN** the `daily_pnl` table is empty
- **THEN** the response returns empty arrays for all fields

### Requirement: Open positions endpoint
The dashboard SHALL expose `GET /api/positions/open` returning a list of open positions joined with market data and the latest prediction. Each position SHALL include: market question, category, side, size, entry price, current price, unrealized P&L, return percentage, agent estimate, edge remaining, confidence bounds, entry timestamp, and days held.

#### Scenario: Position with YES side
- **WHEN** a YES position exists with entry_price 0.45 and current_price 0.52, size 100
- **THEN** unrealized_pnl is `(0.52 - 0.45) * 100 = 7.00` and edge_remaining is `agent_estimate - current_price`

#### Scenario: Position with NO side
- **WHEN** a NO position exists with entry_price 0.40 and current market price (YES) is 0.70, size 100
- **THEN** unrealized_pnl is `((1 - 0.70) - 0.40) * 100 = -10.00` and edge_remaining is `current_price - agent_estimate`

#### Scenario: No predictions exist for a position
- **WHEN** an open position has no associated prediction record
- **THEN** `agent_estimate`, `edge_remaining`, `confidence_low`, and `confidence_high` are `null`

### Requirement: Closed positions endpoint
The dashboard SHALL expose `GET /api/positions/closed` accepting a `limit` query parameter (default 50, max 500) and returning closed positions ordered by exit timestamp descending, joined with market data.

#### Scenario: Fetch recent closed positions
- **WHEN** a client requests `/api/positions/closed?limit=10`
- **THEN** the response contains at most 10 closed positions ordered by most recent exit first

### Requirement: Trade history endpoint
The dashboard SHALL expose `GET /api/positions/trades` accepting `limit` (default 100, max 1000) and `offset` (default 0) query parameters, returning trades joined with market questions, ordered by timestamp descending.

#### Scenario: Paginated trade history
- **WHEN** a client requests `/api/positions/trades?limit=10&offset=20`
- **THEN** the response contains trades 21-30 (0-indexed) from the most recent trades

### Requirement: Price history endpoint
The dashboard SHALL expose `GET /api/positions/price-history/{market_id}` returning column-oriented arrays of price snapshot data: timestamps, price_yes, price_no, and volume.

#### Scenario: Market with price snapshots
- **WHEN** price snapshots exist for the requested market_id
- **THEN** the response includes all snapshots ordered chronologically

#### Scenario: No price_snapshots table
- **WHEN** the database is at schema version 1 (no price_snapshots table)
- **THEN** the response returns empty arrays

### Requirement: Calibration report endpoint
The dashboard SHALL expose `GET /api/calibration/report` returning Brier score (agent and market), calibration buckets (10 buckets from 0.0-1.0 with avg_predicted, actual_rate, calibration_error, count), and category breakdown with per-category Brier scores.

#### Scenario: Sufficient resolved predictions
- **WHEN** 2 or more resolved predictions exist
- **THEN** the response includes computed brier_score, market_brier_score, non-empty buckets array, and category_breakdown

#### Scenario: Insufficient resolved predictions
- **WHEN** fewer than 2 resolved predictions exist
- **THEN** brier_score and market_brier_score are `null` and buckets and category_breakdown are empty arrays

### Requirement: Calibration scatter endpoint
The dashboard SHALL expose `GET /api/calibration/scatter` returning individual resolved predictions with agent_estimate, outcome, market_price, category, market_id, and timestamp, ordered chronologically.

#### Scenario: Resolved predictions exist
- **WHEN** resolved predictions exist in the database
- **THEN** each prediction in the response includes agent_estimate, outcome (0 or 1), market_price, and category

### Requirement: Operations status endpoint
The dashboard SHALL expose `GET /api/operations/status` returning active market count, total market count, categories tracked, kill switch state, pending prediction count, open order count, and recent daily activity (last 30 days).

#### Scenario: Active agent with data
- **WHEN** the agent has indexed markets and made predictions
- **THEN** the response includes non-zero counts and a recent_activity array with date, trades, pnl, and portfolio_value per day

### Requirement: Recent predictions endpoint
The dashboard SHALL expose `GET /api/operations/predictions` accepting a `limit` query parameter (default 20, max 200) and returning recent predictions joined with market data, including timestamp, market question, category, agent estimate, final estimate, market price, confidence bounds, edge, threshold, thesis, resolution status, and outcome.

#### Scenario: Predictions with edge data
- **WHEN** the predictions table includes edge_at_prediction columns
- **THEN** the response includes edge and threshold values for each prediction

#### Scenario: Predictions without edge columns
- **WHEN** the predictions table lacks edge_at_prediction columns
- **THEN** the response includes `null` for edge and threshold fields

### Requirement: Application entrypoint
The dashboard SHALL be launchable via `polymarket-dashboard` CLI command accepting `--db` (database path), `--host` (default 0.0.0.0), and `--port` (default 8050) arguments. The `DASHBOARD_DB_PATH` and `PAPER_STARTING_BALANCE` environment variables SHALL be supported for configuration.

#### Scenario: Launch with explicit database path
- **WHEN** the operator runs `polymarket-dashboard --db ./polymarket_agent.db --port 8050`
- **THEN** the server starts on port 8050 serving the dashboard and API

#### Scenario: Launch with environment variable
- **WHEN** `DASHBOARD_DB_PATH` is set and no `--db` flag is provided
- **THEN** the server uses the environment variable path

### Requirement: Metrics route module registration
The dashboard app SHALL include a metrics route module registered at the `/api/metrics` prefix, serving all metrics-related endpoints. The route module SHALL gracefully handle databases where the `metric_events` table does not exist by returning zero/empty responses.

#### Scenario: Metrics routes available
- **WHEN** the dashboard starts
- **THEN** all `/api/metrics/*` endpoints are registered and accessible

#### Scenario: Database without metric_events table
- **WHEN** the database was created before schema v3 and has no `metric_events` table
- **THEN** all metrics endpoints return valid empty/zero responses without errors

### Requirement: Swagger API documentation
The dashboard SHALL serve auto-generated Swagger/OpenAPI documentation at `/api/docs`.

#### Scenario: Access API docs
- **WHEN** a browser navigates to `/api/docs`
- **THEN** an interactive Swagger UI is displayed listing all API endpoints
