## Context

`BacktestCollector` runs synchronously in the terminal. Both operations (`_collect_markets()` via paginated Gamma API, `_collect_price_histories()` via CLOB API with 429 backoff) can run for hours with no persistent state — only log output. The dashboard is a separate FastAPI process that opens `backtest.db` read-only via `aiosqlite`. There is no existing job/task table in either database.

The dashboard already has a `BacktestDB` class that does soft-fail on missing file and uses `mode=ro` URI parameter. The CLI uses the synchronous `get_backtest_db()` context manager which has write access.

## Goals / Non-Goals

**Goals:**
- Persist import job state (status, progress, pid, heartbeat) in `bt_import_jobs` within `backtest.db`
- Allow dashboard to observe job progress without DB write access
- Allow dashboard to trigger a new collection via subprocess spawn
- Allow dashboard to cancel a running collection via SIGTERM (using pid from DB)
- Add `backtest jobs` CLI command for terminal-based status inspection
- Auto-detect stale jobs (heartbeat > 5 min old) and surface them clearly in UI

**Non-Goals:**
- Multiple concurrent import jobs (one at a time only)
- Job queueing or scheduling of future imports
- Persistent job history beyond 20 most recent rows
- Dashboard-initiated cancel that writes to DB (SIGTERM avoids this)
- Progress for `backtest simulate` or `backtest evaluate` (separate concern)

## Decisions

### D1: Job state stored in backtest.db (not a separate file)
The collector already writes to `backtest.db`. Adding `bt_import_jobs` here means zero new database files and the dashboard's existing `BacktestDB` connection covers it automatically.

Alternative considered: separate `jobs.db` or in-memory state in the dashboard process. Rejected — separate file adds operational complexity; in-memory state is lost if the dashboard restarts.

### D2: Dashboard stays read-only; cancel uses os.kill(pid, SIGTERM)
The dashboard's `BacktestDB` keeps `mode=ro` and `PRAGMA query_only=ON`. Cancel is implemented by reading `pid` from the DB (read operation) and calling `os.kill(pid, signal.SIGTERM)` (syscall, no DB write). The collector installs a SIGTERM handler that writes `status=cancelled` and exits cleanly.

Alternative considered: sentinel column `cancel_requested=1` written by dashboard (requires write access). Rejected — breaks the clean read-only boundary. SIGTERM is simpler and doesn't require architectural changes.

### D3: Auto-create job row at start of every collection (no opt-in flag needed)
Every `backtest collect` run creates a `bt_import_jobs` row unconditionally. `--job-id` allows supplying an existing row id (for future dashboard-trigger flow where the dashboard pre-creates the row before spawning).

Alternative considered: `--track` flag as opt-in. Rejected — job rows are cheap and always useful; opt-in creates inconsistent observability.

### D4: Stale detection via updated_at heartbeat (dashboard-side computation)
The collector updates `updated_at` every batch. If the dashboard sees a `running` job with `updated_at` older than 5 minutes, it computes `stale=true` in the API response. The dashboard shows a warning badge but does not attempt to recover or mark the row.

Alternative: PID liveness check (`os.kill(pid, 0)`). Not available from the dashboard without an additional endpoint (since dashboard is async and read-only). Heartbeat is simpler and observable from both CLI and dashboard.

### D5: Dashboard trigger via subprocess.Popen with uv
The dashboard spawns `uv run polymarket backtest collect [--histories-only] [--min-volume N] --job-id <id>`. The `bt_import_jobs` row is pre-created (status=pending) before spawn; after spawn, pid is written to the row via a second DB call.

`uv_cmd` is resolved at startup via `shutil.which("uv")` and stored in `app.state.uv_cmd`. If not found, `/api/data/import` returns HTTP 503 with a clear message.

`bt_path` (the backtest db path as a string) is also stored in `app.state.bt_path` so it can be passed to the subprocess via `--db-path` or environment, ensuring the subprocess writes to the same DB the dashboard is reading.

**Problem**: The dashboard opens `backtest.db` read-only but needs to INSERT a job row before spawning. Solution: the import endpoint uses a separate write connection (`aiosqlite.connect(file:path, uri=False)` without `mode=ro`) just for the pre-create INSERT and pid UPDATE. This is the only point where the dashboard writes to `backtest.db`, scoped to `bt_import_jobs` only.

### D6: Progress update granularity
- `_collect_markets()`: update every batch (~500 markets). Total is unknown upfront, so `markets_total=NULL` until pagination ends.
- `_collect_price_histories()`: query total upfront (COUNT of markets needing history), update every 50 records (approx 1% for a 5000-market run).

### D7: Stale job cleanup on new job start
When `BacktestCollector._create_job()` is called, it first marks any existing `running` jobs as `stalled`. This prevents phantom running rows accumulating after crashes.

## Risks / Trade-offs

[PID reuse] → Check that `status=running` AND `updated_at` is recent (< 5 min) before sending SIGTERM. Stale jobs that have been running for > 5 min without a heartbeat will not receive SIGTERM.

[Dashboard write to backtest.db] → Scoped narrowly: only `POST /api/data/import` writes, only to `bt_import_jobs` table, only for INSERT (job row) and UPDATE (pid). All other dashboard routes remain read-only.

[uv not on PATH] → `/api/data/import` returns HTTP 503 with message "uv command not found — run collection from CLI instead". User can still use CLI.

[Subprocess inherits environment] → The subprocess needs the same `.env` settings (API keys, db path). `subprocess.Popen` inherits the parent environment, which is correct since the dashboard and CLI share the same `.env`.

[Collection already running] → `POST /api/data/import` queries `bt_import_jobs` for any `running` row with a fresh heartbeat (< 5 min). If found, returns HTTP 409 Conflict.

## Migration Plan

1. `init_backtest_db()` runs `CREATE TABLE IF NOT EXISTS bt_import_jobs` — safe for existing databases.
2. No data migration needed (new table, no columns added to existing tables).
3. Dashboard `BacktestDB` picks up the new table automatically on next query.
4. No rollback needed — removing the table is a no-op for existing functionality.

## Open Questions

- Should `backtest jobs` CLI command default to showing last 10 or 20 rows?
  → Decision: 10 (fits one terminal screen for typical 80-line terminal).
- Should the "New Import" button in the UI be a dropdown or separate buttons?
  → Decision: dropdown with 3 presets (Full collection, Histories only, Histories ≥ $100K).
