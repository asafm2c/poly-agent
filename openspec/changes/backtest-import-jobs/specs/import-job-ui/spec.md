## ADDED Requirements

### Requirement: Dashboard exposes read-only job list and detail endpoints
The system SHALL expose three endpoints under `/api/data/`:
- `GET /api/data/jobs` → list of last 20 jobs, newest first, each with `stale` flag computed server-side
- `GET /api/data/jobs/{id}` → single job with full detail including rate (records/sec) computation
- `POST /api/data/jobs/{id}/cancel` → sends SIGTERM to job's pid if status=running and heartbeat is fresh

All GET endpoints SHALL return `{"available": false}` when `backtest.db` is missing or `bt_import_jobs` table absent.

#### Scenario: Jobs list with running and completed rows
- **WHEN** `GET /api/data/jobs` is called with mixed job statuses
- **THEN** response includes `available: true` and a list with fields: id, job_type, status, stale, pid, started_at, updated_at, completed_at, markets_total, markets_done, histories_total, histories_done, histories_skipped, error_msg, progress_pct, duration_seconds

#### Scenario: Stale flag computed from heartbeat age
- **WHEN** a job has `status='running'` and `updated_at` is more than 300 seconds ago
- **THEN** the response includes `stale: true` for that job

#### Scenario: Jobs list when backtest.db missing
- **WHEN** `GET /api/data/jobs` is called and `backtest.db` does not exist
- **THEN** response is `{"available": false}` with HTTP 200

#### Scenario: Cancel sends SIGTERM to running job
- **WHEN** `POST /api/data/jobs/42/cancel` is called and job 42 has `status='running'` and fresh heartbeat
- **THEN** `os.kill(pid, signal.SIGTERM)` is called and response is `{"ok": true}`

#### Scenario: Cancel refused for stale job
- **WHEN** `POST /api/data/jobs/42/cancel` is called and job 42 has `updated_at` older than 300 seconds
- **THEN** response is `{"ok": false, "reason": "job appears stale"}` with HTTP 409

#### Scenario: Cancel refused for non-running job
- **WHEN** `POST /api/data/jobs/42/cancel` is called and job 42 has `status='done'`
- **THEN** response is `{"ok": false, "reason": "job is not running"}` with HTTP 409

### Requirement: Dashboard can trigger a new import via subprocess spawn
The system SHALL expose `POST /api/data/import` that pre-creates a `bt_import_jobs` row, spawns `uv run polymarket backtest collect [options] --job-id <id>` as a non-blocking subprocess, and updates the row with the subprocess pid.

#### Scenario: Full collection triggered
- **WHEN** `POST /api/data/import` is called with body `{"type": "full"}`
- **THEN** a job row is created, subprocess is spawned without `--histories-only`, and response includes `{"job_id": <id>}`

#### Scenario: Filtered history collection triggered
- **WHEN** `POST /api/data/import` is called with body `{"type": "histories_filtered", "min_volume": 100000}`
- **THEN** subprocess is spawned with `--histories-only --min-volume 100000 --job-id <id>`

#### Scenario: Import refused when job already running
- **WHEN** `POST /api/data/import` is called and a job with `status='running'` and fresh heartbeat exists
- **THEN** response is HTTP 409 with `{"error": "A collection job is already running", "job_id": <existing_id>}`

#### Scenario: Import refused when uv not found
- **WHEN** `POST /api/data/import` is called and `uv` is not on PATH
- **THEN** response is HTTP 503 with `{"error": "uv command not found — run collection from CLI instead"}`

### Requirement: app.state stores uv_cmd and bt_path for subprocess trigger
The dashboard application SHALL resolve `uv_cmd = shutil.which("uv")` and store the backtest db path string in `app.state` at startup.

#### Scenario: uv_cmd available at startup
- **WHEN** `create_app()` is called on a system where `uv` is installed
- **THEN** `app.state.uv_cmd` is a non-None string path

#### Scenario: uv_cmd is None when uv not installed
- **WHEN** `create_app()` is called and `uv` is not found on PATH
- **THEN** `app.state.uv_cmd` is None and the dashboard starts normally (not an error at startup)

### Requirement: Data tab shows Import Jobs section with live progress
The dashboard Data tab SHALL display an "Import Jobs" section below the existing charts, containing: a "New Import" dropdown button with three presets (Full collection, Histories only, Histories ≥ $100K), a job list with status badges (Running/Done/Failed/Stalled/Cancelled), progress bars for running jobs, elapsed/ETA information, and a Cancel button for running jobs.

#### Scenario: Running job shows progress bar
- **WHEN** a job has `status='running'` and `histories_total > 0`
- **THEN** a progress bar renders at `histories_done / histories_total × 100%` with records/sec rate

#### Scenario: Running job auto-polls every 5 seconds
- **WHEN** the Data tab is open and at least one job has `status='running'`
- **THEN** `GET /api/data/jobs` is called every 5 seconds and the UI updates without page reload

#### Scenario: Polling stops when no running jobs
- **WHEN** the last running job transitions to done/cancelled/failed
- **THEN** the 5-second poll interval is cleared

#### Scenario: Stale job shows warning badge
- **WHEN** a job has `status='running'` but `stale=true`
- **THEN** a yellow "Stalled" badge replaces the "Running" badge

#### Scenario: Cancel button triggers cancel endpoint
- **WHEN** the user clicks Cancel on a running job
- **THEN** `POST /api/data/jobs/{id}/cancel` is called and the button changes to "Cancelling..." until the next poll confirms status change

#### Scenario: Failed job shows error message
- **WHEN** a job has `status='failed'` and `error_msg` is non-null
- **THEN** the error message is displayed in red below the job row

#### Scenario: Empty state when no jobs exist
- **WHEN** the Import Jobs section loads and no rows exist in `bt_import_jobs`
- **THEN** "No import jobs yet — use 'New Import' to start a collection" is displayed
