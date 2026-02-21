## 1. Backend — Data Router

- [x] 1.1 Create `src/polymarket_dashboard/routes/data.py` with `router = APIRouter()`
- [x] 1.2 Implement `GET /summary` — query bt_markets for total, has_history count, coverage_pct, date range, category count, volume min/max; return `{"available": false}` when DB missing
- [x] 1.3 Implement `GET /by-category` — GROUP BY COALESCE(category, 'unknown'), return list of {category, total, with_history} ordered by total DESC
- [x] 1.4 Implement `GET /by-volume-tier` — 5-tier CASE expression, return list of {tier, total, with_history}
- [x] 1.5 Implement `GET /temporal` — GROUP BY strftime('%Y-%m', end_date), also query bt_regimes; return {months: [{month, total, with_history}], regimes: [{name, start_date, end_date}]}
- [x] 1.6 Add soft-fail guard in each endpoint: check table exists via `await conn.table_exists("bt_markets")` before querying

## 2. Backend — Router Registration

- [x] 2.1 In `src/polymarket_dashboard/app.py`, import `from polymarket_dashboard.routes import data`
- [x] 2.2 Register router: `app.include_router(data.router, prefix="/api/data", tags=["data"])`

## 3. Frontend — Tab Structure

- [x] 3.1 Add `<button data-tab="data">Data</button>` to the nav `.tabs` div in `index.html`
- [x] 3.2 Add `<div id="tab-data" class="tab-content">` with inner layout: KPI grid div, two side-by-side chart containers (category + volume tier), full-width temporal chart container
- [x] 3.3 Add `case 'data': await refreshData(); break;` to the `refresh()` switch statement

## 4. Frontend — refreshData() Implementation

- [x] 4.1 Implement `async function refreshData()` — fetch `/data/summary` first; show empty state if `!data.available`
- [x] 4.2 Render 6 KPI cards: Total Markets, With History, Coverage %, Date Range, Categories, Volume Range — apply color class to Coverage % based on value (≥50% positive, 25–49% neutral, <25% negative)
- [x] 4.3 Fetch category, volume tier, and temporal data in parallel via `Promise.all()`
- [x] 4.4 Render category grouped bar chart with two traces: Total (gray `#64748b`) and With History (blue `#3b82f6`), `barmode: 'group'`, ordered by total DESC
- [x] 4.5 Render volume tier grouped bar chart with same two traces and color scheme, tiers ordered logically (`<$10K` → `>$10M`)
- [x] 4.6 Render temporal histogram: two bar traces (total gray, with_history blue) by month; add Plotly `shapes` for regime vertical bands using distinct muted colors with 0.15 opacity; add regime name annotations
- [x] 4.7 Add empty-state handling for each chart section (show message div if data is empty or unavailable)

## 5. Tests

- [x] 5.1 Test `GET /api/data/summary` returns expected keys with a test backtest.db fixture
- [x] 5.2 Test `GET /api/data/by-category` returns list with category, total, with_history fields
- [x] 5.3 Test `GET /api/data/by-volume-tier` returns all 5 tier labels
- [x] 5.4 Test `GET /api/data/temporal` returns months list and regimes list
- [x] 5.5 Test all endpoints return `{"available": false}` when backtest.db is missing
