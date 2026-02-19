## 1. Package Setup

- [x] 1.1 Create `src/polymarket_dashboard/` package with `__init__.py` and `routes/__init__.py`
- [x] 1.2 Add `[project.optional-dependencies]` dashboard group to `pyproject.toml` (fastapi, uvicorn, aiosqlite)
- [x] 1.3 Add `polymarket-dashboard` script entrypoint and update hatch wheel packages list in `pyproject.toml`
- [x] 1.4 Install with `uv pip install -e ".[dashboard]"` and verify import works

## 2. Database Access Layer

- [x] 2.1 Implement `db.py` with `DashboardDB` class using `mode=ro` URI and `_Connection` wrapper with `execute_fetchone`, `execute_fetchall`, and `table_exists` helpers
- [x] 2.2 Verify read-only mode prevents writes and handles missing database file

## 3. Application Factory

- [x] 3.1 Implement `app.py` with `create_app()` factory mounting all route modules under `/api/` prefixes and static files at root
- [x] 3.2 Implement `main()` entrypoint with argparse for `--db`, `--host`, `--port` and environment variable support (`DASHBOARD_DB_PATH`, `PAPER_STARTING_BALANCE`)

## 4. Portfolio Routes

- [x] 4.1 Implement `GET /api/portfolio/summary` with mark-to-market computation (YES/NO side handling), realized/unrealized P&L, kill switch status, and total return percentage
- [x] 4.2 Implement `GET /api/portfolio/equity-curve` returning column-oriented daily P&L arrays
- [x] 4.3 Handle missing `price_snapshots` table by falling back to `markets.last_price_yes`

## 5. Positions Routes

- [x] 5.1 Implement `GET /api/positions/open` with joined markets + latest prediction, snapshot price lookup, unrealized P&L, edge remaining, and days held computation
- [x] 5.2 Implement `GET /api/positions/closed` with limit parameter and joined market data
- [x] 5.3 Implement `GET /api/positions/trades` with limit/offset pagination and joined market questions
- [x] 5.4 Implement `GET /api/positions/price-history/{market_id}` with table existence check

## 6. Calibration Routes

- [x] 6.1 Implement `GET /api/calibration/report` with Brier score computation, 10-bucket calibration analysis, agent vs market comparison, and category breakdown
- [x] 6.2 Implement `GET /api/calibration/scatter` returning individual resolved predictions with category

## 7. Operations Routes

- [x] 7.1 Implement `GET /api/operations/status` with market counts, categories, kill switch state, pending predictions, open orders, and 30-day activity
- [x] 7.2 Implement `GET /api/operations/predictions` with runtime column detection for `edge_at_prediction`/`threshold_at_prediction`

## 8. Frontend Dashboard

- [x] 8.1 Create `static/index.html` with dark theme (Pico CSS CDN), Plotly.js CDN, and tab navigation structure
- [x] 8.2 Implement Portfolio tab: 4 KPI cards (portfolio value, cash, return %, today P&L), equity curve line chart with range slider, daily P&L bar chart (green/red)
- [x] 8.3 Implement Positions tab: open positions table with color-coded P&L, expandable inline price charts, closed positions table, trades table in 2-column layout
- [x] 8.4 Implement Calibration tab: KPI cards (Brier scores, comparison, prediction counts), calibration curve scatter with reference line, predictions scatter colored by category, category bar chart
- [x] 8.5 Implement Operations tab: KPI cards (markets, categories, predictions, kill switch), predictions table with thesis hover, trade count bar chart
- [x] 8.6 Implement kill switch status badge in nav bar (green/red with pulse animation)
- [x] 8.7 Implement 30-second auto-refresh polling active tab only, with "Last updated" timestamp display
- [x] 8.8 Implement empty-state messages for all components when no data available

## 9. Verification

- [x] 9.1 Verify all 10 API endpoints return valid JSON (including empty-data cases)
- [x] 9.2 Verify dashboard HTML loads and Swagger docs accessible at `/api/docs`
- [x] 9.3 Verify existing `polymarket` CLI commands still work unchanged
- [x] 9.4 Verify dashboard works with both schema version 1 and version 2 databases
