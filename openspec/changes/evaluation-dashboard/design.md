## Context

The Polymarket dashboard is a standalone FastAPI application (`src/polymarket_dashboard/`) that reads the agent's `polymarket_agent.db` in read-only mode via `aiosqlite`. It serves a single `static/index.html` file with 5 tabs (Portfolio, Positions, Calibration, Operations, Costs & Ops), each driven by JSON API endpoints under `/api/{module}/`. Charts use Plotly.js (CDN, `plotly-basic-2.35.2`), styling uses PicoCSS dark theme, and data refreshes every 30 seconds via `setInterval`. The frontend is ~815 lines of self-contained HTML/CSS/JS with no build step.

Simulation results and backtest analysis live in a separate `backtest.db` with tables `bt_simulation_runs`, `bt_simulation_trials`, `bt_markets`, `bt_price_history`, and `bt_regimes`. The upcoming hypothesis-tracker change will add `bt_hypotheses`, `bt_hypothesis_evidence`, and `bt_hypothesis_actions` to the same database. Analysis functions in `analysis.py` compute Brier scores, category breakdowns, and volume-tier groupings using synchronous `sqlite3` — these need to be reimplemented as async SQL for the dashboard to stay decoupled from the agent package.

## Goals / Non-Goals

**Goals:**
- Add two new tabs (Evaluation, Hypotheses) to the existing `index.html`, following all established patterns exactly
- Extend the DB layer to support a second read-only async connection to `backtest.db`
- Provide evaluation API endpoints that reimplement `analysis.py` queries in async SQL
- Provide hypothesis API endpoints that read the hypothesis-tracker tables
- Enable interactive cross-filtering between charts and a drill-down table in the Evaluation tab
- Degrade gracefully when `backtest.db` does not exist or hypothesis tables are missing

**Non-Goals:**
- Importing or calling `analysis.py` functions from the dashboard (decoupling constraint)
- Writing to `backtest.db` (read-only, same as main DB pattern)
- Adding new Python or JS dependencies (everything uses existing aiosqlite, FastAPI, Plotly.js, PicoCSS)
- Server-side pagination or cursor-based queries (trial counts are small, hundreds not thousands)

## Decisions

### D1: BacktestDB as a parallel class, not a DashboardDB extension

**Decision:** Add a new `BacktestDB` class in `db.py` that mirrors `DashboardDB` but with a soft constructor that returns `None` when the file is missing, rather than raising `FileNotFoundError`.

**Rationale:** The main `DashboardDB` correctly fails hard when `polymarket_agent.db` is missing — the dashboard is useless without it. But `backtest.db` is optional; the operator may not have run any simulations. A separate class with graceful fallback keeps the existing `DashboardDB` behavior untouched while letting evaluation/hypothesis tabs show "No backtest data" empty states.

**Alternative considered:** A single `DashboardDB` that accepts multiple paths. Rejected because it would complicate the connection context manager and mix two databases with different availability guarantees.

**Implementation in `db.py`:**

```python
class BacktestDB:
    """Read-only async access to backtest.db. Returns None from create() if file missing."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    @classmethod
    def create(cls, db_path: Path) -> "BacktestDB | None":
        if not db_path.exists():
            return None
        return cls(db_path)

    @asynccontextmanager
    async def connection(self):
        db = await aiosqlite.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
        )
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA query_only=ON")
        await db.execute("PRAGMA busy_timeout=5000")
        try:
            yield _Connection(db)
        finally:
            await db.close()
```

This reuses the existing `_Connection` wrapper with its `execute_fetchone`, `execute_fetchall`, and `table_exists` helpers.

### D2: BacktestDB stored on app.state alongside existing db

**Decision:** `app.state.backtest_db` holds the `BacktestDB` instance (or `None`). Route handlers check for `None` before querying and return empty-state responses.

**Implementation in `app.py`:**

```python
from polymarket_dashboard.db import DashboardDB, BacktestDB
from polymarket_dashboard.routes import calibration, metrics, operations, portfolio, positions, evaluation, hypotheses

def create_app(db_path: Path | None = None, backtest_db_path: Path | None = None) -> FastAPI:
    path = db_path or Path(os.environ.get("DASHBOARD_DB_PATH", "polymarket_agent.db"))
    bt_path = backtest_db_path or Path(os.environ.get("BACKTEST_DB_PATH", "backtest.db"))

    app = FastAPI(title="Polymarket Agent Dashboard", docs_url="/api/docs")
    app.state.db = DashboardDB(path)
    app.state.backtest_db = BacktestDB.create(bt_path)
    app.state.starting_balance = float(os.environ.get("PAPER_STARTING_BALANCE", "1000.0"))

    app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
    app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
    app.include_router(calibration.router, prefix="/api/calibration", tags=["calibration"])
    app.include_router(operations.router, prefix="/api/operations", tags=["operations"])
    app.include_router(metrics.router, prefix="/api/metrics", tags=["metrics"])
    app.include_router(evaluation.router, prefix="/api/evaluation", tags=["evaluation"])
    app.include_router(hypotheses.router, prefix="/api/hypotheses", tags=["hypotheses"])

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True))

    return app
```

The `main()` function also gains a `--backtest-db` argument.

### D3: Route-level None guard pattern

**Decision:** Every evaluation/hypothesis endpoint starts with a guard that returns an empty-state response when `backtest_db is None`.

**Rationale:** Consistent with how `metrics.py` handles missing `metric_events` table via `_has_metrics()`. The guard avoids deeply nested conditionals.

**Pattern:**

```python
@router.get("/runs")
async def list_runs(request: Request):
    bt = request.app.state.backtest_db
    if bt is None:
        return {"runs": [], "available": False}
    async with bt.connection() as conn:
        ...
```

The `available: false` field lets the frontend show a targeted message ("No backtest database found") vs. "No simulation runs yet" (database exists but empty).

### D4: Async SQL reimplementation of analysis.py queries

**Decision:** Evaluation endpoints contain their own SQL queries rather than calling `analysis.py`. The SQL mirrors the logic in `simulation_summary()`, `simulation_by_category()`, and `simulation_by_volume_tier()`.

**Rationale:** The dashboard must not import from `polymarket_agent`. The analysis functions use synchronous `sqlite3`; the dashboard uses async `aiosqlite`. Reimplementing in SQL is actually simpler than the Python-side computation in `analysis.py` because SQLite handles the aggregation directly (fewer round trips, no in-memory loops).

### D5: Volume tier classification in SQL using CASE

**Decision:** Volume tier bucketing is done in SQL `CASE WHEN` expressions, matching the Python `_tier()` function in `analysis.py`:

```sql
CASE
    WHEN m.volume >= 10000000 THEN '>10M'
    WHEN m.volume >= 1000000  THEN '1M-10M'
    WHEN m.volume >= 100000   THEN '100K-1M'
    ELSE '10K-100K'
END AS volume_tier
```

### D6: Frontend cross-filtering via JavaScript state object

**Decision:** The Evaluation tab maintains a `evalFilter` JavaScript state object (`{category: null, volume_tier: null, run_id: null}`) that is updated when clicking chart elements and applied when rendering the drill-down table. Clicking a heatmap cell sets `category`; clicking a volume bar sets `volume_tier`. The table is re-filtered client-side from the full trials array without re-fetching from the API.

**Rationale:** Trial datasets are small (tens to hundreds of rows). Client-side filtering is instantaneous and avoids API round-trips for interactive exploration. A "Clear filters" button resets the state.

**Alternative considered:** Server-side filtered queries with URL params. Rejected because it adds latency for each click interaction and the data volume doesn't warrant it.

## Evaluation API Routes

### `GET /api/evaluation/runs`

Lists all simulation runs with summary statistics.

**SQL:**
```sql
SELECT
    r.id, r.started_at, r.completed_at, r.config,
    r.market_count, r.agent_brier, r.market_brier,
    r.simulated_pnl, r.total_cost,
    COUNT(t.id) AS trial_count,
    SUM(CASE WHEN t.agent_brier IS NOT NULL THEN 1 ELSE 0 END) AS valid_trials,
    AVG(t.agent_brier) AS avg_agent_brier,
    AVG(t.market_brier) AS avg_market_brier,
    AVG(t.agent_brier) - AVG(t.market_brier) AS brier_diff,
    SUM(CASE WHEN json_extract(t.simulated_trade, '$.net_pnl') > 0 THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN t.simulated_trade IS NOT NULL THEN 1 ELSE 0 END) AS trade_count
FROM bt_simulation_runs r
LEFT JOIN bt_simulation_trials t ON t.run_id = r.id
GROUP BY r.id
ORDER BY r.id DESC
```

**Response schema:**
```json
{
    "runs": [
        {
            "id": 3,
            "started_at": "2026-02-19T10:30:00",
            "completed_at": "2026-02-19T10:42:15",
            "config": "{\"horizon\": 7, \"volume_min\": 1000000}",
            "market_count": 20,
            "trial_count": 20,
            "valid_trials": 20,
            "agent_brier": 0.1675,
            "market_brier": 0.1788,
            "brier_diff": -0.0113,
            "simulated_pnl": 0.0,
            "trade_count": 0,
            "win_rate": null,
            "total_cost": 0.46
        }
    ],
    "available": true
}
```

### `GET /api/evaluation/trials/{run_id}`

Per-trial detail for a given run, joined with market metadata.

**Query parameters:**
- `run_id` (path, required): simulation run ID
- `sort_by` (query, optional, default `"market_id"`): one of `"brier_diff"`, `"agent_brier"`, `"volume"`, `"category"`, `"market_id"`
- `sort_dir` (query, optional, default `"asc"`): `"asc"` or `"desc"`

**SQL:**
```sql
SELECT
    t.id AS trial_id, t.market_id, t.horizon_days,
    t.market_price_at_horizon, t.agent_estimate,
    t.confidence_low, t.confidence_high,
    t.outcome, t.agent_brier, t.market_brier,
    t.agent_brier - t.market_brier AS brier_diff,
    t.edge, t.simulated_trade, t.reasoning,
    t.llm_cost, t.duration_ms,
    m.question, m.category, m.volume, m.end_date,
    m.resolution_outcome,
    CASE
        WHEN m.volume >= 10000000 THEN '>10M'
        WHEN m.volume >= 1000000  THEN '1M-10M'
        WHEN m.volume >= 100000   THEN '100K-1M'
        ELSE '10K-100K'
    END AS volume_tier
FROM bt_simulation_trials t
JOIN bt_markets m ON t.market_id = m.id
WHERE t.run_id = ?
ORDER BY {sort_column} {sort_dir}
```

The `sort_column` is validated server-side against an allowlist to prevent SQL injection: `{"brier_diff": "brier_diff", "agent_brier": "t.agent_brier", "volume": "m.volume", "category": "m.category", "market_id": "t.market_id"}`.

**Response schema:**
```json
{
    "run_id": 3,
    "trials": [
        {
            "trial_id": 45,
            "market_id": "0x1234...",
            "question": "Will Iran and US reach a nuclear deal by March 2026?",
            "category": null,
            "volume": 2500000,
            "volume_tier": "1M-10M",
            "end_date": "2026-03-01T00:00:00Z",
            "horizon_days": 7,
            "market_price": 0.35,
            "agent_estimate": 0.22,
            "confidence_low": 0.15,
            "confidence_high": 0.30,
            "outcome": 0.0,
            "agent_brier": 0.0484,
            "market_brier": 0.1225,
            "brier_diff": -0.0741,
            "edge": 0.13,
            "simulated_trade": null,
            "reasoning": "Base rate for diplomatic agreements...",
            "llm_cost": 0.023,
            "duration_ms": 38000
        }
    ],
    "count": 20
}
```

### `GET /api/evaluation/by-category/{run_id}`

Brier scores grouped by market category for a given run.

**SQL:**
```sql
SELECT
    COALESCE(m.category, '(null)') AS category,
    COUNT(*) AS trial_count,
    AVG(t.agent_brier) AS agent_brier,
    AVG(t.market_brier) AS market_brier,
    AVG(t.agent_brier) - AVG(t.market_brier) AS brier_diff,
    COALESCE(SUM(json_extract(t.simulated_trade, '$.net_pnl')), 0) AS simulated_pnl
FROM bt_simulation_trials t
JOIN bt_markets m ON t.market_id = m.id
WHERE t.run_id = ?
GROUP BY COALESCE(m.category, '(null)')
ORDER BY trial_count DESC
```

**Response schema:**
```json
{
    "run_id": 3,
    "categories": [
        {
            "category": "(null)",
            "trial_count": 18,
            "agent_brier": 0.1650,
            "market_brier": 0.1780,
            "brier_diff": -0.0130,
            "simulated_pnl": 0.0
        }
    ]
}
```

### `GET /api/evaluation/by-volume-tier/{run_id}`

Brier scores grouped by volume tier for a given run.

**SQL:**
```sql
SELECT
    CASE
        WHEN m.volume >= 10000000 THEN '>10M'
        WHEN m.volume >= 1000000  THEN '1M-10M'
        WHEN m.volume >= 100000   THEN '100K-1M'
        ELSE '10K-100K'
    END AS volume_tier,
    COUNT(*) AS trial_count,
    AVG(t.agent_brier) AS agent_brier,
    AVG(t.market_brier) AS market_brier,
    AVG(t.agent_brier) - AVG(t.market_brier) AS brier_diff,
    COALESCE(SUM(json_extract(t.simulated_trade, '$.net_pnl')), 0) AS simulated_pnl
FROM bt_simulation_trials t
JOIN bt_markets m ON t.market_id = m.id
WHERE t.run_id = ?
GROUP BY volume_tier
ORDER BY
    CASE volume_tier
        WHEN '10K-100K' THEN 1
        WHEN '100K-1M' THEN 2
        WHEN '1M-10M' THEN 3
        WHEN '>10M' THEN 4
    END
```

**Response schema:**
```json
{
    "run_id": 3,
    "tiers": [
        {
            "volume_tier": "1M-10M",
            "trial_count": 18,
            "agent_brier": 0.1650,
            "market_brier": 0.1780,
            "brier_diff": -0.0130,
            "simulated_pnl": 0.0
        },
        {
            "volume_tier": ">10M",
            "trial_count": 2,
            "agent_brier": 0.1900,
            "market_brier": 0.1850,
            "brier_diff": 0.0050,
            "simulated_pnl": 0.0
        }
    ]
}
```

### `GET /api/evaluation/temporal/{run_id}`

Trials ordered by resolution date with rolling Brier difference and regime boundaries.

**SQL (trials):**
```sql
SELECT
    t.id AS trial_id, t.market_id, t.agent_brier, t.market_brier,
    t.agent_brier - t.market_brier AS brier_diff,
    m.question, m.end_date, m.category, m.volume
FROM bt_simulation_trials t
JOIN bt_markets m ON t.market_id = m.id
WHERE t.run_id = ? AND t.agent_brier IS NOT NULL
ORDER BY m.end_date ASC
```

**SQL (regimes):**
```sql
SELECT name, start_date, end_date FROM bt_regimes ORDER BY start_date
```

The rolling Brier difference is computed server-side as a cumulative moving average over the ordered trials: for trial `i`, `rolling_brier_diff[i] = mean(brier_diff[0..i])`. This avoids SQL window functions that differ across SQLite versions.

**Response schema:**
```json
{
    "run_id": 3,
    "trials": [
        {
            "trial_id": 42,
            "market_id": "0xabc...",
            "question": "Will Bitcoin hit $150K...",
            "end_date": "2026-01-15",
            "category": null,
            "volume": 5000000,
            "agent_brier": 0.12,
            "market_brier": 0.15,
            "brier_diff": -0.03,
            "rolling_brier_diff": -0.03
        }
    ],
    "regimes": [
        {"name": "pre-GPT4", "start_date": "2020-01-01", "end_date": "2023-03-14"},
        {"name": "GPT4-era", "start_date": "2023-03-14", "end_date": "2024-03-04"},
        {"name": "Claude3-era", "start_date": "2024-03-04", "end_date": "2024-05-13"},
        {"name": "GPT4o-era", "start_date": "2024-05-13", "end_date": "2024-09-12"},
        {"name": "o1-era", "start_date": "2024-09-12", "end_date": "2025-06-25"},
        {"name": "post-Claude4", "start_date": "2025-06-25", "end_date": null}
    ]
}
```

### `GET /api/evaluation/compare`

Cross-run comparison of agent vs market Brier, for plotting progression over multiple runs.

**Query parameters:**
- `category` (optional): filter trials by market category
- `volume_tier` (optional): filter trials by volume tier (uses same CASE expression)

**SQL:**
```sql
SELECT
    r.id AS run_id,
    r.started_at,
    json_extract(r.config, '$.model') AS model,
    json_extract(r.config, '$.horizon') AS horizon,
    COUNT(t.id) AS trial_count,
    AVG(t.agent_brier) AS agent_brier,
    AVG(t.market_brier) AS market_brier,
    AVG(t.agent_brier) - AVG(t.market_brier) AS brier_diff
FROM bt_simulation_runs r
JOIN bt_simulation_trials t ON t.run_id = r.id
JOIN bt_markets m ON t.market_id = m.id
WHERE t.agent_brier IS NOT NULL
    {AND m.category = ?}
    {AND volume_tier_filter}
GROUP BY r.id
ORDER BY r.id ASC
```

Where the category and volume-tier clauses are conditionally appended based on query params.

**Response schema:**
```json
{
    "runs": [
        {
            "run_id": 1,
            "started_at": "2026-02-18T15:00:00",
            "model": "claude-sonnet-4-6",
            "horizon": 7,
            "trial_count": 10,
            "agent_brier": 0.1800,
            "market_brier": 0.1850,
            "brier_diff": -0.0050
        }
    ]
}
```

## Hypotheses API Routes

These endpoints read the tables from the hypothesis-tracker change: `bt_hypotheses`, `bt_hypothesis_evidence`, `bt_hypothesis_actions`. All endpoints guard on both `backtest_db is None` and `table_exists("bt_hypotheses")` to handle the case where the backtest DB exists but the hypothesis schema hasn't been applied yet.

### `GET /api/hypotheses/list`

**Query parameters:**
- `status` (optional): filter by hypothesis status (`proposed`, `testing`, `confirmed`, `rejected`, `invalidated`)

**SQL:**
```sql
SELECT
    h.id, h.title, h.description, h.status,
    h.category, h.volume_min, h.volume_max,
    h.model, h.confidence, h.created_at, h.updated_at,
    COUNT(e.id) AS evidence_count,
    MAX(e.created_at) AS last_evidence_at
FROM bt_hypotheses h
LEFT JOIN bt_hypothesis_evidence e ON e.hypothesis_id = h.id
{WHERE h.status = ?}
GROUP BY h.id
ORDER BY h.updated_at DESC
```

**Response schema:**
```json
{
    "hypotheses": [
        {
            "id": 1,
            "title": "Agent tempers overconfidence on probable-NO markets",
            "description": "For markets with price > 0.7...",
            "status": "testing",
            "category": null,
            "volume_min": 100000,
            "volume_max": 1000000,
            "model": null,
            "confidence": 0.65,
            "created_at": "2026-02-19T10:00:00",
            "updated_at": "2026-02-19T12:00:00",
            "evidence_count": 3,
            "last_evidence_at": "2026-02-19T12:00:00"
        }
    ],
    "available": true,
    "tables_exist": true
}
```

### `GET /api/hypotheses/{id}/evidence`

**SQL:**
```sql
SELECT
    e.id, e.hypothesis_id, e.run_id,
    e.brier_diff, e.p_value, e.sample_size,
    e.supports, e.notes, e.created_at,
    r.started_at AS run_started_at,
    r.agent_brier AS run_agent_brier,
    r.market_brier AS run_market_brier
FROM bt_hypothesis_evidence e
LEFT JOIN bt_simulation_runs r ON e.run_id = r.id
WHERE e.hypothesis_id = ?
ORDER BY e.created_at DESC
```

**Response schema:**
```json
{
    "hypothesis_id": 1,
    "evidence": [
        {
            "id": 5,
            "run_id": 3,
            "brier_diff": -0.0130,
            "p_value": 0.12,
            "sample_size": 18,
            "supports": true,
            "notes": "...",
            "created_at": "2026-02-19T12:00:00",
            "run_started_at": "2026-02-19T10:30:00",
            "run_agent_brier": 0.1675,
            "run_market_brier": 0.1788
        }
    ]
}
```

### `GET /api/hypotheses/{id}/actions`

**SQL:**
```sql
SELECT
    a.id, a.hypothesis_id, a.action_type,
    a.config, a.strength, a.active, a.created_at
FROM bt_hypothesis_actions a
WHERE a.hypothesis_id = ?
ORDER BY a.created_at DESC
```

**Response schema:**
```json
{
    "hypothesis_id": 1,
    "actions": [
        {
            "id": 2,
            "action_type": "edge_override",
            "config": "{\"category\": null, \"volume_tier\": \"100K-1M\", \"edge_adjustment\": -0.02}",
            "strength": 0.65,
            "active": true,
            "created_at": "2026-02-19T12:30:00"
        }
    ]
}
```

## Frontend Integration

### Tab Buttons

Add two buttons to the existing `<div class="tabs">` in `index.html`, after the "Costs & Ops" button:

```html
<button data-tab="evaluation">Evaluation</button>
<button data-tab="hypotheses">Hypotheses</button>
```

These follow the exact same `data-tab` attribute pattern. The existing tab switching code (`$$('.tabs button').forEach(...)`) automatically handles them because it operates on all `<button>` elements within `.tabs`.

### Tab Content Divs

Added inside `<main>`, after the costs tab content div:

```html
<!-- EVALUATION TAB -->
<div id="tab-evaluation" class="tab-content">
    <div id="eval-run-selector" style="margin-bottom:0.75rem;">
        <select id="eval-run-select" style="..."></select>
    </div>
    <div class="kpi-grid" id="eval-kpis"></div>
    <div class="grid-2">
        <div class="chart-container">
            <div class="chart-title">Model Comparison (Agent vs Market Brier)</div>
            <div id="eval-model-chart" style="height:300px;"></div>
        </div>
        <div class="chart-container">
            <div class="chart-title">Category Heatmap (Brier Diff)</div>
            <div id="eval-category-heatmap" style="height:300px;"></div>
        </div>
    </div>
    <div class="grid-2">
        <div class="chart-container">
            <div class="chart-title">Volume Tier Performance</div>
            <div id="eval-volume-chart" style="height:300px;"></div>
        </div>
        <div class="chart-container">
            <div class="chart-title">Temporal Brier Diff (Rolling)</div>
            <div id="eval-temporal-chart" style="height:300px;"></div>
        </div>
    </div>
    <div class="chart-container">
        <div class="chart-title">
            Trial Drill-Down
            <span id="eval-filter-badge" style="font-size:0.7rem;color:#94a3b8;margin-left:0.5rem;"></span>
            <button id="eval-clear-filter" class="expand-btn" style="margin-left:0.5rem;display:none;" onclick="clearEvalFilter()">Clear filter</button>
        </div>
        <input type="text" id="eval-search" placeholder="Search questions..." style="...">
        <div id="eval-drilldown-table"></div>
    </div>
</div>

<!-- HYPOTHESES TAB -->
<div id="tab-hypotheses" class="tab-content">
    <div id="hyp-list-container">
        <div class="chart-container">
            <div class="chart-title">Hypotheses</div>
            <div id="hyp-status-filter" style="margin-bottom:0.5rem;">
                <button class="expand-btn active" data-status="all" onclick="filterHypStatus('all')">All</button>
                <button class="expand-btn" data-status="proposed" onclick="filterHypStatus('proposed')">Proposed</button>
                <button class="expand-btn" data-status="testing" onclick="filterHypStatus('testing')">Testing</button>
                <button class="expand-btn" data-status="confirmed" onclick="filterHypStatus('confirmed')">Confirmed</button>
                <button class="expand-btn" data-status="rejected" onclick="filterHypStatus('rejected')">Rejected</button>
            </div>
            <div id="hyp-table"></div>
        </div>
    </div>
    <div id="hyp-detail-container" style="display:none;">
        <button class="expand-btn" onclick="closeHypDetail()" style="margin-bottom:0.5rem;">Back to list</button>
        <div class="kpi-grid" id="hyp-detail-kpis"></div>
        <div class="grid-2">
            <div class="chart-container">
                <div class="chart-title">Evidence</div>
                <div id="hyp-evidence-table"></div>
            </div>
            <div class="chart-container">
                <div class="chart-title">Active Actions</div>
                <div id="hyp-actions-table"></div>
            </div>
        </div>
    </div>
</div>
```

### CSS Additions

Added inside the existing `<style>` block:

```css
/* Run selector */
#eval-run-select {
    background: var(--card-bg); border: 1px solid #334155;
    color: #e2e8f0; padding: 0.4rem 0.75rem; border-radius: 6px;
    font-size: 0.85rem;
}

/* Search input for drill-down */
#eval-search {
    background: var(--card-bg); border: 1px solid #334155;
    color: #e2e8f0; padding: 0.4rem 0.75rem; border-radius: 6px;
    font-size: 0.8rem; width: 300px; margin-bottom: 0.5rem;
}

/* Hypothesis status badges */
.hyp-badge {
    display: inline-block; padding: 0.15rem 0.5rem; border-radius: 9999px;
    font-size: 0.7rem; font-weight: 600;
}
.hyp-proposed  { background: #1e3a5f; color: #60a5fa; }
.hyp-testing   { background: #422006; color: #fbbf24; }
.hyp-confirmed { background: #14532d; color: #86efac; }
.hyp-rejected  { background: #450a0a; color: #fca5a5; }
.hyp-invalidated { background: #1e293b; color: #64748b; }

/* Clickable heatmap/chart cells */
.eval-clickable { cursor: pointer; }

/* Sortable table header */
.data-table th.sortable { cursor: pointer; user-select: none; }
.data-table th.sortable:hover { color: #e2e8f0; }
.data-table th.sortable::after { content: ' \u2195'; font-size: 0.6rem; }
.data-table th.sort-asc::after { content: ' \u2191'; }
.data-table th.sort-desc::after { content: ' \u2193'; }
```

### JavaScript State for Evaluation Tab

```javascript
// --- Evaluation state ---
let evalRunId = null;
let evalTrials = [];  // full dataset from API
let evalFilter = { category: null, volume_tier: null };

function clearEvalFilter() {
    evalFilter = { category: null, volume_tier: null };
    renderEvalDrilldown();
    $('#eval-filter-badge').textContent = '';
    $('#eval-clear-filter').style.display = 'none';
}
```

### Refresh Integration

The `refresh()` function's switch statement gains two new cases:

```javascript
async function refresh() {
    try {
        switch (activeTab) {
            case 'portfolio': await refreshPortfolio(); break;
            case 'positions': await refreshPositions(); break;
            case 'calibration': await refreshCalibration(); break;
            case 'operations': await refreshOperations(); break;
            case 'costs': await refreshCosts(); break;
            case 'evaluation': await refreshEvaluation(); break;
            case 'hypotheses': await refreshHypotheses(); break;
        }
        ...
    }
}
```

### `refreshEvaluation()` Function

```javascript
async function refreshEvaluation() {
    const runs = await api('/evaluation/runs');
    if (!runs || !runs.available) {
        $('#eval-kpis').innerHTML = '<div class="empty-state">No backtest database found. Run a simulation first.</div>';
        return;
    }
    if (runs.runs.length === 0) {
        $('#eval-kpis').innerHTML = '<div class="empty-state">No simulation runs yet. Use: polymarket backtest simulate</div>';
        return;
    }

    // Populate run selector
    const select = $('#eval-run-select');
    const currentVal = select.value;
    select.innerHTML = runs.runs.map(r =>
        `<option value="${r.id}">Run #${r.id} — ${r.trial_count} trials — ${new Date(r.started_at).toLocaleDateString()}</option>`
    ).join('');
    if (currentVal && runs.runs.some(r => r.id == currentVal)) {
        select.value = currentVal;
    }
    evalRunId = parseInt(select.value);

    select.onchange = () => { evalRunId = parseInt(select.value); refreshEvaluation(); };

    // Fetch all data for selected run in parallel
    const [trials, byCategory, byVolume, temporal, compare] = await Promise.all([
        api(`/evaluation/trials/${evalRunId}`),
        api(`/evaluation/by-category/${evalRunId}`),
        api(`/evaluation/by-volume-tier/${evalRunId}`),
        api(`/evaluation/temporal/${evalRunId}`),
        api('/evaluation/compare'),
    ]);

    const run = runs.runs.find(r => r.id === evalRunId);
    renderEvalKPIs(run);
    renderModelComparison(compare);
    renderCategoryHeatmap(byCategory);
    renderVolumeTier(byVolume);
    renderTemporal(temporal);

    evalTrials = trials ? trials.trials : [];
    renderEvalDrilldown();
}
```

## Chart Specifications

All charts use the existing `PLOTLY_DARK` layout base and `PLOTLY_CONFIG` (`{displayModeBar: false, responsive: true}`).

### Evaluation KPI Strip

Uses the existing `kpiCard()` helper, 6 cards in the `kpi-grid`:

```javascript
function renderEvalKPIs(run) {
    const diff = run.brier_diff;
    const diffClass = diff < -0.005 ? 'positive' : diff > 0.005 ? 'negative' : 'neutral';
    const diffLabel = diff < 0 ? 'Agent Better' : diff > 0 ? 'Market Better' : 'Tied';
    const wr = run.win_rate != null ? (run.win_rate * 100).toFixed(0) + '%' : 'N/A';

    $('#eval-kpis').innerHTML = [
        kpiCard('Agent Brier', run.agent_brier != null ? run.agent_brier.toFixed(4) : '-', 'Lower is better'),
        kpiCard('Market Brier', run.market_brier != null ? run.market_brier.toFixed(4) : '-', 'Baseline'),
        kpiCard('Brier Diff', diff != null ? diff.toFixed(4) : '-', diffLabel, diffClass),
        kpiCard('Trials', `${run.valid_trials} / ${run.trial_count}`, `${run.trade_count} trades triggered`),
        kpiCard('Win Rate', wr, `${run.trade_count} trades`),
        kpiCard('LLM Cost', '$' + (run.total_cost || 0).toFixed(2),
            run.trial_count > 0 ? `$${(run.total_cost / run.trial_count).toFixed(3)}/trial` : ''),
    ].join('');
}
```

### Chart 1: Model Comparison (Grouped Bar)

Compares agent vs market Brier across all simulation runs.

```javascript
function renderModelComparison(data) {
    if (!data || data.runs.length === 0) {
        $('#eval-model-chart').innerHTML = '<div class="empty-state">Need multiple runs for comparison</div>';
        return;
    }
    const labels = data.runs.map(r => `Run #${r.run_id}`);
    Plotly.react('eval-model-chart', [
        {
            x: labels,
            y: data.runs.map(r => r.agent_brier),
            name: 'Agent',
            type: 'bar',
            marker: { color: '#3b82f6' },
        },
        {
            x: labels,
            y: data.runs.map(r => r.market_brier),
            name: 'Market',
            type: 'bar',
            marker: { color: '#475569' },
        }
    ], {
        ...PLOTLY_DARK,
        barmode: 'group',
        yaxis: { ...PLOTLY_DARK.yaxis, title: 'Brier Score (lower = better)' },
        showlegend: true,
        legend: { x: 0.02, y: 0.98 },
        annotations: data.runs.map((r, i) => ({
            x: labels[i],
            y: Math.max(r.agent_brier, r.market_brier) + 0.005,
            text: `n=${r.trial_count}`,
            showarrow: false,
            font: { size: 10, color: '#94a3b8' },
        })),
    }, PLOTLY_CONFIG);
}
```

- **Trace type:** `bar` (grouped via `barmode: 'group'`)
- **X data:** Run labels (`Run #1`, `Run #2`, ...)
- **Y data:** `agent_brier` (blue `#3b82f6`) and `market_brier` (slate `#475569`)
- **Annotations:** Trial count `n=X` above each pair, in muted color `#94a3b8`

### Chart 2: Category Heatmap

Rows = categories, single column per run. Cell color = Brier diff (green negative = agent better, red positive = market better). Cell text = trial count.

```javascript
function renderCategoryHeatmap(data) {
    if (!data || data.categories.length === 0) {
        $('#eval-category-heatmap').innerHTML = '<div class="empty-state">No category data</div>';
        return;
    }
    const cats = data.categories.map(c => c.category);
    const diffs = data.categories.map(c => c.brier_diff);
    const texts = data.categories.map(c =>
        `n=${c.trial_count}<br>diff=${c.brier_diff != null ? c.brier_diff.toFixed(4) : 'N/A'}`
    );

    Plotly.react('eval-category-heatmap', [{
        z: [diffs],
        x: cats,
        y: ['Brier Diff'],
        type: 'heatmap',
        colorscale: [
            [0, '#22c55e'],    // green = agent better (negative diff)
            [0.5, '#1e293b'],  // neutral center = card bg
            [1, '#ef4444'],    // red = market better (positive diff)
        ],
        zmid: 0,
        text: [texts],
        texttemplate: '%{text}',
        textfont: { size: 11, color: '#e2e8f0' },
        hovertemplate: '%{x}<br>Brier diff: %{z:.4f}<extra></extra>',
        showscale: true,
        colorbar: {
            title: 'Brier Diff',
            titleside: 'right',
            tickfont: { color: '#94a3b8' },
            titlefont: { color: '#94a3b8' },
        },
    }], {
        ...PLOTLY_DARK,
        margin: { ...PLOTLY_DARK.margin, l: 80 },
        xaxis: { ...PLOTLY_DARK.xaxis, title: '' },
        yaxis: { ...PLOTLY_DARK.yaxis, title: '' },
    }, PLOTLY_CONFIG);

    // Cross-filter: clicking a heatmap cell filters drill-down
    document.getElementById('eval-category-heatmap').on('plotly_click', function(eventData) {
        const cat = eventData.points[0].x;
        evalFilter.category = cat;
        evalFilter.volume_tier = null;
        renderEvalDrilldown();
        $('#eval-filter-badge').textContent = `Filtered: category = ${cat}`;
        $('#eval-clear-filter').style.display = 'inline';
    });
}
```

- **Trace type:** `heatmap`
- **Z data:** Brier diff values (1D array wrapped in array for single-row heatmap)
- **Color scale:** diverging green (#22c55e) through dark slate (#1e293b) to red (#ef4444), centered at 0 via `zmid: 0`
- **Cell text:** Trial count and diff value
- **Click handler:** Sets `evalFilter.category` and re-renders drill-down table

### Chart 3: Volume Tier Performance (Bar Chart)

```javascript
function renderVolumeTier(data) {
    if (!data || data.tiers.length === 0) {
        $('#eval-volume-chart').innerHTML = '<div class="empty-state">No volume tier data</div>';
        return;
    }
    const tierOrder = ['10K-100K', '100K-1M', '1M-10M', '>10M'];
    const sorted = tierOrder.filter(t => data.tiers.some(d => d.volume_tier === t))
        .map(t => data.tiers.find(d => d.volume_tier === t));

    const colors = sorted.map(t =>
        t.brier_diff < -0.005 ? '#22c55e' : t.brier_diff > 0.005 ? '#ef4444' : '#94a3b8'
    );

    Plotly.react('eval-volume-chart', [{
        x: sorted.map(t => t.volume_tier),
        y: sorted.map(t => t.brier_diff),
        type: 'bar',
        marker: { color: colors },
        text: sorted.map(t => `n=${t.trial_count}`),
        textposition: 'outside',
        textfont: { size: 10, color: '#94a3b8' },
        hovertemplate: '%{x}<br>Brier diff: %{y:.4f}<br>n=%{text}<extra></extra>',
    }], {
        ...PLOTLY_DARK,
        yaxis: { ...PLOTLY_DARK.yaxis, title: 'Brier Diff (negative = agent better)', zeroline: true, zerolinecolor: '#475569', zerolinewidth: 2 },
        xaxis: { ...PLOTLY_DARK.xaxis, title: 'Volume Tier' },
        showlegend: false,
        shapes: [{
            type: 'line', x0: -0.5, x1: sorted.length - 0.5, y0: 0, y1: 0,
            line: { color: '#475569', width: 1, dash: 'dash' },
        }],
    }, PLOTLY_CONFIG);

    // Cross-filter: clicking a bar filters drill-down
    document.getElementById('eval-volume-chart').on('plotly_click', function(eventData) {
        const tier = eventData.points[0].x;
        evalFilter.volume_tier = tier;
        evalFilter.category = null;
        renderEvalDrilldown();
        $('#eval-filter-badge').textContent = `Filtered: volume = ${tier}`;
        $('#eval-clear-filter').style.display = 'inline';
    });
}
```

- **Trace type:** `bar`
- **X data:** Volume tier labels in order `['10K-100K', '100K-1M', '1M-10M', '>10M']`
- **Y data:** Brier diff values
- **Bar colors:** Per-bar conditional: green `#22c55e` if agent better, red `#ef4444` if market better, muted `#94a3b8` if neutral
- **Annotations:** Trial count `n=X` above/below each bar via `text` + `textposition: 'outside'`
- **Zero line:** Dashed `#475569` line at y=0
- **Click handler:** Sets `evalFilter.volume_tier` and re-renders drill-down table

### Chart 4: Temporal Line (Rolling Brier Diff)

```javascript
function renderTemporal(data) {
    if (!data || data.trials.length === 0) {
        $('#eval-temporal-chart').innerHTML = '<div class="empty-state">No temporal data</div>';
        return;
    }

    const traces = [
        {
            x: data.trials.map(t => t.end_date),
            y: data.trials.map(t => t.rolling_brier_diff),
            type: 'scatter',
            mode: 'lines+markers',
            line: { color: '#3b82f6', width: 2 },
            marker: { size: 5, color: '#3b82f6' },
            name: 'Rolling Brier Diff',
            hovertemplate: '%{x}<br>Rolling diff: %{y:.4f}<extra></extra>',
        },
        {
            x: data.trials.map(t => t.end_date),
            y: data.trials.map(t => t.brier_diff),
            type: 'scatter',
            mode: 'markers',
            marker: { size: 4, color: '#94a3b8', opacity: 0.5 },
            name: 'Per-Trial Diff',
        }
    ];

    // Regime boundary vertical lines
    const shapes = data.regimes
        .filter(r => r.end_date != null)
        .map(r => ({
            type: 'line',
            x0: r.end_date, x1: r.end_date,
            y0: 0, y1: 1, yref: 'paper',
            line: { color: '#475569', width: 1, dash: 'dash' },
        }));

    // Regime labels as annotations
    const annotations = data.regimes
        .filter(r => r.end_date != null)
        .map(r => ({
            x: r.end_date,
            y: 1.02, yref: 'paper',
            text: r.name,
            showarrow: false,
            font: { size: 9, color: '#64748b' },
            textangle: -45,
        }));

    Plotly.react('eval-temporal-chart', traces, {
        ...PLOTLY_DARK,
        yaxis: {
            ...PLOTLY_DARK.yaxis,
            title: 'Brier Diff',
            zeroline: true, zerolinecolor: '#475569', zerolinewidth: 2,
        },
        xaxis: { ...PLOTLY_DARK.xaxis, type: 'date', title: 'Resolution Date' },
        showlegend: true,
        legend: { x: 0.02, y: 0.98, font: { size: 10 } },
        shapes: shapes,
        annotations: annotations,
    }, PLOTLY_CONFIG);
}
```

- **Trace 1:** Rolling Brier diff as `scatter` with `lines+markers`, blue `#3b82f6`
- **Trace 2:** Per-trial Brier diff as `scatter` with `markers` only, muted `#94a3b8` at 50% opacity
- **Regime boundaries:** Vertical dashed lines at each regime end date, via `shapes` array. Color `#475569`, dash pattern
- **Regime labels:** Annotations at top of chart, rotated -45 degrees, muted color `#64748b`
- **Zero line:** Emphasized at y=0, `#475569`

### Drill-Down Table

Client-side filtering and rendering from the `evalTrials` array:

```javascript
function renderEvalDrilldown() {
    let filtered = evalTrials;

    // Apply chart cross-filters
    if (evalFilter.category) {
        filtered = filtered.filter(t => (t.category || '(null)') === evalFilter.category);
    }
    if (evalFilter.volume_tier) {
        filtered = filtered.filter(t => t.volume_tier === evalFilter.volume_tier);
    }

    // Apply text search
    const search = ($('#eval-search').value || '').toLowerCase();
    if (search) {
        filtered = filtered.filter(t => t.question.toLowerCase().includes(search));
    }

    if (filtered.length === 0) {
        $('#eval-drilldown-table').innerHTML = '<div class="empty-state">No trials match current filters</div>';
        return;
    }

    const rows = filtered.map(t => {
        const diff = t.brier_diff;
        const diffClass = diff < -0.005 ? 'positive' : diff > 0.005 ? 'negative' : 'neutral';
        return `<tr>
            <td class="text-truncate" title="${t.question}">${truncate(t.question, 40)}</td>
            <td>${t.category || '-'}</td>
            <td>${t.volume_tier}</td>
            <td>${fmtProb(t.agent_estimate)}</td>
            <td>${fmtProb(t.market_price)}</td>
            <td>${t.outcome != null ? (t.outcome === 1 ? 'YES' : 'NO') : '-'}</td>
            <td>${t.agent_brier != null ? t.agent_brier.toFixed(4) : '-'}</td>
            <td>${t.market_brier != null ? t.market_brier.toFixed(4) : '-'}</td>
            <td class="${diffClass}">${diff != null ? diff.toFixed(4) : '-'}</td>
            <td>${t.edge != null ? fmtProb(t.edge) : '-'}</td>
            <td>$${(t.llm_cost || 0).toFixed(3)}</td>
        </tr>`;
    }).join('');

    $('#eval-drilldown-table').innerHTML = `
        <table class="data-table">
            <thead><tr>
                <th class="sortable" data-col="question">Market</th>
                <th class="sortable" data-col="category">Category</th>
                <th class="sortable" data-col="volume_tier">Vol Tier</th>
                <th class="sortable" data-col="agent_estimate">Estimate</th>
                <th class="sortable" data-col="market_price">Mkt Price</th>
                <th class="sortable" data-col="outcome">Outcome</th>
                <th class="sortable" data-col="agent_brier">Agent Brier</th>
                <th class="sortable" data-col="market_brier">Mkt Brier</th>
                <th class="sortable" data-col="brier_diff">Diff</th>
                <th class="sortable" data-col="edge">Edge</th>
                <th class="sortable" data-col="llm_cost">Cost</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>`;

    // Attach sort handlers
    $$('#eval-drilldown-table th.sortable').forEach(th => {
        th.addEventListener('click', () => sortEvalTable(th.dataset.col));
    });
}
```

The text search input triggers re-render on `input` event:

```javascript
$('#eval-search').addEventListener('input', () => renderEvalDrilldown());
```

Column sorting modifies `evalTrials` in place and re-renders:

```javascript
let evalSortCol = null;
let evalSortDir = 'asc';

function sortEvalTable(col) {
    if (evalSortCol === col) {
        evalSortDir = evalSortDir === 'asc' ? 'desc' : 'asc';
    } else {
        evalSortCol = col;
        evalSortDir = 'asc';
    }
    evalTrials.sort((a, b) => {
        let va = a[col], vb = b[col];
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === 'string') return evalSortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
        return evalSortDir === 'asc' ? va - vb : vb - va;
    });
    renderEvalDrilldown();
}
```

### `refreshHypotheses()` Function

```javascript
async function refreshHypotheses() {
    const data = await api('/hypotheses/list');
    if (!data || !data.available) {
        $('#hyp-table').innerHTML = '<div class="empty-state">No backtest database found</div>';
        return;
    }
    if (!data.tables_exist) {
        $('#hyp-table').innerHTML = '<div class="empty-state">Hypothesis tables not yet created. Run the hypothesis-tracker migration first.</div>';
        return;
    }
    if (data.hypotheses.length === 0) {
        $('#hyp-table').innerHTML = '<div class="empty-state">No hypotheses defined yet. Use: polymarket backtest hypothesis propose</div>';
        return;
    }

    renderHypTable(data.hypotheses);
}

let hypStatusFilter = 'all';

function filterHypStatus(status) {
    hypStatusFilter = status;
    $$('#hyp-status-filter button').forEach(b => b.classList.toggle('active', b.dataset.status === status));
    refreshHypotheses();
}

function renderHypTable(hypotheses) {
    let filtered = hypotheses;
    if (hypStatusFilter !== 'all') {
        filtered = filtered.filter(h => h.status === hypStatusFilter);
    }

    const badgeClass = { proposed: 'hyp-proposed', testing: 'hyp-testing', confirmed: 'hyp-confirmed', rejected: 'hyp-rejected', invalidated: 'hyp-invalidated' };

    const rows = filtered.map(h => `
        <tr style="cursor:pointer" onclick="showHypDetail(${h.id})">
            <td class="text-truncate" title="${h.title}">${truncate(h.title, 45)}</td>
            <td><span class="hyp-badge ${badgeClass[h.status] || ''}">${h.status}</span></td>
            <td>${h.category || '-'}</td>
            <td>${h.confidence != null ? (h.confidence * 100).toFixed(0) + '%' : '-'}</td>
            <td>${h.evidence_count}</td>
            <td style="font-size:0.7rem">${h.updated_at ? new Date(h.updated_at).toLocaleDateString() : '-'}</td>
        </tr>
    `).join('');

    $('#hyp-table').innerHTML = `
        <table class="data-table">
            <thead><tr>
                <th>Hypothesis</th><th>Status</th><th>Category</th>
                <th>Confidence</th><th>Evidence</th><th>Updated</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}
```

### Hypothesis Detail Panel

Clicking a hypothesis row loads evidence and actions, switching from list to detail view:

```javascript
async function showHypDetail(id) {
    const [evidenceData, actionsData, listData] = await Promise.all([
        api(`/hypotheses/${id}/evidence`),
        api(`/hypotheses/${id}/actions`),
        api('/hypotheses/list'),
    ]);

    const hyp = listData.hypotheses.find(h => h.id === id);
    if (!hyp) return;

    // KPIs
    const badgeClass = { proposed: 'hyp-proposed', testing: 'hyp-testing', confirmed: 'hyp-confirmed', rejected: 'hyp-rejected', invalidated: 'hyp-invalidated' };
    $('#hyp-detail-kpis').innerHTML = [
        kpiCard('Hypothesis', truncate(hyp.title, 50), `<span class="hyp-badge ${badgeClass[hyp.status]}">${hyp.status}</span>`),
        kpiCard('Confidence', hyp.confidence != null ? (hyp.confidence * 100).toFixed(0) + '%' : '-', ''),
        kpiCard('Evidence Records', hyp.evidence_count.toString(), hyp.last_evidence_at ? `Last: ${new Date(hyp.last_evidence_at).toLocaleDateString()}` : ''),
        kpiCard('Filters', [hyp.category, hyp.volume_min ? `>$${(hyp.volume_min/1000).toFixed(0)}K` : '', hyp.volume_max ? `<$${(hyp.volume_max/1000).toFixed(0)}K` : ''].filter(Boolean).join(', ') || 'None', ''),
    ].join('');

    // Evidence table
    if (evidenceData && evidenceData.evidence.length > 0) {
        const rows = evidenceData.evidence.map(e => `
            <tr>
                <td>Run #${e.run_id}</td>
                <td class="${e.supports ? 'positive' : 'negative'}">${e.supports ? 'Supports' : 'Contradicts'}</td>
                <td>${e.brier_diff != null ? e.brier_diff.toFixed(4) : '-'}</td>
                <td>${e.p_value != null ? e.p_value.toFixed(3) : '-'}</td>
                <td>${e.sample_size || '-'}</td>
                <td style="font-size:0.7rem">${new Date(e.created_at).toLocaleDateString()}</td>
            </tr>
        `).join('');
        $('#hyp-evidence-table').innerHTML = `
            <table class="data-table">
                <thead><tr><th>Run</th><th>Result</th><th>Brier Diff</th><th>p-value</th><th>n</th><th>Date</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
    } else {
        $('#hyp-evidence-table').innerHTML = '<div class="empty-state">No evidence records</div>';
    }

    // Actions table
    if (actionsData && actionsData.actions.length > 0) {
        const rows = actionsData.actions.map(a => `
            <tr>
                <td>${a.action_type}</td>
                <td style="font-size:0.75rem">${a.config}</td>
                <td>${(a.strength * 100).toFixed(0)}%</td>
                <td class="${a.active ? 'positive' : 'negative'}">${a.active ? 'Active' : 'Inactive'}</td>
            </tr>
        `).join('');
        $('#hyp-actions-table').innerHTML = `
            <table class="data-table">
                <thead><tr><th>Type</th><th>Config</th><th>Strength</th><th>Active</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
    } else {
        $('#hyp-actions-table').innerHTML = '<div class="empty-state">No actions generated</div>';
    }

    // Toggle visibility
    $('#hyp-list-container').style.display = 'none';
    $('#hyp-detail-container').style.display = 'block';
}

function closeHypDetail() {
    $('#hyp-list-container').style.display = 'block';
    $('#hyp-detail-container').style.display = 'none';
}
```

## App Registration

The complete `app.py` modifications:

1. Import `BacktestDB` from `db.py` and the two new route modules from `routes/`
2. Add `backtest_db_path` parameter to `create_app()`
3. Store `BacktestDB.create(bt_path)` on `app.state.backtest_db`
4. Register `evaluation.router` at `/api/evaluation` and `hypotheses.router` at `/api/hypotheses`
5. Add `--backtest-db` CLI argument to `main()`

The static file mount stays last (catch-all for the SPA), which is already the case.

## Risks / Trade-offs

- **SQL query duplication with analysis.py**: The evaluation endpoints reimplement aggregation logic that exists in `analysis.py`. If volume tier boundaries or Brier computation changes in the agent, the dashboard may diverge. Mitigated by: (1) the logic is arithmetic, not algorithmic; (2) both read the same DB tables; (3) the tier boundaries are a de facto standard (`10K-100K`, `100K-1M`, `1M-10M`, `>10M`).

- **Client-side filtering limited by data size**: The drill-down table holds all trials in memory. For runs with hundreds of trials this is fine. If runs grow to thousands, consider server-side pagination. Current design handles up to ~500 trials without noticeable lag.

- **Hypothesis table schema not yet implemented**: The hypotheses API depends on tables from the hypothesis-tracker change. The `table_exists()` guard ensures the tab shows a helpful message rather than crashing if the tables don't exist yet. This design is intentionally forward-compatible.

- **Two database connections from one process**: The dashboard opens connections to both `polymarket_agent.db` and `backtest.db`. Both use `mode=ro` and `busy_timeout=5000`. Since they are separate files, there is no contention between them. The backtest DB uses WAL mode (set by the agent), which allows unlimited concurrent readers.

- **Plotly heatmap for single-row data**: The category heatmap uses a Plotly `heatmap` trace with a single row, which may look sparse with few categories. If there are 1-2 categories, it functions as a colored bar. With 5+ categories it becomes a proper heatmap. The tradeoff is acceptable because the interaction (click to filter) works regardless of category count.

- **~600-700 lines of new JavaScript**: The two new tabs add substantial JS to the monolithic `index.html`. This is consistent with the existing pattern (5 tabs in ~600 lines of JS) but pushes the file toward ~1400-1500 lines total. Still manageable for a single-page monitoring tool with no build step. If future tabs are needed, consider extracting per-tab JS modules loaded via `<script type="module">`.
