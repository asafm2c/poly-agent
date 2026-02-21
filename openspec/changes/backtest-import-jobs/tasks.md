## 1. Schema

- [x] 1.1 Add `bt_import_jobs` table to `init_backtest_db()` in `backtest/database.py` with all required columns (id, job_type, status, params_json, pid, started_at, updated_at, completed_at, markets_total, markets_done, histories_total, histories_done, histories_skipped, error_msg)
- [x] 1.2 Ensure table creation is idempotent (`CREATE TABLE IF NOT EXISTS`) — safe for existing databases with no migration needed

## 2. Collector — Job Helpers

- [x] 2.1 Add `_create_job(job_type, params, job_id=None)` helper to `BacktestCollector`: marks any existing `running` rows as `stalled`, then inserts (or updates existing row) with `status=running`, `pid=os.getpid()`, `started_at=now`; returns `job_id`
- [x] 2.2 Add `_update_job(**fields)` helper: updates the current job row's specified fields plus `updated_at=now` using the write-capable `get_backtest_db()` connection
- [x] 2.3 Install SIGTERM handler in `BacktestCollector.__init__`: sets `status=cancelled` on active job row (if any) then calls `sys.exit(0)`

## 3. Collector — Progress Writes

- [x] 3.1 Call `_create_job('full', {})` at start of `collect()` and `_create_job('histories'/'histories_filtered', params)` at start of `collect_histories_only()`
- [x] 3.2 In `_collect_markets()`: call `_update_job(markets_done=total)` after each batch loop iteration
- [x] 3.3 In `_collect_price_histories()`: set `histories_total` via `_update_job` after the initial COUNT query; call `_update_job(histories_done=collected, histories_skipped=skipped)` every 50 records
- [x] 3.4 In `collect()` success path: call `_update_job(status='done', completed_at=now)` before returning
- [x] 3.5 In `collect()` / `collect_histories_only()` exception handler: call `_update_job(status='failed', error_msg=str(e))` then re-raise

## 4. CLI Commands

- [x] 4.1 Add `--job-id` option to `backtest collect` command; pass through to `BacktestCollector` so `_create_job()` uses the existing row instead of inserting
- [x] 4.2 Print "Job ID: {id}" after collection completes in `backtest collect` command
- [x] 4.3 Add `backtest jobs` command: queries last 10 `bt_import_jobs` rows, renders a Rich table with columns: ID, Type, Status, Progress, Started, Duration; shows "No import jobs found" if empty

## 5. Dashboard App Setup

- [x] 5.1 In `create_app()` (`app.py`): store `app.state.uv_cmd = shutil.which("uv")` and `app.state.bt_path = str(bt_path)` for use by the import endpoint

## 6. Dashboard API — Job Endpoints

- [x] 6.1 Add `GET /api/data/jobs` endpoint to `routes/data.py`: queries `bt_import_jobs` last 20 rows, computes `stale` (updated_at > 300s ago for running jobs), `progress_pct`, `duration_seconds`; returns `{"available": false}` if table missing
- [x] 6.2 Add `GET /api/data/jobs/{id}` endpoint: single job row with same computed fields plus `rate` (histories_done / elapsed_seconds)
- [x] 6.3 Add `POST /api/data/import` endpoint: validates no active job (409 if running+fresh), checks `uv_cmd` (503 if None), inserts job row, spawns `subprocess.Popen(...)`, updates row with pid; returns `{"job_id": id}`
- [x] 6.4 Add `POST /api/data/jobs/{id}/cancel` endpoint: validates `status=running` and fresh heartbeat (< 300s), calls `os.kill(pid, signal.SIGTERM)`; returns `{"ok": true}` or 409 with reason

## 7. Dashboard UI

- [x] 7.1 Add "Import Jobs" section div at the bottom of `#tab-data` in `index.html`, including a "New Import" dropdown button (three options: Full collection / Histories only / Histories ≥ $100K)
- [x] 7.2 Implement `refreshJobsSection()` JS function: fetches `/api/data/jobs`, renders job list with status badges (color-coded: green=done, blue=running, red=failed, yellow=stalled, gray=cancelled)
- [x] 7.3 Render progress bar for running jobs: `histories_done / histories_total × 100%`, rate (records/sec), and estimated time remaining
- [x] 7.4 Render Cancel button for running non-stale jobs: on click, POST to cancel endpoint, disable button and show "Cancelling..."
- [x] 7.5 Render error_msg in red for failed jobs
- [x] 7.6 Wire "New Import" dropdown: on option select, POST `/api/data/import` with appropriate body, then immediately call `refreshJobsSection()` and start polling
- [x] 7.7 Auto-poll `refreshJobsSection()` every 5 seconds when any job has `status=running`; clear interval when no running jobs remain
- [x] 7.8 Call `refreshJobsSection()` on Data tab activation (add to `refreshData()` or the tab switch handler)

## 8. Tests

- [x] 8.1 Schema: test `bt_import_jobs` table created by `init_backtest_db()`, verify all columns exist; test idempotency (run twice, no error)
- [x] 8.2 Collector: test `_create_job()` inserts row with correct fields and marks prior running row as stalled
- [x] 8.3 Collector: test `_update_job()` updates counts and `updated_at`
- [x] 8.4 Collector: test SIGTERM handler sets `status=cancelled` on active job row
- [x] 8.5 Collector: test exception path sets `status=failed` with `error_msg`
- [x] 8.6 API `GET /api/data/jobs`: test list with stale flag, progress_pct, duration; test `available=false` when table missing
- [x] 8.7 API `POST /api/data/import`: test 409 when job already running; test 503 when uv_cmd=None; test successful spawn sets job_id in response (mock subprocess)
- [x] 8.8 API `POST /api/data/jobs/{id}/cancel`: test 409 for stale job; test 409 for non-running job; test `os.kill` called for valid running job (mock os.kill)
