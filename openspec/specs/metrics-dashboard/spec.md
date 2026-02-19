## Requirements

### Requirement: Metrics summary endpoint
The dashboard SHALL expose `GET /api/metrics/summary` returning aggregated metrics for a configurable period: total LLM calls, total LLM tokens (input and output), total estimated LLM cost, total API calls (by service), total API errors, and the period covered. The `days` query parameter (default 1, max 30) SHALL control the lookback window.

#### Scenario: Summary for today
- **WHEN** a client requests `/api/metrics/summary?days=1`
- **THEN** the response includes aggregated LLM and API metrics for the last 24 hours

#### Scenario: Summary for 30 days
- **WHEN** a client requests `/api/metrics/summary?days=30`
- **THEN** the response includes aggregated metrics for the full retention window

#### Scenario: No metric events exist
- **WHEN** the `metric_events` table does not exist or is empty
- **THEN** the response returns zero for all counters

### Requirement: Metrics time series endpoint
The dashboard SHALL expose `GET /api/metrics/timeseries` returning daily-bucketed metric aggregates: date, llm_calls, llm_input_tokens, llm_output_tokens, llm_cost, api_calls_gamma, api_calls_clob, api_calls_tavily, api_errors. The `days` query parameter (default 7, max 30) SHALL control the lookback window.

#### Scenario: Week of daily data
- **WHEN** a client requests `/api/metrics/timeseries?days=7`
- **THEN** the response includes up to 7 entries, one per day with activity, ordered chronologically

#### Scenario: Day with no activity
- **WHEN** a day within the requested range has no metric events
- **THEN** that day is omitted from the response (sparse representation)

### Requirement: Metrics cost breakdown endpoint
The dashboard SHALL expose `GET /api/metrics/cost-breakdown` returning LLM cost grouped by model for a configurable period: model name, call count, total input tokens, total output tokens, total cost. The `days` query parameter (default 7, max 30) SHALL control the lookback window.

#### Scenario: Multiple models used
- **WHEN** both Haiku and Sonnet calls exist in the period
- **THEN** the response includes separate entries for each model with independent totals

### Requirement: Storage metrics endpoint
The dashboard SHALL expose `GET /api/metrics/storage` returning current database size (via `PRAGMA page_count * page_size`), row counts for key tables (markets, predictions, positions, trades, price_snapshots, metric_events), and the metric_events retention window.

#### Scenario: Database with data
- **WHEN** the database has data across multiple tables
- **THEN** the response includes `db_size_bytes`, `db_size_mb` (rounded to 1 decimal), and a `tables` object with row counts per table

#### Scenario: Table does not exist
- **WHEN** a table (e.g., `price_snapshots` or `metric_events`) does not exist in the schema
- **THEN** its row count is returned as 0

### Requirement: Recent metric events endpoint
The dashboard SHALL expose `GET /api/metrics/recent` returning the most recent individual metric events. The `limit` query parameter (default 50, max 200) and optional `event_type` filter SHALL be supported.

#### Scenario: Fetch recent events
- **WHEN** a client requests `/api/metrics/recent?limit=20`
- **THEN** the response includes the 20 most recent metric events ordered by timestamp descending, with parsed JSON data fields

#### Scenario: Filter by event type
- **WHEN** a client requests `/api/metrics/recent?event_type=llm_call`
- **THEN** only `llm_call` events are returned

### Requirement: Costs & Ops dashboard tab
The dashboard frontend SHALL include a 5th tab labeled "Costs & Ops" displaying: (1) four KPI cards for LLM Cost Today, LLM Calls Today, API Calls Today, and DB Size; (2) a Plotly stacked area chart of daily LLM token usage (input vs output) with a cost overlay line; (3) a Plotly bar chart of API calls by service (Gamma, CLOB, Tavily) over time; (4) a cost breakdown donut chart by model; (5) an error rate line chart (24-hour rolling window); (6) a live event feed table showing recent metric events.

#### Scenario: Tab loads with data
- **WHEN** the user clicks the "Costs & Ops" tab and metric events exist
- **THEN** all charts render with data and KPI cards show today's aggregated values

#### Scenario: No metric events yet
- **WHEN** the metric_events table does not exist or is empty
- **THEN** KPI cards show zero values and charts display empty state messages

#### Scenario: Auto-refresh updates metrics
- **WHEN** 30 seconds elapse while the Costs & Ops tab is active
- **THEN** the metrics summary, timeseries, and recent events are re-fetched and charts are updated
