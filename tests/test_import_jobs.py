"""Tests for import job tracking: schema, collector, and dashboard API endpoints."""

import json
import os
import signal
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bt_db(path: Path) -> None:
    """Initialize a minimal backtest.db with all required tables."""
    from polymarket_agent.backtest.database import init_backtest_db
    init_backtest_db(path)


def _make_dashboard_app(bt_path: Path, uv_cmd: str | None = "/usr/bin/uv") -> FastAPI:
    """Build a minimal FastAPI app for testing data/job endpoints."""
    from polymarket_dashboard.db import BacktestDB
    from polymarket_dashboard.routes import data

    app = FastAPI()
    app.state.db = None
    app.state.backtest_db = BacktestDB.create(bt_path)
    app.state.starting_balance = 1000.0
    app.state.uv_cmd = uv_cmd
    app.state.bt_path = str(bt_path)
    app.include_router(data.router, prefix="/api/data")
    return app


# ---------------------------------------------------------------------------
# 8.1 Schema tests
# ---------------------------------------------------------------------------


class TestSchema:
    def test_bt_import_jobs_table_created(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)

        conn = sqlite3.connect(db)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "bt_import_jobs" in tables
        conn.close()

    def test_bt_import_jobs_columns(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)

        conn = sqlite3.connect(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(bt_import_jobs)")}
        expected = {
            "id", "job_type", "status", "params_json", "pid",
            "started_at", "updated_at", "completed_at",
            "markets_total", "markets_done",
            "histories_total", "histories_done", "histories_skipped",
            "error_msg",
        }
        assert expected.issubset(cols)
        conn.close()

    def test_schema_idempotent(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)
        # Second call must not raise
        _make_bt_db(db)

        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM bt_import_jobs").fetchone()[0]
        assert count == 0
        conn.close()


# ---------------------------------------------------------------------------
# 8.2 Collector: _create_job inserts row and stalifies prior running rows
# ---------------------------------------------------------------------------


class TestCollectorCreateJob:
    def test_create_job_inserts_row(self, tmp_path):
        db = tmp_path / "bt.db"
        from polymarket_agent.backtest.collector import BacktestCollector

        with patch("httpx.Client"):
            collector = BacktestCollector(db_path=db)

        job_id = collector._create_job("full", {})
        assert job_id is not None

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM bt_import_jobs WHERE id=?", (job_id,)).fetchone()
        assert row["job_type"] == "full"
        assert row["status"] == "running"
        assert row["pid"] == os.getpid()
        assert row["params_json"] == "{}"
        conn.close()

    def test_create_job_stalifies_existing_running(self, tmp_path):
        db = tmp_path / "bt.db"
        from polymarket_agent.backtest.collector import BacktestCollector

        with patch("httpx.Client"):
            collector = BacktestCollector(db_path=db)

        # Manually insert a "running" job
        conn = sqlite3.connect(db)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO bt_import_jobs (job_type, status, started_at, updated_at) VALUES (?,?,?,?)",
            ("histories", "running", now, now),
        )
        conn.commit()
        old_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        # Create a new job — old one should become stalled
        collector._create_job("full", {})

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM bt_import_jobs WHERE id=?", (old_id,)).fetchone()
        assert row["status"] == "stalled"
        conn.close()

    def test_create_job_with_existing_job_id(self, tmp_path):
        db = tmp_path / "bt.db"
        from polymarket_agent.backtest.collector import BacktestCollector

        with patch("httpx.Client"):
            collector = BacktestCollector(db_path=db)

        # Pre-insert a row (use 'stalled' since CHECK allows it and simulates a pre-existing row)
        conn = sqlite3.connect(db)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO bt_import_jobs (job_type, status, started_at, updated_at) VALUES (?,?,?,?)",
            ("full", "stalled", now, now),
        )
        conn.commit()
        pre_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        returned_id = collector._create_job("full", {}, job_id=pre_id)
        assert returned_id == pre_id

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, pid FROM bt_import_jobs WHERE id=?", (pre_id,)).fetchone()
        assert row["status"] == "running"
        assert row["pid"] == os.getpid()
        conn.close()


# ---------------------------------------------------------------------------
# 8.3 Collector: _update_job updates counts and updated_at
# ---------------------------------------------------------------------------


class TestCollectorUpdateJob:
    def test_update_job_sets_fields(self, tmp_path):
        db = tmp_path / "bt.db"
        from polymarket_agent.backtest.collector import BacktestCollector

        with patch("httpx.Client"):
            collector = BacktestCollector(db_path=db)

        job_id = collector._create_job("histories", {})

        collector._update_job(histories_done=50, histories_skipped=5)

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM bt_import_jobs WHERE id=?", (job_id,)).fetchone()
        assert row["histories_done"] == 50
        assert row["histories_skipped"] == 5
        assert row["updated_at"] is not None
        conn.close()

    def test_update_job_no_op_when_no_job(self, tmp_path):
        db = tmp_path / "bt.db"
        from polymarket_agent.backtest.collector import BacktestCollector

        with patch("httpx.Client"):
            collector = BacktestCollector(db_path=db)

        # No job created — _update_job should not raise
        collector._update_job(histories_done=10)


# ---------------------------------------------------------------------------
# 8.4 Collector: SIGTERM handler sets status=cancelled
# ---------------------------------------------------------------------------


class TestCollectorSigterm:
    def test_sigterm_sets_cancelled(self, tmp_path):
        db = tmp_path / "bt.db"
        from polymarket_agent.backtest.collector import BacktestCollector

        with patch("httpx.Client"):
            collector = BacktestCollector(db_path=db)

        job_id = collector._create_job("full", {})

        # Invoke the handler directly (simulate SIGTERM without actually killing process)
        # Re-retrieve the installed handler
        handler = signal.getsignal(signal.SIGTERM)

        with pytest.raises(SystemExit):
            handler(signal.SIGTERM, None)

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM bt_import_jobs WHERE id=?", (job_id,)).fetchone()
        assert row["status"] == "cancelled"
        conn.close()

    def test_sigterm_no_job_exits_cleanly(self, tmp_path):
        db = tmp_path / "bt.db"
        from polymarket_agent.backtest.collector import BacktestCollector

        with patch("httpx.Client"):
            collector = BacktestCollector(db_path=db)

        # No job created
        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(SystemExit):
            handler(signal.SIGTERM, None)


# ---------------------------------------------------------------------------
# 8.5 Collector: exception path sets status=failed
# ---------------------------------------------------------------------------


class TestCollectorFailure:
    def test_exception_marks_job_failed(self, tmp_path):
        db = tmp_path / "bt.db"
        from polymarket_agent.backtest.collector import BacktestCollector

        with patch("httpx.Client"):
            collector = BacktestCollector(db_path=db)

        # Patch _collect_markets to raise
        with patch.object(collector, "_collect_markets", side_effect=RuntimeError("network down")):
            with pytest.raises(RuntimeError):
                collector.collect()

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM bt_import_jobs ORDER BY id DESC LIMIT 1").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "failed"
        assert "network down" in rows[0]["error_msg"]
        conn.close()


# ---------------------------------------------------------------------------
# 8.6 API GET /api/data/jobs — stale flag, progress_pct, duration
# ---------------------------------------------------------------------------


class TestJobsListEndpoint:
    def _insert_job(self, db: Path, job_type="full", status="done",
                    histories_done=100, histories_total=200,
                    updated_at_offset_secs=0, pid=None):
        """Helper to insert a job row for testing."""
        conn = sqlite3.connect(db)
        now = datetime.now(timezone.utc)
        started = now.isoformat()
        updated = datetime.fromtimestamp(
            now.timestamp() - updated_at_offset_secs, tz=timezone.utc
        ).isoformat()
        completed = now.isoformat() if status in ("done", "failed") else None
        conn.execute(
            """INSERT INTO bt_import_jobs
               (job_type, status, pid, started_at, updated_at, completed_at,
                histories_total, histories_done, histories_skipped)
               VALUES (?,?,?,?,?,?,?,?,0)""",
            (job_type, status, pid, started, updated, completed,
             histories_total, histories_done),
        )
        conn.commit()
        conn.close()

    def test_jobs_list_returns_jobs(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)
        self._insert_job(db, status="done")

        with TestClient(_make_dashboard_app(db)) as client:
            r = client.get("/api/data/jobs")
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is True
        assert len(data["jobs"]) == 1
        job = data["jobs"][0]
        assert job["status"] == "done"
        assert job["progress_pct"] == 50.0

    def test_jobs_list_stale_flag(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)
        # Insert a running job with heartbeat > 300s ago
        self._insert_job(db, status="running", updated_at_offset_secs=400, pid=99999)

        with TestClient(_make_dashboard_app(db)) as client:
            r = client.get("/api/data/jobs")
        data = r.json()
        assert data["jobs"][0]["stale"] is True

    def test_jobs_list_fresh_running_not_stale(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)
        self._insert_job(db, status="running", updated_at_offset_secs=10, pid=os.getpid())

        with TestClient(_make_dashboard_app(db)) as client:
            r = client.get("/api/data/jobs")
        data = r.json()
        assert data["jobs"][0]["stale"] is False

    def test_jobs_list_available_false_when_no_db(self, tmp_path):
        missing = tmp_path / "missing.db"
        app = _make_dashboard_app(missing, uv_cmd="/usr/bin/uv")
        with TestClient(app) as client:
            r = client.get("/api/data/jobs")
        assert r.status_code == 200
        assert r.json()["available"] is False

    def test_jobs_list_available_false_when_table_missing(self, tmp_path):
        db = tmp_path / "bt.db"
        # Create DB but without bt_import_jobs table
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.close()
        from polymarket_dashboard.db import BacktestDB
        from polymarket_dashboard.routes import data as data_routes
        app = FastAPI()
        app.state.db = None
        app.state.backtest_db = BacktestDB.create(db)
        app.state.uv_cmd = "/usr/bin/uv"
        app.state.bt_path = str(db)
        app.include_router(data_routes.router, prefix="/api/data")

        with TestClient(app) as client:
            r = client.get("/api/data/jobs")
        assert r.json()["available"] is False


# ---------------------------------------------------------------------------
# 8.7 API POST /api/data/import
# ---------------------------------------------------------------------------


class TestImportEndpoint:
    def test_import_409_when_job_running(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)

        # Insert a fresh running job
        conn = sqlite3.connect(db)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO bt_import_jobs (job_type, status, pid, started_at, updated_at) VALUES (?,?,?,?,?)",
            ("full", "running", os.getpid(), now, now),
        )
        conn.commit()
        conn.close()

        with TestClient(_make_dashboard_app(db)) as client:
            r = client.post("/api/data/import", json={"type": "full"})
        assert r.status_code == 409
        assert "already running" in r.json()["error"]

    def test_import_503_when_uv_not_found(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)

        app = _make_dashboard_app(db, uv_cmd=None)
        with TestClient(app) as client:
            r = client.post("/api/data/import", json={"type": "full"})
        assert r.status_code == 503
        assert "uv command not found" in r.json()["error"]

    def test_import_spawns_subprocess(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)

        mock_proc = MagicMock()
        mock_proc.pid = 12345

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            with TestClient(_make_dashboard_app(db)) as client:
                r = client.post("/api/data/import", json={"type": "histories"})

        assert r.status_code == 200
        data = r.json()
        assert "job_id" in data
        assert data["pid"] == 12345
        mock_popen.assert_called_once()

        # Verify job row was created
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM bt_import_jobs ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None
        assert row["pid"] == 12345
        conn.close()

    def test_import_histories_filtered_passes_min_volume(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)

        mock_proc = MagicMock()
        mock_proc.pid = 99

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            with TestClient(_make_dashboard_app(db)) as client:
                r = client.post("/api/data/import", json={"type": "histories_filtered", "min_volume": 100000})

        assert r.status_code == 200
        cmd = mock_popen.call_args[0][0]
        assert "--histories-only" in cmd
        assert "--min-volume" in cmd
        assert "100000" in cmd


# ---------------------------------------------------------------------------
# 8.8 API POST /api/data/jobs/{id}/cancel
# ---------------------------------------------------------------------------


class TestCancelEndpoint:
    def _insert_running_job(self, db: Path, pid: int, fresh: bool = True) -> int:
        conn = sqlite3.connect(db)
        now = datetime.now(timezone.utc)
        offset = 10 if fresh else 400
        updated = datetime.fromtimestamp(
            now.timestamp() - offset, tz=timezone.utc
        ).isoformat()
        conn.execute(
            """INSERT INTO bt_import_jobs
               (job_type, status, pid, started_at, updated_at)
               VALUES (?,?,?,?,?)""",
            ("full", "running", pid, now.isoformat(), updated),
        )
        conn.commit()
        job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return job_id

    def test_cancel_stale_job_returns_409(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)
        job_id = self._insert_running_job(db, pid=os.getpid(), fresh=False)

        with TestClient(_make_dashboard_app(db)) as client:
            r = client.post(f"/api/data/jobs/{job_id}/cancel")
        assert r.status_code == 409
        assert "stale" in r.json()["reason"]

    def test_cancel_non_running_job_returns_409(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)

        conn = sqlite3.connect(db)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO bt_import_jobs (job_type, status, pid, started_at, updated_at) VALUES (?,?,?,?,?)",
            ("full", "done", os.getpid(), now, now),
        )
        conn.commit()
        job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        with TestClient(_make_dashboard_app(db)) as client:
            r = client.post(f"/api/data/jobs/{job_id}/cancel")
        assert r.status_code == 409
        assert "not running" in r.json()["reason"]

    def test_cancel_sends_sigterm(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)
        job_id = self._insert_running_job(db, pid=os.getpid(), fresh=True)

        with patch("os.kill") as mock_kill:
            with TestClient(_make_dashboard_app(db)) as client:
                r = client.post(f"/api/data/jobs/{job_id}/cancel")

        assert r.status_code == 200
        assert r.json()["ok"] is True
        mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)

    def test_cancel_process_not_found_returns_409(self, tmp_path):
        db = tmp_path / "bt.db"
        _make_bt_db(db)
        job_id = self._insert_running_job(db, pid=999999, fresh=True)

        with patch("os.kill", side_effect=ProcessLookupError):
            with TestClient(_make_dashboard_app(db)) as client:
                r = client.post(f"/api/data/jobs/{job_id}/cancel")
        assert r.status_code == 409
