"""Tests for /api/data/* endpoints — backtest corpus visualization."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _create_test_bt_db(path: Path):
    """Create a minimal backtest.db with bt_markets and bt_regimes for testing."""
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE bt_markets (
        id TEXT PRIMARY KEY,
        question TEXT,
        category TEXT,
        end_date TEXT,
        volume REAL,
        has_history INTEGER DEFAULT 0,
        resolution_outcome TEXT
    )""")
    conn.execute("""CREATE TABLE bt_regimes (
        name TEXT PRIMARY KEY,
        start_date TEXT,
        end_date TEXT
    )""")
    # Markets spanning categories, volumes, dates
    markets = [
        ("m1", "Q1", "politics", "2023-06-01", 500_000, 1),
        ("m2", "Q2", "politics", "2023-09-01", 200_000, 1),
        ("m3", "Q3", "sports",   "2023-03-01",  50_000, 0),
        ("m4", "Q4", "crypto",   "2024-01-01", 2_000_000, 1),
        ("m5", "Q5", None,       "2024-06-01",   5_000, 0),
        ("m6", "Q6", "sports",   "2024-03-01", 15_000_000, 1),
    ]
    conn.executemany(
        "INSERT INTO bt_markets VALUES (?,?,?,?,?,?,NULL)", markets
    )
    regimes = [
        ("GPT4-era", "2023-03-14", "2024-03-04"),
        ("GPT4o-era", "2024-05-13", "2024-09-12"),
    ]
    conn.executemany("INSERT INTO bt_regimes VALUES (?,?,?)", regimes)
    conn.commit()
    conn.close()


@pytest.fixture()
def client_with_db(tmp_path):
    db = tmp_path / "test_bt.db"
    _create_test_bt_db(db)

    from polymarket_dashboard.app import create_app
    from polymarket_dashboard.db import BacktestDB, DashboardDB

    app = create_app.__wrapped__(db_path=None, backtest_db_path=db) if hasattr(create_app, '__wrapped__') else None

    # Build app manually to avoid DashboardDB failing on missing agent db
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from polymarket_dashboard.routes import (
        calibration, data, evaluation, hypotheses, metrics, operations, portfolio, positions
    )

    app = FastAPI(title="Test Dashboard")
    app.state.db = None
    app.state.backtest_db = BacktestDB.create(db)
    app.state.starting_balance = 1000.0

    app.include_router(data.router, prefix="/api/data", tags=["data"])

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client_no_db(tmp_path):
    missing = tmp_path / "nonexistent.db"

    from fastapi import FastAPI
    from polymarket_dashboard.db import BacktestDB
    from polymarket_dashboard.routes import data

    app = FastAPI(title="Test Dashboard No DB")
    app.state.db = None
    app.state.backtest_db = BacktestDB.create(missing)  # returns None
    app.state.starting_balance = 1000.0
    app.include_router(data.router, prefix="/api/data", tags=["data"])

    with TestClient(app) as c:
        yield c


class TestDataSummary:
    """5.1: Test GET /api/data/summary with test backtest.db fixture."""

    def test_summary_available(self, client_with_db):
        resp = client_with_db.get("/api/data/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        for key in ("total_markets", "with_history", "coverage_pct",
                    "date_range_start", "date_range_end", "category_count",
                    "volume_min", "volume_max"):
            assert key in data, f"Missing key: {key}"

    def test_summary_values(self, client_with_db):
        data = client_with_db.get("/api/data/summary").json()
        assert data["total_markets"] == 6
        assert data["with_history"] == 4
        assert round(data["coverage_pct"], 1) == round(4 / 6 * 100, 1)


class TestDataByCategory:
    """5.2: Test GET /api/data/by-category returns list with required fields."""

    def test_by_category_fields(self, client_with_db):
        resp = client_with_db.get("/api/data/by-category")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert len(data["categories"]) > 0
        for cat in data["categories"]:
            assert "category" in cat
            assert "total" in cat
            assert "with_history" in cat

    def test_null_category_becomes_unknown(self, client_with_db):
        names = [c["category"] for c in client_with_db.get("/api/data/by-category").json()["categories"]]
        assert "unknown" in names

    def test_ordered_by_total_desc(self, client_with_db):
        totals = [c["total"] for c in client_with_db.get("/api/data/by-category").json()["categories"]]
        assert totals == sorted(totals, reverse=True)


class TestDataByVolumeTier:
    """5.3: Test GET /api/data/by-volume-tier returns all 5 tier labels."""

    def test_volume_tier_fields(self, client_with_db):
        resp = client_with_db.get("/api/data/by-volume-tier")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        for tier in data["tiers"]:
            assert "tier" in tier
            assert "total" in tier
            assert "with_history" in tier

    def test_all_five_tier_labels(self, client_with_db):
        labels = {t["tier"] for t in client_with_db.get("/api/data/by-volume-tier").json()["tiers"]}
        expected = {"<$10K", "$10K-$100K", "$100K-$1M", "$1M-$10M", ">$10M"}
        assert labels == expected

    def test_tier_ordering(self, client_with_db):
        tier_order = ["<$10K", "$10K-$100K", "$100K-$1M", "$1M-$10M", ">$10M"]
        returned = [t["tier"] for t in client_with_db.get("/api/data/by-volume-tier").json()["tiers"]]
        assert returned == tier_order


class TestDataTemporal:
    """5.4: Test GET /api/data/temporal returns months list and regimes list."""

    def test_temporal_fields(self, client_with_db):
        resp = client_with_db.get("/api/data/temporal")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert "months" in data
        assert "regimes" in data

    def test_months_have_required_fields(self, client_with_db):
        for m in client_with_db.get("/api/data/temporal").json()["months"]:
            assert "month" in m
            assert "total" in m
            assert "with_history" in m

    def test_regimes_returned(self, client_with_db):
        regimes = client_with_db.get("/api/data/temporal").json()["regimes"]
        assert len(regimes) == 2
        assert regimes[0]["name"] == "GPT4-era"
        for r in regimes:
            assert "name" in r and "start_date" in r and "end_date" in r

    def test_months_ordered_asc(self, client_with_db):
        months = [m["month"] for m in client_with_db.get("/api/data/temporal").json()["months"]]
        assert months == sorted(months)


class TestDataMissingDB:
    """5.5: All endpoints return {"available": false} when backtest.db is missing."""

    def test_summary_no_db(self, client_no_db):
        resp = client_no_db.get("/api/data/summary")
        assert resp.status_code == 200
        assert resp.json()["available"] is False

    def test_by_category_no_db(self, client_no_db):
        resp = client_no_db.get("/api/data/by-category")
        assert resp.status_code == 200
        assert resp.json()["available"] is False

    def test_by_volume_tier_no_db(self, client_no_db):
        resp = client_no_db.get("/api/data/by-volume-tier")
        assert resp.status_code == 200
        assert resp.json()["available"] is False

    def test_temporal_no_db(self, client_no_db):
        resp = client_no_db.get("/api/data/temporal")
        assert resp.status_code == 200
        assert resp.json()["available"] is False


# ---------------------------------------------------------------------------
# Task 7.1 — BacktestDB.create() soft-failure behaviour
# ---------------------------------------------------------------------------

class TestBacktestDBCreate:
    """7.1: BacktestDB.create() returns None for missing file, instance for existing."""

    def test_backtest_db_create_returns_none_for_missing_file(self, tmp_path):
        from polymarket_dashboard.db import BacktestDB

        missing = tmp_path / "does_not_exist.db"
        result = BacktestDB.create(missing)
        assert result is None

    def test_backtest_db_create_returns_instance_when_file_exists(self, tmp_path):
        from polymarket_dashboard.db import BacktestDB

        db_path = tmp_path / "real.db"
        db_path.touch()
        result = BacktestDB.create(db_path)
        assert result is not None
        assert isinstance(result, BacktestDB)


# ---------------------------------------------------------------------------
# Task 7.2 — Evaluation API endpoints with a test backtest.db fixture
# ---------------------------------------------------------------------------

def _create_test_eval_bt_db(path: Path):
    """Create a minimal backtest.db with simulation runs and trials for testing."""
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE bt_simulation_runs (
        id INTEGER PRIMARY KEY,
        started_at TEXT,
        completed_at TEXT,
        config TEXT,
        market_count INTEGER,
        agent_brier REAL,
        market_brier REAL,
        simulated_pnl REAL,
        total_cost REAL
    )""")
    conn.execute("""CREATE TABLE bt_simulation_trials (
        id INTEGER PRIMARY KEY,
        run_id INTEGER,
        market_id TEXT,
        agent_brier REAL,
        market_brier REAL,
        simulated_trade TEXT,
        agent_estimate REAL,
        market_price_at_horizon REAL,
        outcome TEXT,
        edge REAL,
        model TEXT,
        llm_cost REAL,
        training_recency_score REAL
    )""")
    conn.execute("""CREATE TABLE bt_markets (
        id TEXT PRIMARY KEY,
        question TEXT,
        category TEXT,
        end_date TEXT,
        volume REAL,
        has_history INTEGER DEFAULT 0,
        resolution_outcome TEXT
    )""")
    # Insert 1 run row
    conn.execute(
        """INSERT INTO bt_simulation_runs
           (id, started_at, completed_at, config, market_count, agent_brier, market_brier, simulated_pnl, total_cost)
           VALUES (1, '2024-01-01T00:00:00', '2024-01-01T01:00:00', '{"model": "haiku"}', 2, 0.15, 0.18, 5.0, 0.01)"""
    )
    # Insert supporting market rows (needed for the trials JOIN)
    conn.execute("INSERT INTO bt_markets VALUES ('mkt1', 'Will X happen?', 'politics', '2024-01-15', 500000, 1, NULL)")
    conn.execute("INSERT INTO bt_markets VALUES ('mkt2', 'Will Y happen?', 'sports', '2024-02-01', 200000, 1, NULL)")
    # Insert 2 trial rows
    conn.execute(
        """INSERT INTO bt_simulation_trials
           (id, run_id, market_id, agent_brier, market_brier, simulated_trade,
            agent_estimate, market_price_at_horizon, outcome, edge, model, llm_cost, training_recency_score)
           VALUES (1, 1, 'mkt1', 0.12, 0.16, NULL, 0.65, 0.70, 'YES', 0.05, 'haiku', 0.001, 0.5)"""
    )
    conn.execute(
        """INSERT INTO bt_simulation_trials
           (id, run_id, market_id, agent_brier, market_brier, simulated_trade,
            agent_estimate, market_price_at_horizon, outcome, edge, model, llm_cost, training_recency_score)
           VALUES (2, 1, 'mkt2', 0.18, 0.20, NULL, 0.40, 0.45, 'NO', 0.02, 'haiku', 0.001, 0.6)"""
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def client_eval_with_db(tmp_path):
    db = tmp_path / "test_eval_bt.db"
    _create_test_eval_bt_db(db)

    from fastapi import FastAPI
    from polymarket_dashboard.db import BacktestDB
    from polymarket_dashboard.routes import evaluation

    app = FastAPI(title="Test Evaluation Dashboard")
    app.state.db = None
    app.state.backtest_db = BacktestDB.create(db)
    app.state.starting_balance = 1000.0

    app.include_router(evaluation.router, prefix="/api/evaluation", tags=["evaluation"])

    with TestClient(app) as c:
        yield c


class TestEvaluationRuns:
    """7.2: GET /api/evaluation/runs returns 200 with runs list."""

    def test_runs_returns_200(self, client_eval_with_db):
        resp = client_eval_with_db.get("/api/evaluation/runs")
        assert resp.status_code == 200

    def test_runs_available_true(self, client_eval_with_db):
        data = client_eval_with_db.get("/api/evaluation/runs").json()
        assert data["available"] is True

    def test_runs_contains_one_run(self, client_eval_with_db):
        data = client_eval_with_db.get("/api/evaluation/runs").json()
        assert len(data["runs"]) == 1

    def test_run_has_required_fields(self, client_eval_with_db):
        run = client_eval_with_db.get("/api/evaluation/runs").json()["runs"][0]
        for key in ("id", "started_at", "completed_at", "model", "market_count",
                    "trial_count", "agent_brier", "market_brier", "brier_diff",
                    "simulated_pnl", "total_cost", "valid_trials", "trade_count"):
            assert key in run, f"Missing key: {key}"

    def test_run_brier_diff_computed(self, client_eval_with_db):
        run = client_eval_with_db.get("/api/evaluation/runs").json()["runs"][0]
        assert run["brier_diff"] is not None
        assert abs(run["brier_diff"] - round(0.15 - 0.18, 4)) < 1e-6

    def test_runs_no_db_returns_available_false(self, tmp_path):
        from fastapi import FastAPI
        from polymarket_dashboard.db import BacktestDB
        from polymarket_dashboard.routes import evaluation

        app = FastAPI(title="Test Eval No DB")
        app.state.db = None
        app.state.backtest_db = BacktestDB.create(tmp_path / "missing.db")
        app.state.starting_balance = 1000.0
        app.include_router(evaluation.router, prefix="/api/evaluation", tags=["evaluation"])

        with TestClient(app) as c:
            data = c.get("/api/evaluation/runs").json()
        assert data["available"] is False
        assert data["runs"] == []


# ---------------------------------------------------------------------------
# Task 7.3 — Hypotheses API graceful degradation
# ---------------------------------------------------------------------------

@pytest.fixture()
def client_hypotheses_no_bt_db(tmp_path):
    """Fixture: bt_db is None (file does not exist)."""
    from fastapi import FastAPI
    from polymarket_dashboard.db import BacktestDB
    from polymarket_dashboard.routes import hypotheses

    app = FastAPI(title="Test Hypotheses No DB")
    app.state.db = None
    app.state.backtest_db = BacktestDB.create(tmp_path / "missing.db")  # returns None
    app.state.starting_balance = 1000.0
    app.include_router(hypotheses.router, prefix="/api/hypotheses", tags=["hypotheses"])

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client_hypotheses_no_tables(tmp_path):
    """Fixture: DB exists but bt_hypotheses table does not exist."""
    db_path = tmp_path / "empty_bt.db"
    # Create a DB with only bt_markets (no hypothesis tables)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE bt_markets (
        id TEXT PRIMARY KEY,
        question TEXT,
        category TEXT,
        end_date TEXT,
        volume REAL,
        has_history INTEGER DEFAULT 0,
        resolution_outcome TEXT
    )""")
    conn.commit()
    conn.close()

    from fastapi import FastAPI
    from polymarket_dashboard.db import BacktestDB
    from polymarket_dashboard.routes import hypotheses

    app = FastAPI(title="Test Hypotheses No Tables")
    app.state.db = None
    app.state.backtest_db = BacktestDB.create(db_path)
    app.state.starting_balance = 1000.0
    app.include_router(hypotheses.router, prefix="/api/hypotheses", tags=["hypotheses"])

    with TestClient(app) as c:
        yield c


class TestHypothesesGracefulDegradation:
    """7.3: /api/hypotheses/list degrades gracefully when DB or tables are absent."""

    def test_no_bt_db_returns_available_false(self, client_hypotheses_no_bt_db):
        resp = client_hypotheses_no_bt_db.get("/api/hypotheses/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert data["tables_exist"] is False
        assert data["hypotheses"] == []

    def test_db_exists_no_tables_returns_available_true_tables_false(
        self, client_hypotheses_no_tables
    ):
        resp = client_hypotheses_no_tables.get("/api/hypotheses/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["tables_exist"] is False
        assert data["hypotheses"] == []


# ---------------------------------------------------------------------------
# Task 7.4 — create_app() mounts evaluation and hypotheses routers
# ---------------------------------------------------------------------------

class TestCreateAppRouters:
    """7.4: create_app() includes evaluation and hypotheses routers."""

    def test_create_app_includes_evaluation_and_hypotheses_routers(self, tmp_path):
        # create_app calls DashboardDB(path) which raises on missing file,
        # so we provide a minimal agent db file.
        agent_db = tmp_path / "agent.db"
        conn = sqlite3.connect(agent_db)
        conn.commit()
        conn.close()

        from polymarket_dashboard.app import create_app

        app = create_app(db_path=agent_db, backtest_db_path=tmp_path / "nonexistent.db")
        routes = {route.path for route in app.routes}
        assert any("/api/evaluation" in p for p in routes)
        assert any("/api/hypotheses" in p for p in routes)


# ---------------------------------------------------------------------------
# Task 7.5 — Smoke test: dashboard root serves content (no 500)
# ---------------------------------------------------------------------------

class TestDashboardRootSmoke:
    """7.5: The dashboard root URL does not return a 500 error."""

    def test_dashboard_root_serves_content(self, tmp_path):
        agent_db = tmp_path / "agent.db"
        conn = sqlite3.connect(agent_db)
        conn.commit()
        conn.close()

        from polymarket_dashboard.app import create_app

        app = create_app(db_path=agent_db, backtest_db_path=tmp_path / "nonexistent.db")
        with TestClient(app) as client:
            # Either root serves HTML or 404 if no static files in test env — not a 500
            response = client.get("/", follow_redirects=True)
            assert response.status_code in (200, 404)
            assert response.status_code != 500
