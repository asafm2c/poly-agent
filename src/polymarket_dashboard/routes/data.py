"""Data API: backtest corpus statistics and import job management from backtest.db."""

import json
import os
import signal
import subprocess
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

STALE_SECONDS = 300  # 5 minutes without heartbeat = stale


def _get_bt_db(request: Request):
    return request.app.state.backtest_db


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_seconds(started_at: str | None) -> float | None:
    if not started_at:
        return None
    try:
        start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        return (_now_utc() - start_dt).total_seconds()
    except Exception:
        return None


def _heartbeat_age(updated_at: str | None) -> float | None:
    if not updated_at:
        return None
    try:
        upd_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        return (_now_utc() - upd_dt).total_seconds()
    except Exception:
        return None


def _format_job(r) -> dict:
    """Format a bt_import_jobs row into an API response dict."""
    status = r["status"]
    histories_total = r["histories_total"] or 0
    histories_done = r["histories_done"] or 0
    histories_skipped = r["histories_skipped"] or 0

    progress_pct = None
    if histories_total > 0:
        progress_pct = round(histories_done / histories_total * 100, 1)

    elapsed = _elapsed_seconds(r["started_at"])
    duration_seconds = None
    if r["completed_at"] and r["started_at"]:
        try:
            s = datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(r["completed_at"].replace("Z", "+00:00"))
            duration_seconds = int((e - s).total_seconds())
        except Exception:
            pass
    elif elapsed is not None and status == "running":
        duration_seconds = int(elapsed)

    stale = False
    if status == "running":
        age = _heartbeat_age(r["updated_at"])
        if age is not None and age > STALE_SECONDS:
            stale = True

    rate = None
    if histories_done > 0 and elapsed and elapsed > 0:
        rate = round(histories_done / elapsed, 2)

    return {
        "id": r["id"],
        "job_type": r["job_type"],
        "status": r["status"],
        "stale": stale,
        "pid": r["pid"],
        "params": json.loads(r["params_json"]) if r["params_json"] else {},
        "started_at": r["started_at"],
        "updated_at": r["updated_at"],
        "completed_at": r["completed_at"],
        "markets_total": r["markets_total"],
        "markets_done": r["markets_done"] or 0,
        "histories_total": histories_total,
        "histories_done": histories_done,
        "histories_skipped": histories_skipped,
        "progress_pct": progress_pct,
        "duration_seconds": duration_seconds,
        "rate": rate,
        "error_msg": r["error_msg"],
    }


# ---------------------------------------------------------------------------
# Corpus statistics endpoints (existing)
# ---------------------------------------------------------------------------


@router.get("/summary")
async def data_summary(request: Request):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_markets"):
            return {"available": False}

        row = await conn.execute_fetchone(
            """SELECT
                COUNT(*) as total,
                SUM(has_history) as with_history,
                MIN(end_date) as date_start,
                MAX(end_date) as date_end,
                COUNT(DISTINCT COALESCE(category, 'unknown')) as category_count,
                MIN(volume) as volume_min,
                MAX(volume) as volume_max
            FROM bt_markets"""
        )

    if not row or not row["total"]:
        return {"available": False}

    total = row["total"] or 0
    with_history = row["with_history"] or 0
    coverage_pct = round(with_history / total * 100, 1) if total > 0 else 0.0

    return {
        "available": True,
        "total_markets": total,
        "with_history": with_history,
        "coverage_pct": coverage_pct,
        "date_range_start": row["date_start"],
        "date_range_end": row["date_end"],
        "category_count": row["category_count"] or 0,
        "volume_min": row["volume_min"],
        "volume_max": row["volume_max"],
    }


@router.get("/by-category")
async def data_by_category(request: Request):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "categories": []}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_markets"):
            return {"available": False, "categories": []}

        rows = await conn.execute_fetchall(
            """SELECT
                COALESCE(category, 'unknown') as category,
                COUNT(*) as total,
                SUM(has_history) as with_history
            FROM bt_markets
            GROUP BY COALESCE(category, 'unknown')
            ORDER BY total DESC"""
        )

    categories = [
        {
            "category": r["category"],
            "total": r["total"],
            "with_history": r["with_history"] or 0,
        }
        for r in rows
    ]

    return {"available": True, "categories": categories}


@router.get("/by-volume-tier")
async def data_by_volume_tier(request: Request):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "tiers": []}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_markets"):
            return {"available": False, "tiers": []}

        rows = await conn.execute_fetchall(
            """SELECT
                CASE
                    WHEN volume >= 10000000 THEN '>$10M'
                    WHEN volume >= 1000000  THEN '$1M-$10M'
                    WHEN volume >= 100000   THEN '$100K-$1M'
                    WHEN volume >= 10000    THEN '$10K-$100K'
                    ELSE '<$10K'
                END as tier,
                COUNT(*) as total,
                SUM(has_history) as with_history
            FROM bt_markets
            GROUP BY tier"""
        )

    # Enforce logical order
    tier_order = ['<$10K', '$10K-$100K', '$100K-$1M', '$1M-$10M', '>$10M']
    tier_map = {r["tier"]: r for r in rows}
    tiers = []
    for t in tier_order:
        if t in tier_map:
            r = tier_map[t]
            tiers.append({
                "tier": r["tier"],
                "total": r["total"],
                "with_history": r["with_history"] or 0,
            })

    return {"available": True, "tiers": tiers}


@router.get("/temporal")
async def data_temporal(request: Request):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "months": [], "regimes": []}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_markets"):
            return {"available": False, "months": [], "regimes": []}

        rows = await conn.execute_fetchall(
            """SELECT
                strftime('%Y-%m', end_date) as month,
                COUNT(*) as total,
                SUM(has_history) as with_history
            FROM bt_markets
            WHERE end_date IS NOT NULL
            GROUP BY month
            ORDER BY month ASC"""
        )

        regimes = []
        if await conn.table_exists("bt_regimes"):
            regime_rows = await conn.execute_fetchall(
                "SELECT name, start_date, end_date FROM bt_regimes ORDER BY start_date"
            )
            regimes = [
                {"name": r["name"], "start_date": r["start_date"], "end_date": r["end_date"]}
                for r in regime_rows
            ]

    months = [
        {
            "month": r["month"],
            "total": r["total"],
            "with_history": r["with_history"] or 0,
        }
        for r in rows
    ]

    return {"available": True, "months": months, "regimes": regimes}


# ---------------------------------------------------------------------------
# Import job endpoints
# ---------------------------------------------------------------------------


@router.get("/jobs")
async def list_jobs(request: Request):
    """List the last 20 import jobs."""
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "jobs": []}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_import_jobs"):
            return {"available": False, "jobs": []}

        rows = await conn.execute_fetchall(
            """SELECT id, job_type, status, params_json, pid,
                      started_at, updated_at, completed_at,
                      markets_total, markets_done,
                      histories_total, histories_done, histories_skipped,
                      error_msg
               FROM bt_import_jobs
               ORDER BY id DESC
               LIMIT 20"""
        )

    jobs = [_format_job(r) for r in rows]
    return {"available": True, "jobs": jobs}


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: int):
    """Get a single import job by ID."""
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return JSONResponse({"available": False}, status_code=404)

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_import_jobs"):
            return JSONResponse({"available": False}, status_code=404)

        row = await conn.execute_fetchone(
            """SELECT id, job_type, status, params_json, pid,
                      started_at, updated_at, completed_at,
                      markets_total, markets_done,
                      histories_total, histories_done, histories_skipped,
                      error_msg
               FROM bt_import_jobs WHERE id = ?""",
            (job_id,),
        )

    if not row:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    return {"available": True, "job": _format_job(row)}


@router.post("/import")
async def trigger_import(request: Request):
    """Spawn a new backtest collection subprocess."""
    uv_cmd = getattr(request.app.state, "uv_cmd", None)
    bt_path = getattr(request.app.state, "bt_path", "backtest.db")
    bt_db = _get_bt_db(request)

    if uv_cmd is None:
        return JSONResponse(
            {"error": "uv command not found — run collection from CLI instead"},
            status_code=503,
        )

    # Parse request body
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    import_type = body.get("type", "full")
    min_volume = body.get("min_volume")

    # Check for already-running job (read-only check)
    if bt_db is not None:
        async with bt_db.connection() as conn:
            if await conn.table_exists("bt_import_jobs"):
                row = await conn.execute_fetchone(
                    "SELECT id, updated_at FROM bt_import_jobs WHERE status='running' LIMIT 1"
                )
                if row:
                    age = _heartbeat_age(row["updated_at"])
                    if age is None or age <= STALE_SECONDS:
                        return JSONResponse(
                            {
                                "error": "A collection job is already running",
                                "job_id": row["id"],
                            },
                            status_code=409,
                        )

    # Pre-create job row using a write connection (narrow exception to read-only rule)
    now = datetime.now(timezone.utc).isoformat()
    params = {}
    if min_volume is not None:
        params["min_volume"] = min_volume

    job_id = None
    async with aiosqlite.connect(bt_path) as db:
        db.row_factory = aiosqlite.Row
        # Ensure table exists (may be a fresh DB)
        await db.execute("""CREATE TABLE IF NOT EXISTS bt_import_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            params_json TEXT,
            pid INTEGER,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            markets_total INTEGER,
            markets_done INTEGER DEFAULT 0,
            histories_total INTEGER,
            histories_done INTEGER DEFAULT 0,
            histories_skipped INTEGER DEFAULT 0,
            error_msg TEXT
        )""")
        cursor = await db.execute(
            """INSERT INTO bt_import_jobs (job_type, status, params_json, started_at, updated_at)
               VALUES (?, 'running', ?, ?, ?)""",
            (import_type, json.dumps(params), now, now),
        )
        job_id = cursor.lastrowid
        await db.commit()

    # Build subprocess command
    cmd = [uv_cmd, "run", "polymarket", "backtest", "collect", "--job-id", str(job_id)]
    if import_type in ("histories", "histories_filtered"):
        cmd.append("--histories-only")
    if min_volume is not None:
        cmd.extend(["--min-volume", str(min_volume)])

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Update row with PID
    async with aiosqlite.connect(bt_path) as db:
        await db.execute(
            "UPDATE bt_import_jobs SET pid=?, status='running', updated_at=? WHERE id=?",
            (proc.pid, datetime.now(timezone.utc).isoformat(), job_id),
        )
        await db.commit()

    return {"job_id": job_id, "pid": proc.pid}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: int):
    """Cancel a running import job via SIGTERM."""
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return JSONResponse({"ok": False, "reason": "backtest db not available"}, status_code=503)

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_import_jobs"):
            return JSONResponse({"ok": False, "reason": "no jobs table"}, status_code=404)

        row = await conn.execute_fetchone(
            "SELECT id, status, pid, updated_at FROM bt_import_jobs WHERE id=?",
            (job_id,),
        )

    if not row:
        return JSONResponse({"ok": False, "reason": "job not found"}, status_code=404)

    if row["status"] != "running":
        return JSONResponse(
            {"ok": False, "reason": f"job is not running (status={row['status']})"},
            status_code=409,
        )

    age = _heartbeat_age(row["updated_at"])
    if age is not None and age > STALE_SECONDS:
        return JSONResponse(
            {"ok": False, "reason": "job appears stale — heartbeat too old to cancel safely"},
            status_code=409,
        )

    pid = row["pid"]
    if not pid:
        return JSONResponse({"ok": False, "reason": "job has no pid"}, status_code=409)

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return JSONResponse({"ok": False, "reason": "process not found"}, status_code=409)
    except PermissionError:
        return JSONResponse({"ok": False, "reason": "permission denied"}, status_code=403)

    return {"ok": True}
