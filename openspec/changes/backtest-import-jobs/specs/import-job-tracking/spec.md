## ADDED Requirements

### Requirement: Import job table persists collection state
The system SHALL maintain a `bt_import_jobs` table in `backtest.db` with columns: `id` (INTEGER PK AUTOINCREMENT), `job_type` (TEXT: 'full'|'histories'|'histories_filtered'), `status` (TEXT: 'running'|'done'|'failed'|'stalled'|'cancelled'), `params_json` (TEXT, JSON of CLI options), `pid` (INTEGER, OS process ID), `started_at` (TEXT ISO8601), `updated_at` (TEXT ISO8601), `completed_at` (TEXT ISO8601 nullable), `markets_total` (INTEGER nullable), `markets_done` (INTEGER default 0), `histories_total` (INTEGER nullable), `histories_done` (INTEGER default 0), `histories_skipped` (INTEGER default 0), `error_msg` (TEXT nullable).

#### Scenario: Table created on database init
- **WHEN** `init_backtest_db()` is called on a new or existing database
- **THEN** the `bt_import_jobs` table exists with all specified columns and `CREATE TABLE IF NOT EXISTS` semantics (idempotent)

#### Scenario: Table exists after migration on existing DB
- **WHEN** `init_backtest_db()` is called on an existing `backtest.db` that predates this table
- **THEN** the table is created without error and existing tables are unaffected

### Requirement: Collector creates a job row at collection start
The `BacktestCollector` SHALL insert a `bt_import_jobs` row with `status='running'`, current `pid`, `started_at`, and serialized params at the beginning of every `collect()` and `collect_histories_only()` call. It SHALL first mark any existing `running` rows as `stalled`.

#### Scenario: New job row created on collect start
- **WHEN** `collector.collect()` is called
- **THEN** a new `bt_import_jobs` row is inserted with `status='running'`, `pid=os.getpid()`, `started_at=now`, `job_type='full'`, and the returned `job_id` is stored for subsequent updates

#### Scenario: Stale running jobs cleaned up at start
- **WHEN** `collector.collect()` is called and a row with `status='running'` already exists
- **THEN** that existing row is updated to `status='stalled'` before the new row is inserted

#### Scenario: collect_histories_only creates job with correct type
- **WHEN** `collector.collect_histories_only(min_volume=100000)` is called
- **THEN** the job row has `job_type='histories_filtered'` and `params_json` contains `{"min_volume": 100000}`

### Requirement: Collector writes progress updates with heartbeat
The `BacktestCollector` SHALL update the current job row's progress counters and `updated_at` timestamp periodically during collection: every market batch for `_collect_markets()`, and every 50 records for `_collect_price_histories()`.

#### Scenario: Markets progress updated per batch
- **WHEN** `_collect_markets()` processes a batch of 500 markets
- **THEN** `markets_done` is incremented and `updated_at` is set to the current UTC time

#### Scenario: Histories progress updated every 50 records
- **WHEN** `_collect_price_histories()` processes 50 records
- **THEN** `histories_done` and `histories_skipped` are updated and `updated_at` is refreshed

#### Scenario: histories_total set at start of history collection
- **WHEN** `_collect_price_histories()` begins, after querying the count of markets needing history
- **THEN** `histories_total` is set to that count in the job row

### Requirement: Collector marks job done or failed on completion
The `BacktestCollector` SHALL update the job row to `status='done'` with `completed_at` on success, or `status='failed'` with `error_msg` if an unhandled exception occurs.

#### Scenario: Successful completion marks job done
- **WHEN** `collect()` completes without exception
- **THEN** the job row has `status='done'`, `completed_at` set to current UTC, and final counts accurate

#### Scenario: Exception marks job failed
- **WHEN** an unhandled exception occurs during collection
- **THEN** the job row is updated to `status='failed'` with `error_msg` containing the exception string

### Requirement: Collector handles SIGTERM gracefully and marks job cancelled
The `BacktestCollector` SHALL install a SIGTERM signal handler that updates the current job row to `status='cancelled'` and exits cleanly.

#### Scenario: SIGTERM received during collection
- **WHEN** the collector process receives SIGTERM while `_collect_price_histories()` is running
- **THEN** the signal handler sets `status='cancelled'` on the active job row and calls `sys.exit(0)`

#### Scenario: SIGTERM before job row exists (no-op)
- **WHEN** SIGTERM is received before a job row is created
- **THEN** the process exits cleanly without error

### Requirement: backtest collect command supports --job-id option
The `backtest collect` CLI command SHALL accept an optional `--job-id INTEGER` parameter. When provided, the collector uses the existing row instead of creating a new one. When absent, a new row is auto-created.

#### Scenario: --job-id uses existing row
- **WHEN** `backtest collect --job-id 42` is run
- **THEN** the collector updates row 42 (setting pid, started_at, status=running) rather than inserting a new row

#### Scenario: collect prints job ID on completion
- **WHEN** `backtest collect` completes (with or without --job-id)
- **THEN** the CLI prints "Job ID: <id>" to the console

### Requirement: backtest jobs command lists recent import jobs
The `backtest jobs` CLI command SHALL display the 10 most recent `bt_import_jobs` rows in a Rich table with columns: ID, Type, Status, Progress, Started, Duration.

#### Scenario: Jobs table displays running job with progress
- **WHEN** `backtest jobs` is run while a collection is active
- **THEN** the running row shows histories_done / histories_total as progress and elapsed time

#### Scenario: Jobs table on empty history
- **WHEN** `backtest jobs` is run and no rows exist
- **THEN** a message "No import jobs found" is displayed
