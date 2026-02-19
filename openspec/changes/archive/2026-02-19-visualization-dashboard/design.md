## Context

The Polymarket trading agent stores all operational data in a SQLite database (`polymarket_agent.db`) using WAL journal mode. The agent is a Click CLI application (`polymarket` command) with an APScheduler loop that scans markets, runs LLM analysis, executes paper trades, tracks calibration, and manages risk. Currently, monitoring requires reading CLI output or querying the database manually.

The operator wants a web dashboard to visualize agent performance without modifying the core engine. The dashboard must be a separate package that can be iterated independently.

## Goals / Non-Goals

**Goals:**
- Provide visual monitoring of portfolio value, P&L, position health, calibration accuracy, and operational status
- Run as a separate process alongside the agent with zero coupling
- Read the SQLite database without any possibility of writing to it
- Handle schema variations gracefully (missing columns or tables from different migration versions)
- Work with empty data states (new databases with no trades yet)

**Non-Goals:**
- Real-time streaming (30-second polling is sufficient given agent job intervals of 15-60 minutes)
- Write operations (no trade execution, no kill switch toggling from the dashboard)
- Authentication or multi-user access control (single-operator tool on a local network)
- Historical data aggregation beyond what the agent already stores (no new tables)
- Mobile-optimized layout (desktop browser is the primary use case)

## Decisions

### D1: Standalone sibling package vs. submodule of polymarket_agent
**Decision**: Separate `src/polymarket_dashboard/` package with its own dependencies.
**Rationale**: Zero import coupling means the dashboard can never break the agent. Optional `[dashboard]` dependency group keeps the agent's install lean. The operator can `pip install -e .` without dashboard deps, or `pip install -e ".[dashboard]"` to include them.
**Alternative considered**: A module within `polymarket_agent` that reuses `get_db()`. Rejected because it would create import-time dependencies on FastAPI/uvicorn even when just running the agent CLI.

### D2: FastAPI over Flask
**Decision**: FastAPI with uvicorn.
**Rationale**: The project already uses Pydantic throughout; FastAPI's native Pydantic integration eliminates JSON serialization boilerplate. Async support via `aiosqlite` prevents blocking the event loop during database queries. Auto-generated Swagger docs at `/api/docs` aid development.
**Alternative considered**: Flask. Simpler but requires manual JSON serialization and would need threading or an async extension for non-blocking DB access.

### D3: aiosqlite with read-only URI mode
**Decision**: Open the database via `aiosqlite.connect(f"file:{path}?mode=ro", uri=True)` with `PRAGMA query_only=ON` and `PRAGMA busy_timeout=5000`.
**Rationale**: `mode=ro` makes write operations physically impossible at the SQLite level — not just by convention, but enforced by the engine. WAL mode (set by the agent) allows unlimited concurrent readers. `busy_timeout=5000` handles the rare case where a WAL checkpoint overlaps with a dashboard query.
**Alternative considered**: Reusing the agent's `get_db()` context manager. Rejected because it acquires read-write connections and would create an import dependency on `polymarket_agent.config`.

### D4: Single HTML file with CDN-loaded libraries
**Decision**: One `static/index.html` file using Pico CSS and Plotly.js from CDN. No build step, no npm, no bundler.
**Rationale**: Eliminates frontend toolchain complexity entirely. The dashboard is a monitoring tool, not a user-facing product — simplicity in deployment and maintenance outweighs bundle optimization. Plotly.js provides scatter plots, line charts, bar charts, and built-in zoom/range sliders suitable for all visualization needs.
**Alternative considered**: Chart.js (smaller bundle but lacks calibration curve support without plugins), React/Vue SPA (massive over-engineering for a monitoring dashboard).

### D5: Polling over WebSocket/SSE
**Decision**: 30-second `setInterval` polling from the frontend.
**Rationale**: The agent runs jobs every 15-60 minutes. Database state changes slowly. Polling every 30 seconds is more than adequate and avoids all connection management complexity. Only the active tab's data is fetched to minimize queries.
**Alternative considered**: Server-Sent Events. Would reduce unnecessary requests but adds reconnection logic and server-side state for negligible benefit.

### D6: Graceful schema handling via runtime detection
**Decision**: Check for table existence (`table_exists()`) and column existence (`PRAGMA table_info`) before querying optional schema elements.
**Rationale**: The agent's database may be at schema version 1 (no `price_snapshots` table) or version 2 (with `price_snapshots`). Similarly, `edge_at_prediction` and `threshold_at_prediction` columns may not exist. Runtime detection ensures the dashboard works with any schema version and degrades gracefully.

## Risks / Trade-offs

- **Calibration logic duplication**: The dashboard reimplements Brier score and bucket computation from `calibration.py`. If the agent's calibration formula changes, the dashboard may show different numbers. → Mitigated by the logic being straightforward arithmetic (~20 lines) that is unlikely to change frequently.

- **Mark-to-market accuracy**: The dashboard computes unrealized P&L using latest `price_snapshots` or `markets.last_price_yes` as fallback. These may be stale if the agent hasn't run a scan recently. → Acceptable: the dashboard displays data freshness via the "Last updated" timestamp.

- **CDN dependency for frontend**: Pico CSS and Plotly.js are loaded from CDN. No internet means no chart rendering. → Acceptable for the operator's LAN environment. Could be vendored later if needed.

- **No authentication**: The dashboard is accessible to anyone on the local network. → Acceptable for a single-operator setup on a home LAN (192.168.x.x). Out of scope per non-goals.

- **Starting balance hardcoded**: Total return % uses `PAPER_STARTING_BALANCE` env var (default 1000.0) rather than reading the agent's config. → Simple and avoids any config coupling. The operator sets this once.
