## Why

The agent makes hundreds of LLM calls, API requests (Gamma, CLOB, Tavily), and database writes per day — but none of this operational data is persisted. Token usage, cost estimates, API latencies, and error rates exist only in transient log lines and in-memory counters that reset on every restart. Without persistent metrics, there's no way to answer basic operational questions: How much are we spending on LLM calls? What's our API error rate? How fast is the database growing?

## What Changes

- Add a lightweight metrics recorder module to the agent that persists operational events (LLM calls, API requests, errors) to a new `metric_events` SQLite table
- Instrument 5 existing modules with 2-3 lines each to record events: `llm_client.py`, `gamma_client.py`, `clob_client.py`, `web_search.py`, `scheduler.py`
- Add schema migration v3 for the `metric_events` table
- Add 30-day retention cleanup alongside existing snapshot cleanup in the daily report job
- Add new dashboard API endpoints to query and aggregate metric events
- Add a new "Costs & Ops" tab to the dashboard frontend displaying LLM costs, API call volumes, error rates, and storage growth

## Capabilities

### New Capabilities
- `metrics-recorder`: Agent-side metrics persistence — the `metric_events` table, the recorder module, and instrumentation of existing call sites
- `metrics-dashboard`: Dashboard API endpoints and frontend tab for viewing operational metrics, costs, and system health

### Modified Capabilities
- `dashboard-api`: Adding new `/api/metrics/*` endpoints for querying metric events
- `dashboard-ui`: Adding a 5th "Costs & Ops" tab to the frontend

## Impact

- **Agent code**: 6 files touched (1 new module + 5 existing with minimal additions). All changes are additive — no behavioral changes to existing logic.
- **Database schema**: Migration v3 adds `metric_events` table. Fully backward-compatible.
- **Dashboard code**: New route module + frontend tab additions. No changes to existing dashboard endpoints.
- **Dependencies**: None new. Uses existing `sqlite3`, `json`, `time` stdlib modules.
- **Storage**: `metric_events` table grows ~500-2000 rows/day depending on activity. 30-day retention keeps it bounded.
