## 1. Schema & Metrics Module

- [x] 1.1 Add migration v3 to `database.py` — `metric_events` table with `id`, `timestamp`, `event_type`, `data` columns and index on `(event_type, timestamp)`
- [x] 1.2 Create `src/polymarket_agent/metrics.py` — module-level `record(event_type, **data)` function that inserts into `metric_events`, silently catches errors
- [x] 1.3 Add `cleanup_old_metrics(retention_days)` function to `metrics.py` — deletes events older than cutoff, returns count

## 2. Agent Instrumentation

- [x] 2.1 Instrument `llm_client.py` — record `llm_call` event after each successful call (model, input_tokens, output_tokens, cost, latency_ms) and `api_error` on rate limit / API errors
- [x] 2.2 Instrument `gamma_client.py` — record `api_call` event for each HTTP request (service="gamma", endpoint, status, latency_ms) and `api_error` on failures
- [x] 2.3 Instrument `clob_client.py` — record `api_call` event for each HTTP request (service="clob", endpoint, status, latency_ms) and `api_error` on failures
- [x] 2.4 Instrument `web_search.py` — record `api_call` event for each search (service="tavily", endpoint="search", status, latency_ms) and `api_error` on failures
- [x] 2.5 Add `cleanup_old_metrics()` call to `scheduler.py` `_daily_report_job` alongside existing snapshot cleanup

## 3. Dashboard API Endpoints

- [x] 3.1 Create `src/polymarket_dashboard/routes/metrics.py` with router at `/api/metrics` prefix
- [x] 3.2 Implement `GET /api/metrics/summary` — aggregated LLM calls, tokens, cost, API calls by service for configurable day window
- [x] 3.3 Implement `GET /api/metrics/timeseries` — daily-bucketed aggregates for charting
- [x] 3.4 Implement `GET /api/metrics/cost-breakdown` — LLM cost grouped by model
- [x] 3.5 Implement `GET /api/metrics/storage` — DB size via PRAGMAs, row counts per table
- [x] 3.6 Implement `GET /api/metrics/recent` — recent individual events with optional type filter
- [x] 3.7 Register metrics router in `app.py`

## 4. Dashboard Frontend

- [x] 4.1 Add "Costs & Ops" tab button to navigation bar in `index.html`
- [x] 4.2 Add Costs & Ops tab content container with KPI cards (LLM Cost Today, LLM Calls Today, API Calls Today, DB Size)
- [x] 4.3 Add LLM token usage stacked area chart with cost overlay line
- [x] 4.4 Add API calls by service bar chart (Gamma, CLOB, Tavily over time)
- [x] 4.5 Add cost breakdown donut chart by model
- [x] 4.6 Add error rate line chart
- [x] 4.7 Add live metric event feed table
- [x] 4.8 Wire auto-refresh for Costs & Ops tab (fetch on tab switch + 30s interval)

## 5. Integration & Verification

- [x] 5.1 Verify migration v3 applies cleanly on existing v2 database
- [x] 5.2 Verify dashboard starts and Costs & Ops tab renders with empty metric_events table
- [x] 5.3 Verify all `/api/metrics/*` endpoints return valid JSON
- [x] 5.4 Verify existing dashboard tabs and agent CLI commands still work unchanged
