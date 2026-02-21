## Why

Data collection runs (`backtest collect`) can take hours, produce only terminal log output, and leave no persistent record of progress or outcome. There is no way to monitor a running collection from the dashboard, trigger one without a terminal, or see whether a previous run succeeded or stalled.

## What Changes

- New `bt_import_jobs` table in `backtest.db` tracks every collection run (status, progress counts, pid, timestamps, error)
- `BacktestCollector` gains job-aware progress writing: creates a job row at start, updates counts per batch, writes heartbeat timestamps, handles SIGTERM gracefully
- `backtest collect` CLI gains `--job-id` option (use existing row) and prints job id on completion
- New `backtest jobs` CLI command lists recent import jobs in a rich table
- New dashboard API endpoints under `/api/data/jobs/` (read-only): list jobs, single job detail, cancel via SIGTERM
- Dashboard Data tab gains an "Import Jobs" section at the bottom: job list with status badges and progress bars, "New Import" trigger button, auto-poll while running, cancel button

## Capabilities

### New Capabilities
- `import-job-tracking`: Schema + collector integration for persisting import job state (status, progress, pid, heartbeat) in `bt_import_jobs`
- `import-job-ui`: Dashboard UI and API for observing and triggering import jobs, including progress bars, auto-polling, subprocess spawn, and SIGTERM cancel

### Modified Capabilities
- `historical-data`: Collection progress is now written to `bt_import_jobs` per batch; SIGTERM handler ensures clean status update before exit

## Impact

- `src/polymarket_agent/backtest/database.py` — new table definition + migration
- `src/polymarket_agent/backtest/collector.py` — job creation, progress writes, signal handler
- `src/polymarket_agent/cli/main.py` — `--job-id` option on `collect`, new `backtest jobs` command
- `src/polymarket_dashboard/app.py` — `uv_cmd` and `bt_path` stored in app.state
- `src/polymarket_dashboard/routes/data.py` — new job endpoints added to existing router
- `src/polymarket_dashboard/static/index.html` — Import Jobs section + JS logic
- `tests/test_dashboard_data.py` — extended with job endpoint tests
- New `tests/test_import_jobs.py` — collector + CLI job tracking tests
