## Purpose

Modify `app.py` to register the evaluation and hypotheses route modules, initialize a `BacktestDB` instance on `app.state`, and accept a backtest database path via CLI argument and environment variable.

## MODIFIED Requirements

### Requirement 1: BacktestDB initialization on app.state
The `create_app()` function SHALL accept an optional `backtest_db_path` parameter. The backtest DB path SHALL be resolved from (in priority order): the `backtest_db_path` argument, the `BACKTEST_DB_PATH` environment variable, or the default `"backtest.db"`. The result of `BacktestDB.create(bt_path)` SHALL be stored on `app.state.backtest_db` (which may be `None` if the file does not exist).

#### Scenario: Backtest DB path from argument
- **GIVEN** `create_app(backtest_db_path=Path("/data/backtest.db"))` is called
- **WHEN** the app initializes
- **THEN** `app.state.backtest_db` is a `BacktestDB` instance (or `None` if the file is missing at that path)

#### Scenario: Backtest DB path from environment variable
- **GIVEN** `BACKTEST_DB_PATH=/data/backtest.db` is set and no argument is provided
- **WHEN** the app initializes
- **THEN** `BacktestDB.create(Path("/data/backtest.db"))` is called

#### Scenario: Default backtest DB path
- **GIVEN** no argument and no environment variable are provided
- **WHEN** the app initializes
- **THEN** `BacktestDB.create(Path("backtest.db"))` is called

### Requirement 2: Evaluation router registration
The app SHALL import `evaluation` from `polymarket_dashboard.routes` and register `evaluation.router` at the `/api/evaluation` prefix with the `"evaluation"` tag.

#### Scenario: Evaluation endpoints accessible
- **GIVEN** the app has started
- **WHEN** a client requests `GET /api/evaluation/runs`
- **THEN** the request is routed to the evaluation router

### Requirement 3: Hypotheses router registration
The app SHALL import `hypotheses` from `polymarket_dashboard.routes` and register `hypotheses.router` at the `/api/hypotheses` prefix with the `"hypotheses"` tag.

#### Scenario: Hypotheses endpoints accessible
- **GIVEN** the app has started
- **WHEN** a client requests `GET /api/hypotheses/list`
- **THEN** the request is routed to the hypotheses router

### Requirement 4: Router ordering with static mount
The evaluation and hypotheses routers SHALL be registered BEFORE the static file mount (`app.mount("/", StaticFiles(...))`) to ensure API routes take precedence over the catch-all static file serving.

#### Scenario: API routes take precedence
- **GIVEN** the app has started with both API routers and static mount
- **WHEN** a client requests `GET /api/evaluation/runs`
- **THEN** the evaluation router handles the request, not the static file mount

### Requirement 5: CLI backtest-db argument
The `main()` function SHALL accept a `--backtest-db` CLI argument specifying the path to `backtest.db`. This argument SHALL be passed to `create_app()` as `backtest_db_path`.

#### Scenario: Launch with explicit backtest DB path
- **WHEN** the operator runs `polymarket-dashboard --db ./polymarket_agent.db --backtest-db ./backtest.db --port 8050`
- **THEN** the server starts with both databases configured

#### Scenario: Launch without backtest DB argument
- **WHEN** the operator runs `polymarket-dashboard --db ./polymarket_agent.db`
- **THEN** the server starts, falling back to environment variable or default path for the backtest DB

### Requirement 6: Import additions
The app module SHALL import `BacktestDB` from `polymarket_dashboard.db` and the `evaluation` and `hypotheses` modules from `polymarket_dashboard.routes`.

#### Scenario: Clean imports
- **GIVEN** the app module is loaded
- **WHEN** Python resolves imports
- **THEN** `BacktestDB`, `evaluation`, and `hypotheses` are available without import errors

## Scenarios

### Scenario: Full app startup with both databases
- **GIVEN** `polymarket_agent.db` and `backtest.db` both exist
- **WHEN** the app starts via `polymarket-dashboard --db ./polymarket_agent.db --backtest-db ./backtest.db`
- **THEN** `app.state.db` is a `DashboardDB`, `app.state.backtest_db` is a `BacktestDB`, and all 7 route prefixes (`portfolio`, `positions`, `calibration`, `operations`, `metrics`, `evaluation`, `hypotheses`) are registered

### Scenario: App startup without backtest database
- **GIVEN** `polymarket_agent.db` exists but `backtest.db` does not
- **WHEN** the app starts
- **THEN** `app.state.backtest_db` is `None`, the app starts successfully, and evaluation/hypothesis endpoints return empty-state responses
