## 1. BacktestDB Layer

- [x] 1.1 Add `BacktestDB` class to `db.py` with soft `create()` classmethod
- [x] 1.2 Verify `_Connection.table_exists()` works for forward-compat guards

## 2. App Registration

- [x] 2.1 Add `backtest_db_path` parameter to `create_app()`
- [x] 2.2 Store `BacktestDB.create()` on `app.state.backtest_db`
- [x] 2.3 Register evaluation and hypotheses routers, add `--backtest-db` CLI arg

## 3. Evaluation API

- [x] 3.1 Create `routes/evaluation.py` with None guard pattern
- [x] 3.2 `GET /runs` — simulation runs listing with summary stats
- [x] 3.3 `GET /trials/{run_id}` — per-trial detail with sort and filter
- [x] 3.4 `GET /by-category/{run_id}` — Brier scores by category
- [x] 3.5 `GET /by-volume-tier/{run_id}` — Brier scores by volume tier
- [x] 3.6 `GET /temporal/{run_id}` — rolling Brier diff with regime markers (with table_exists guard)
- [x] 3.7 `GET /compare` — cross-run comparison

## 4. Hypotheses API

- [x] 4.1 Create `routes/hypotheses.py` with double-guard pattern (None + table_exists)
- [x] 4.2 `GET /list` with status filter and evidence counts
- [x] 4.3 `GET /{id}/evidence` with run joins
- [x] 4.4 `GET /{id}/actions`

## 5. Frontend — Evaluation Tab

- [x] 5.1 Add Evaluation tab button to nav
- [x] 5.2 Add Evaluation tab content div with run selector, KPIs, charts, drill-down
- [x] 5.3 Add CSS for badges, filters, search input, run selector
- [x] 5.4 Implement `refreshEvaluation()` with parallel API fetches
- [x] 5.5 KPI summary strip (6 compact cards)
- [x] 5.6 Model comparison grouped bar chart
- [x] 5.7 Category breakdown bar chart
- [x] 5.8 Volume tier bar chart
- [x] 5.9 Temporal line chart with regime boundary markers
- [x] 5.10 Drill-down table with search filtering via `renderEvalTrials()`
- [x] 5.11 Auto-refresh integration (evaluation case in switch)

## 6. Frontend — Hypotheses Tab

- [x] 6.1 Add Hypotheses tab button to nav
- [x] 6.2 Add Hypotheses tab content div with filter bar, list, detail panel
- [x] 6.3 Status filter buttons with `filterHypotheses()` handler
- [x] 6.4 Hypothesis list table with status badges via `renderHypotheses()`
- [x] 6.5 Detail panel with `showHypDetail()` — KPIs, evidence table, actions table
- [x] 6.6 Close handler via `closeHypDetail()`
- [x] 6.7 `refreshHypotheses()` and auto-refresh integration

## 7. Tests

- [x] 7.1 Test BacktestDB.create() returns None for missing file
- [x] 7.2 Test evaluation API endpoints with test backtest.db fixture
- [x] 7.3 Test hypotheses API endpoints (graceful degradation when no tables)
- [x] 7.4 Test app creation with new routers
- [x] 7.5 Smoke test for dashboard serving static files with new tabs
