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
