## Purpose

Extend the database layer in `db.py` to support a second read-only async connection to `backtest.db` via a new `BacktestDB` class, parallel to the existing `DashboardDB`. The `BacktestDB` class provides soft construction (returns `None` when the file is missing) to allow graceful degradation when no backtest data is available.

## MODIFIED Requirements

### Requirement 1: BacktestDB class with soft constructor
The `db.py` module SHALL define a `BacktestDB` class with a `create(db_path: Path) -> BacktestDB | None` class method. If `db_path` does not exist, `create()` SHALL return `None`. If `db_path` exists, `create()` SHALL return a `BacktestDB` instance. This class SHALL NOT raise `FileNotFoundError` (unlike `DashboardDB`, which correctly fails hard for the main database).

#### Scenario: Backtest DB file exists
- **GIVEN** `backtest.db` exists at the configured path
- **WHEN** `BacktestDB.create(path)` is called
- **THEN** a `BacktestDB` instance is returned (not `None`)

#### Scenario: Backtest DB file missing
- **GIVEN** no file exists at the configured path
- **WHEN** `BacktestDB.create(path)` is called
- **THEN** `None` is returned without raising an exception

### Requirement 2: Read-only async connection
The `BacktestDB` class SHALL provide an `async connection()` context manager that opens the database with `file:{path}?mode=ro` URI parameter, sets `PRAGMA query_only=ON` and `PRAGMA busy_timeout=5000`, and uses `aiosqlite.Row` as the row factory. The connection SHALL be closed when the context manager exits. The connection SHALL reuse the existing `_Connection` wrapper class to provide `execute_fetchone`, `execute_fetchall`, and `table_exists` helper methods.

#### Scenario: Connection is read-only
- **GIVEN** a `BacktestDB` instance exists
- **WHEN** a connection is opened
- **THEN** `mode=ro` and `PRAGMA query_only=ON` are set, preventing any writes

#### Scenario: Connection supports table_exists
- **GIVEN** a connection is open to `backtest.db`
- **WHEN** `conn.table_exists("bt_hypotheses")` is called
- **THEN** it returns `True` if the table exists, `False` otherwise

#### Scenario: Concurrent reads with WAL mode
- **GIVEN** the agent's simulator is writing to `backtest.db` via WAL mode
- **WHEN** the dashboard opens a read-only connection
- **THEN** reads succeed without blocking or errors, with `busy_timeout=5000` handling brief contention

### Requirement 3: DashboardDB unchanged
The existing `DashboardDB` class SHALL NOT be modified. It SHALL continue to raise `FileNotFoundError` when its database path does not exist. The `BacktestDB` class is a parallel, independent class — not a subclass or extension of `DashboardDB`.

#### Scenario: DashboardDB behavior preserved
- **GIVEN** the main `polymarket_agent.db` does not exist
- **WHEN** `DashboardDB(path)` is constructed and a connection is attempted
- **THEN** `FileNotFoundError` is raised, consistent with existing behavior

## Scenarios

### Scenario: Both databases available
- **GIVEN** both `polymarket_agent.db` and `backtest.db` exist
- **WHEN** the dashboard starts
- **THEN** `DashboardDB` connects to the main database and `BacktestDB.create()` returns a valid instance for the backtest database, allowing both to be queried independently

### Scenario: Main DB available, backtest DB missing
- **GIVEN** `polymarket_agent.db` exists but `backtest.db` does not
- **WHEN** the dashboard starts
- **THEN** `DashboardDB` connects normally and `BacktestDB.create()` returns `None`, causing evaluation/hypothesis tabs to show empty states
