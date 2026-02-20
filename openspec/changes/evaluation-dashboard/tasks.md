## 1. BacktestDB Layer

- [ ] 1.1 Add `BacktestDB` class to `src/polymarket_dashboard/db.py` with soft `create()` classmethod that returns `None` when the file is missing (no `FileNotFoundError`). Uses `mode=ro` URI, `aiosqlite.Row` row factory, `PRAGMA query_only=ON`, `PRAGMA busy_timeout=5000`, and reuses the existing `_Connection` wrapper. **Spec: `dashboard-db`**
- [ ] 1.2 Verify `_Connection.table_exists()` already exists and works for forward-compat guards on `bt_hypotheses`, `bt_hypothesis_evidence`, `bt_hypothesis_actions` tables. No new code needed — confirm the existing helper is sufficient. **Spec: `dashboard-db`**

## 2. App Registration

- [ ] 2.1 Add `backtest_db_path: Path | None = None` parameter to `create_app()` in `src/polymarket_dashboard/app.py`. Default to `Path(os.environ.get("BACKTEST_DB_PATH", "backtest.db"))`. Store `BacktestDB.create(bt_path)` on `app.state.backtest_db`. **Spec: `dashboard-app`**
- [ ] 2.2 Import and register `evaluation.router` at `/api/evaluation` and `hypotheses.router` at `/api/hypotheses` in `create_app()`. Keep the static file mount last (catch-all). **Files: `src/polymarket_dashboard/app.py`** **Spec: `dashboard-app`**
- [ ] 2.3 Add `--backtest-db` CLI argument to `main()` in `app.py` and pass it to `create_app(backtest_db_path=args.backtest_db)`. **Spec: `dashboard-app`**

## 3. Evaluation API

- [ ] 3.1 Create `src/polymarket_dashboard/routes/evaluation.py` with `router = APIRouter()` and the route-level None guard pattern: every endpoint starts by checking `request.app.state.backtest_db` and returns `{"available": False, ...empty...}` when `None`. **Spec: `evaluation-api`**
- [ ] 3.2 Implement `GET /runs` — list all simulation runs with summary stats. JOIN `bt_simulation_runs` with `bt_simulation_trials`, compute `trial_count`, `valid_trials`, `avg_agent_brier`, `avg_market_brier`, `brier_diff`, `wins`, `trade_count`, `win_rate`. Return `{"runs": [...], "available": true}`. **Spec: `evaluation-api`**
- [ ] 3.3 Implement `GET /trials/{run_id}` — per-trial detail joined with `bt_markets`. Accept `sort_by` (allowlist: `brier_diff`, `agent_brier`, `volume`, `category`, `market_id`) and `sort_dir` (`asc`/`desc`) query params. Compute `volume_tier` via SQL CASE. Validate sort column against allowlist to prevent injection. Return `{"run_id": N, "trials": [...], "count": N}`. **Spec: `evaluation-api`**
- [ ] 3.4 Implement `GET /by-category/{run_id}` — Brier scores grouped by `COALESCE(m.category, '(null)')`. Return `{"run_id": N, "categories": [...]}` with `trial_count`, `agent_brier`, `market_brier`, `brier_diff`, `simulated_pnl` per category. **Spec: `evaluation-api`**
- [ ] 3.5 Implement `GET /by-volume-tier/{run_id}` — Brier scores grouped by volume tier (SQL CASE: `10K-100K`, `100K-1M`, `1M-10M`, `>10M`). Order tiers logically. Return `{"run_id": N, "tiers": [...]}`. **Spec: `evaluation-api`**
- [ ] 3.6 Implement `GET /temporal/{run_id}` — trials ordered by `m.end_date ASC` with `agent_brier IS NOT NULL` filter. Compute `rolling_brier_diff` server-side as cumulative moving average. Fetch regime boundaries from `bt_regimes` (guard with `table_exists`). Return `{"run_id": N, "trials": [...with rolling_brier_diff...], "regimes": [...]}`. **Spec: `evaluation-api`**
- [ ] 3.7 Implement `GET /compare` — cross-run comparison. Accept optional `category` and `volume_tier` query params, conditionally append WHERE clauses. Extract model and horizon from `json_extract(r.config, ...)`. Return `{"runs": [...]}` with `run_id`, `started_at`, `model`, `horizon`, `trial_count`, `agent_brier`, `market_brier`, `brier_diff`. **Spec: `evaluation-api`**

## 4. Hypotheses API

- [ ] 4.1 Create `src/polymarket_dashboard/routes/hypotheses.py` with `router = APIRouter()`. Every endpoint double-guards: check `backtest_db is None` (return `{"available": False}`) AND check `table_exists("bt_hypotheses")` (return `{"available": True, "tables_exist": False}`). **Spec: `hypotheses-api`**
- [ ] 4.2 Implement `GET /list` — all hypotheses with LEFT JOIN on `bt_hypothesis_evidence` for `evidence_count` and `last_evidence_at`. Accept optional `status` query param filter. Return `{"hypotheses": [...], "available": true, "tables_exist": true}`. **Spec: `hypotheses-api`**
- [ ] 4.3 Implement `GET /{id}/evidence` — evidence records for a hypothesis with LEFT JOIN on `bt_simulation_runs` for run context (`run_started_at`, `run_agent_brier`, `run_market_brier`). Order by `e.created_at DESC`. Return `{"hypothesis_id": N, "evidence": [...]}`. **Spec: `hypotheses-api`**
- [ ] 4.4 Implement `GET /{id}/actions` — actions for a hypothesis from `bt_hypothesis_actions`, ordered by `a.created_at DESC`. Return `{"hypothesis_id": N, "actions": [...]}`. **Spec: `hypotheses-api`**

## 5. Frontend — Evaluation Tab

- [ ] 5.1 Add `<button data-tab="evaluation">Evaluation</button>` to the `.tabs` div in `src/polymarket_dashboard/static/index.html`, after the "Costs & Ops" button. Existing tab-switching JS handles it automatically. **Spec: `dashboard-static`, `evaluation-frontend`**
- [ ] 5.2 Add `<div id="tab-evaluation" class="tab-content">` content div inside `<main>`, after the costs tab div. Include: run selector `<select>`, KPI grid `#eval-kpis`, 2x2 chart grid (`#eval-model-chart`, `#eval-category-heatmap`, `#eval-volume-chart`, `#eval-temporal-chart`), drill-down section with filter badge, clear button, search input, and table div `#eval-drilldown-table`. **Spec: `evaluation-frontend`**
- [ ] 5.3 Add CSS for `#eval-run-select` (dark background, border, colors), `#eval-search` input, `.eval-clickable`, sortable table headers (`.data-table th.sortable` with cursor, hover, `::after` arrows, `.sort-asc`/`.sort-desc` variants). **Spec: `evaluation-frontend`**
- [ ] 5.4 Add JS state variables: `evalRunId`, `evalTrials`, `evalFilter = {category: null, volume_tier: null}`, `evalSortCol`, `evalSortDir`. Add `clearEvalFilter()` function. **Spec: `evaluation-frontend`**
- [ ] 5.5 Implement `refreshEvaluation()` — fetch `/evaluation/runs`, handle `available: false` and empty runs with distinct empty-state messages. Populate run selector dropdown, preserve current selection on re-render. Fetch all run-specific data in parallel via `Promise.all` (`trials`, `by-category`, `by-volume-tier`, `temporal`, `compare`). Call render functions. Wire `select.onchange`. **Spec: `evaluation-frontend`**
- [ ] 5.6 Implement `renderEvalKPIs(run)` — 6 compact KPI cards using existing `kpiCard()` helper: Agent Brier, Market Brier, Brier Diff (with positive/negative/neutral class and label), Trials (`valid/total` with trade count sub), Win Rate, LLM Cost (with per-trial sub). **Spec: `evaluation-frontend`**
- [ ] 5.7 Implement `renderModelComparison(data)` — grouped bar chart (`barmode: 'group'`) with Agent (blue `#3b82f6`) and Market (slate `#475569`) bars per run. Annotations show `n=X` trial counts. Uses `PLOTLY_DARK` layout and `PLOTLY_CONFIG`. **Spec: `evaluation-frontend`**
- [ ] 5.8 Implement `renderCategoryHeatmap(data)` — single-row Plotly heatmap with diverging colorscale (green `#22c55e` at 0 through dark slate `#1e293b` at 0.5 to red `#ef4444` at 1, `zmid: 0`). Cell text shows `n=` and diff. Attach `plotly_click` handler to set `evalFilter.category` and re-render drill-down. **Spec: `evaluation-frontend`**
- [ ] 5.9 Implement `renderVolumeTier(data)` — bar chart with tier labels in logical order (`10K-100K`, `100K-1M`, `1M-10M`, `>10M`). Per-bar conditional coloring (green/red/muted). Trial count annotations. Dashed zero line. Attach `plotly_click` handler to set `evalFilter.volume_tier`. **Spec: `evaluation-frontend`**
- [ ] 5.10 Implement `renderTemporal(data)` — two-trace scatter: rolling Brier diff (lines+markers, blue) and per-trial diff (markers only, muted 50% opacity). Regime boundaries as vertical dashed lines via `shapes`. Regime labels as rotated annotations. Emphasized zero line. **Spec: `evaluation-frontend`**
- [ ] 5.11 Implement `renderEvalDrilldown()` — client-side filtering from `evalTrials` by `evalFilter.category`, `evalFilter.volume_tier`, and `#eval-search` text input. Render sortable table with columns: Market, Category, Vol Tier, Estimate, Mkt Price, Outcome, Agent Brier, Mkt Brier, Diff (color-coded), Edge, Cost. Attach click handlers on `.sortable` headers. **Spec: `evaluation-frontend`**
- [ ] 5.12 Implement `sortEvalTable(col)` — toggle sort direction on repeated clicks, sort `evalTrials` in place (null-safe, string vs numeric), re-render. Wire `#eval-search` input event to trigger `renderEvalDrilldown()`. **Spec: `evaluation-frontend`**
- [ ] 5.13 Add `case 'evaluation': await refreshEvaluation(); break;` to the `refresh()` switch statement. **Spec: `evaluation-frontend`**

## 6. Frontend — Hypotheses Tab

- [ ] 6.1 Add `<button data-tab="hypotheses">Hypotheses</button>` to the `.tabs` div, after the Evaluation button. **Spec: `dashboard-static`, `hypotheses-frontend`**
- [ ] 6.2 Add `<div id="tab-hypotheses" class="tab-content">` with: list container (`#hyp-list-container`) containing status filter buttons (`all`, `proposed`, `testing`, `confirmed`, `rejected`) and `#hyp-table` div; detail container (`#hyp-detail-container`, initially hidden) with back button, `#hyp-detail-kpis`, 2-column grid for `#hyp-evidence-table` and `#hyp-actions-table`. **Spec: `hypotheses-frontend`**
- [ ] 6.3 Add CSS for hypothesis status badges: `.hyp-badge` (pill shape), `.hyp-proposed` (blue), `.hyp-testing` (yellow), `.hyp-confirmed` (green), `.hyp-rejected` (red), `.hyp-invalidated` (gray). **Spec: `hypotheses-frontend`**
- [ ] 6.4 Implement `refreshHypotheses()` — fetch `/hypotheses/list`, handle `available: false`, `tables_exist: false`, and empty list with distinct empty-state messages. Call `renderHypTable()`. **Spec: `hypotheses-frontend`**
- [ ] 6.5 Implement `filterHypStatus(status)` — update `hypStatusFilter`, toggle `.active` class on filter buttons, re-call `refreshHypotheses()`. **Spec: `hypotheses-frontend`**
- [ ] 6.6 Implement `renderHypTable(hypotheses)` — filter by `hypStatusFilter`, render data table with columns: Hypothesis (truncated), Status (badge), Category, Confidence, Evidence count, Updated. Rows are clickable via `onclick="showHypDetail(id)"`. **Spec: `hypotheses-frontend`**
- [ ] 6.7 Implement `showHypDetail(id)` — fetch evidence and actions in parallel via `Promise.all`. Render KPI strip (title+status badge, confidence, evidence count, filters). Render evidence table (Run, Result supports/contradicts, Brier Diff, p-value, n, Date). Render actions table (Type, Config, Strength, Active/Inactive). Toggle visibility: hide list, show detail. **Spec: `hypotheses-frontend`**
- [ ] 6.8 Implement `closeHypDetail()` — toggle visibility back to list view. **Spec: `hypotheses-frontend`**
- [ ] 6.9 Add `case 'hypotheses': await refreshHypotheses(); break;` to the `refresh()` switch statement. **Spec: `hypotheses-frontend`**

## 7. Tests

- [ ] 7.1 Create test fixture: in-memory or temp-file `backtest.db` with `bt_simulation_runs`, `bt_simulation_trials`, `bt_markets`, `bt_regimes` tables populated with representative test data (at least 2 runs, 5+ trials with varied categories and volumes, 2+ regimes). **Spec: `evaluation-api`**
- [ ] 7.2 Write API tests for evaluation endpoints using `httpx.AsyncClient` + `create_app(backtest_db_path=...)`: verify `/runs` returns run list, `/trials/{id}` returns trials with sort params, `/by-category/{id}` groups correctly, `/by-volume-tier/{id}` buckets correctly, `/temporal/{id}` includes rolling Brier diff and regimes, `/compare` filters by category and volume tier. **Spec: `evaluation-api`**
- [ ] 7.3 Write API tests for hypotheses endpoints: verify graceful degradation when `backtest_db` is `None` (returns `available: false`), when backtest DB exists but hypothesis tables don't (returns `tables_exist: false`), and full happy-path with hypothesis data. **Spec: `hypotheses-api`**
- [ ] 7.4 Write test for `BacktestDB.create()` returning `None` when file doesn't exist and a valid instance when it does. **Spec: `dashboard-db`**
- [ ] 7.5 Verify dashboard HTML loads at `/` and Swagger docs accessible at `/api/docs` with the new routers registered (smoke test). **Spec: `dashboard-app`**
