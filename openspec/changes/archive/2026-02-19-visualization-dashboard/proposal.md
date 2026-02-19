## Why

The trading agent accumulates rich operational data (portfolio state, positions, trades, predictions, calibration metrics, risk status) in SQLite but provides no visual way to monitor it. Operators must rely on CLI output and log files to understand agent performance, position health, and calibration accuracy. A web dashboard enables at-a-glance operational awareness without interrupting or modifying the core trading engine.

## What Changes

- Add a standalone FastAPI web server (`polymarket_dashboard`) as a sibling package that reads the agent's SQLite database in read-only mode
- Serve a single-page dark-mode dashboard with 4 tabs: Portfolio, Positions, Calibration, Operations
- Expose 10 JSON API endpoints for portfolio summary, equity curve, open/closed positions, trade history, price history, calibration report, calibration scatter data, operations status, and recent predictions
- Add optional `[dashboard]` dependency group (fastapi, uvicorn, aiosqlite) that does not affect the core agent installation
- Add `polymarket-dashboard` CLI entrypoint for launching the web server

## Capabilities

### New Capabilities
- `dashboard-api`: Read-only FastAPI backend serving portfolio, positions, calibration, and operations data from the agent's SQLite database
- `dashboard-ui`: Single-page web frontend with Plotly.js charts, auto-refresh, and 4-tab layout for monitoring agent operations

### Modified Capabilities

_None. The dashboard is fully decoupled — zero imports from `polymarket_agent`, no schema changes, no modifications to any existing capability._

## Impact

- **New package**: `src/polymarket_dashboard/` with routes, db access layer, and static HTML
- **pyproject.toml**: New `[project.optional-dependencies]` group, new script entrypoint, updated hatch wheel packages list
- **Dependencies**: 3 new optional packages (fastapi, uvicorn, aiosqlite) — only installed with `pip install -e ".[dashboard]"`
- **Database**: Read-only access via `mode=ro` URI parameter; WAL mode ensures no contention with the agent writer
- **No changes** to any existing `polymarket_agent` source files
