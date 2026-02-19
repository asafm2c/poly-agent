## Context

The Polymarket trading agent makes hundreds of LLM calls and API requests per day across 4 external services (Anthropic, Gamma, CLOB, Tavily). The `LLMClient` already tracks token counts and cost in-memory (`total_input_tokens`, `total_output_tokens`, `total_cost`, `call_count`) but these reset on every process restart. External HTTP clients (`GammaClient`, `ClobClient`, `WebSearcher`) have zero instrumentation. The existing dashboard reads the agent's SQLite database in read-only mode and displays portfolio/trading data across 4 tabs.

## Goals / Non-Goals

**Goals:**
- Persist individual operational events (LLM calls, API requests, errors) to the agent's SQLite database
- Enable the dashboard to display cost trends, API call volumes, error rates, and storage metrics
- Keep the instrumentation surface minimal — 2-3 lines added per call site
- Maintain 30-day retention with automatic cleanup

**Non-Goals:**
- Real-time streaming metrics (polling every 30s is sufficient)
- Distributed tracing / correlation IDs across calls
- Alerting or threshold-based notifications
- Tracking network-level metrics (TCP connections, DNS, TLS)
- Modifying the Anthropic SDK or patching httpx globally

## Decisions

### 1. Single `metric_events` table with JSON data column

Store all event types in one table with a `data` JSON column rather than separate tables per metric type.

**Rationale:** One migration, one cleanup query, one index strategy. SQLite's JSON1 extension (`json_extract`) handles typed queries efficiently. New event types can be added without schema changes.

**Alternative considered:** Separate tables (`llm_calls`, `api_calls`, `errors`) — rejected because it multiplies migration, cleanup, and query complexity for marginal benefit. The dashboard aggregates across types anyway.

### 2. Synchronous, fire-and-forget recording via module-level function

Expose `metrics.record(event_type, **data)` as a module-level function. It writes synchronously to SQLite (which is fast for single-row inserts, ~0.05ms). No background thread, no queue.

**Rationale:** The agent already does synchronous SQLite writes throughout (positions, trades, predictions). Adding one more INSERT per operation is negligible. The simplicity of a direct write avoids failure modes of async queues.

**Alternative considered:** Background thread with batched writes — rejected because the overhead of a dedicated thread outweighs the benefit for ~50-200 events/day, and adds shutdown/crash edge cases.

### 3. Instrument at the client level, not via middleware/monkey-patching

Add explicit `metrics.record()` calls inside each client class (`LLMClient.complete`, `GammaClient.fetch_markets`, etc.) rather than wrapping httpx with transport hooks or decorating methods.

**Rationale:** Explicit > implicit. Each instrumentation point is visible, greppable, and removable. The agent uses 4 different HTTP patterns (Anthropic SDK, httpx.Client, TavilyClient, py-clob-client) so a unified middleware doesn't exist.

**Alternative considered:** httpx transport hook or context manager wrapper — rejected because it only covers 2 of 4 clients and hides the recording logic.

### 4. Dashboard computes DB size on-the-fly via PRAGMAs

Storage metrics (DB file size, table row counts) are computed at query time using `PRAGMA page_count * page_size` and `SELECT COUNT(*)` rather than recording them as metric events.

**Rationale:** These are point-in-time values, not events. Computing them on-the-fly avoids redundant storage. SQLite PRAGMAs are O(1) and `COUNT(*)` is fast on small tables.

### 5. Schema migration v3 added to existing migration array

The `metric_events` table is added as `MIGRATIONS[2]` (version 3) in `database.py`, following the same pattern as the v2 price_snapshots migration.

**Rationale:** Consistent with existing migration infrastructure. Auto-applied on next agent startup via `migrate()`.

### 6. Retention handled by existing daily cleanup job

The scheduler's `_daily_report_job` already calls `cleanup_old_snapshots()`. We add a `cleanup_old_metrics()` call alongside it with configurable retention (default 30 days).

## Risks / Trade-offs

- **[Risk] Metric writes slow down hot paths** → Mitigation: Single INSERT is ~0.05ms in WAL mode. Measured against 200ms+ LLM calls and 300ms+ HTTP requests, this is noise.
- **[Risk] metric_events table grows unbounded if cleanup fails** → Mitigation: 30-day retention cleanup runs daily alongside existing snapshot cleanup. Index on `timestamp` makes DELETE efficient.
- **[Risk] JSON data column makes typed queries harder** → Mitigation: SQLite JSON1 is well-supported. Dashboard queries use `json_extract()` which is indexed-friendly. For the expected query patterns (aggregate by event_type, filter by date), this is efficient.
- **[Trade-off] No per-market LLM cost attribution** → We record the market_id context where available (in the scheduler, not in the LLM client itself), keeping the LLM client unaware of business logic. Per-market attribution can be added later by correlating timestamps.
