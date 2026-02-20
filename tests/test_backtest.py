"""Tests for backtest module: database, collector, analysis, strategy, and integration."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

TEST_BACKTEST_DB = Path("/tmp/test_backtest.db")
TEST_STRATEGY_PATH = Path("/tmp/test_strategy.yaml")


@pytest.fixture(autouse=True)
def setup_test_paths(monkeypatch):
    """Use temp files for all tests."""
    monkeypatch.setattr("polymarket_agent.config.settings.backtest_db_path", TEST_BACKTEST_DB)
    monkeypatch.setattr("polymarket_agent.config.settings.strategy_config_path", TEST_STRATEGY_PATH)
    monkeypatch.setattr("polymarket_agent.config.settings.db_path", Path("/tmp/test_polymarket_agent_bt.db"))
    yield
    for p in [TEST_BACKTEST_DB, TEST_STRATEGY_PATH, Path("/tmp/test_polymarket_agent_bt.db")]:
        if p.exists():
            p.unlink()


# ---------------------------------------------------------------------------
# 8.1 Test backtest DB initialization
# ---------------------------------------------------------------------------


class TestBacktestDatabase:
    def test_init_creates_tables(self):
        """Schema created with all expected tables."""
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = {r["name"] for r in tables}

        assert "bt_markets" in table_names
        assert "bt_price_history" in table_names
        assert "bt_regimes" in table_names

    def test_regimes_seeded(self):
        """Regimes table contains all expected model release boundaries."""
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            rows = conn.execute("SELECT name, start_date, end_date FROM bt_regimes ORDER BY start_date").fetchall()

        names = [r["name"] for r in rows]
        assert "pre-GPT4" in names
        assert "GPT4-era" in names
        assert "Claude3-era" in names
        assert "GPT4o-era" in names
        assert "o1-era" in names
        assert "post-Claude4" in names

        # post-Claude4 should have no end date
        post_claude4 = [r for r in rows if r["name"] == "post-Claude4"][0]
        assert post_claude4["end_date"] is None

    def test_init_idempotent(self):
        """Running init twice doesn't fail or duplicate data."""
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)
        init_backtest_db(TEST_BACKTEST_DB)

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM bt_regimes").fetchone()["c"]
        assert count == 6


# ---------------------------------------------------------------------------
# 8.2 Test collector
# ---------------------------------------------------------------------------


class TestCollector:
    def _make_gamma_market(self, market_id="m1", question="Test?", volume=1000,
                           category="crypto", yes_token="tok_yes", no_token="tok_no",
                           end_date="2024-06-01T00:00:00Z"):
        return {
            "id": market_id,
            "question": question,
            "description": "A test market",
            "volumeNum": volume,
            "liquidity": 500,
            "endDate": end_date,
            "resolutionSource": "YES",
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": json.dumps([yes_token, no_token]),
            "tags": [{"label": category}],
            "events": [{"id": f"evt_{market_id}"}],
            "closed": True,
        }

    def _make_price_history(self, days=30, start_price=0.3, end_price=0.9):
        """Generate synthetic price history with timestamps."""
        history = []
        base_ts = int(datetime(2024, 5, 1, tzinfo=timezone.utc).timestamp())
        for i in range(days):
            t = base_ts + i * 86400
            p = start_price + (end_price - start_price) * (i / max(days - 1, 1))
            history.append({"t": t, "p": round(p, 4)})
        return history

    def test_upsert_market(self):
        """Market upserted correctly, metadata updated on conflict."""
        from polymarket_agent.backtest.collector import BacktestCollector
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)

        # Mock the httpx clients to avoid real API calls
        with patch("polymarket_agent.backtest.collector.httpx.Client"):
            collector = BacktestCollector(db_path=TEST_BACKTEST_DB)

        item = self._make_gamma_market()
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            assert collector._upsert_market(conn, item) is True

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            row = conn.execute("SELECT * FROM bt_markets WHERE id = 'm1'").fetchone()
        assert row is not None
        assert row["question"] == "Test?"
        assert row["category"] == "crypto"
        assert row["yes_token"] == "tok_yes"

        # Upsert again with different volume
        item["volumeNum"] = 9999
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            collector._upsert_market(conn, item)

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            row = conn.execute("SELECT volume FROM bt_markets WHERE id = 'm1'").fetchone()
        assert row["volume"] == 9999

        collector.close()

    def test_market_without_clob_tokens(self):
        """Market with no tokens is stored but flagged."""
        from polymarket_agent.backtest.collector import BacktestCollector
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)

        with patch("polymarket_agent.backtest.collector.httpx.Client"):
            collector = BacktestCollector(db_path=TEST_BACKTEST_DB)

        item = self._make_gamma_market(yes_token=None, no_token=None)
        item["clobTokenIds"] = "[]"
        item["outcomes"] = "[]"

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            collector._upsert_market(conn, item)

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            row = conn.execute("SELECT yes_token, no_token FROM bt_markets WHERE id = 'm1'").fetchone()
        assert row["yes_token"] is None

        collector.close()


# ---------------------------------------------------------------------------
# 8.3 Test load_markets() filtering
# ---------------------------------------------------------------------------


class TestLoadMarkets:
    def _seed_markets(self, count=5):
        """Seed test markets with price histories."""
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)

        categories = ["crypto", "politics", "science", "crypto", "politics"]
        volumes = [100000, 50000, 10000, 200000, 5000]
        end_dates = [
            "2024-01-15T00:00:00Z",  # pre-GPT4 boundary area
            "2023-06-01T00:00:00Z",  # GPT4-era
            "2024-04-01T00:00:00Z",  # Claude3-era
            "2024-08-01T00:00:00Z",  # GPT4o-era
            "2024-10-01T00:00:00Z",  # o1-era
        ]

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            for i in range(count):
                conn.execute(
                    """INSERT INTO bt_markets (id, question, category, end_date, volume,
                        liquidity, resolution_outcome, has_history, collected_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'YES', 1, ?)""",
                    (f"m{i}", f"Q{i}?", categories[i], end_dates[i], volumes[i], 1000,
                     datetime.now(timezone.utc).isoformat()),
                )
                # Add price history
                base_ts = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
                for d in range(10):
                    conn.execute(
                        "INSERT INTO bt_price_history (market_id, timestamp, price) VALUES (?, ?, ?)",
                        (f"m{i}", base_ts + d * 86400, 0.5 + d * 0.05),
                    )

    def test_load_all(self):
        from polymarket_agent.backtest.analysis import load_markets

        self._seed_markets()
        markets = load_markets(db_path=TEST_BACKTEST_DB)
        assert len(markets) == 5
        assert all(m["price_history"] for m in markets)

    def test_filter_by_category(self):
        from polymarket_agent.backtest.analysis import load_markets

        self._seed_markets()
        markets = load_markets(category="crypto", db_path=TEST_BACKTEST_DB)
        assert len(markets) == 2
        assert all(m["category"] == "crypto" for m in markets)

    def test_filter_by_volume_range(self):
        from polymarket_agent.backtest.analysis import load_markets

        self._seed_markets()
        markets = load_markets(volume_min=50000, volume_max=200000, db_path=TEST_BACKTEST_DB)
        assert all(50000 <= m["volume"] <= 200000 for m in markets)

    def test_filter_by_regime(self):
        from polymarket_agent.backtest.analysis import load_markets

        self._seed_markets()
        markets = load_markets(regime="GPT4o-era", db_path=TEST_BACKTEST_DB)
        # GPT4o-era: 2024-05-13 to 2024-09-12
        # Only m3 (2024-08-01) falls in this range
        assert len(markets) == 1
        assert markets[0]["id"] == "m3"


# ---------------------------------------------------------------------------
# 8.4 Test efficiency_index()
# ---------------------------------------------------------------------------


class TestEfficiencyIndex:
    def _make_market(self, market_id, outcome, price_at_horizon, end_date="2024-06-01T00:00:00Z"):
        """Create a market with price history at known horizons."""
        res_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        history = []
        # Place price at various horizons
        for horizon in [30, 7, 1]:
            ts = int((res_dt - timedelta(days=horizon)).timestamp())
            # Use the specified price for horizon=7, offset slightly for others
            if horizon == 7:
                history.append({"t": ts, "p": price_at_horizon})
            elif horizon == 30:
                history.append({"t": ts, "p": price_at_horizon - 0.1})
            else:
                history.append({"t": ts, "p": price_at_horizon + 0.05})

        return {
            "id": market_id,
            "question": f"Market {market_id}",
            "category": "test",
            "end_date": end_date,
            "resolution_outcome": "YES" if outcome == 1.0 else "NO",
            "price_history": history,
        }

    def test_efficiency_known_values(self):
        from polymarket_agent.backtest.analysis import efficiency_index

        # Market resolved YES (1.0), price at 7d was 0.7
        # Expected deviation at 7d: |0.7 - 1.0| = 0.3
        markets = [
            self._make_market("m1", 1.0, 0.7),
            self._make_market("m2", 0.0, 0.3),  # NO outcome, price at 7d = 0.3, dev = |0.3 - 0.0| = 0.3
        ]

        result = efficiency_index(markets, horizons=[7])
        assert result[7]["count"] == 2
        assert abs(result[7]["efficiency"] - 0.3) < 0.01

    def test_efficiency_multiple_horizons(self):
        from polymarket_agent.backtest.analysis import efficiency_index

        markets = [self._make_market("m1", 1.0, 0.7)]
        result = efficiency_index(markets, horizons=[30, 7, 1])

        # 30d price = 0.6, dev = |0.6 - 1.0| = 0.4
        # 7d price = 0.7, dev = |0.7 - 1.0| = 0.3
        # 1d price = 0.75, dev = |0.75 - 1.0| = 0.25
        assert result[30]["efficiency"] is not None
        assert result[7]["efficiency"] is not None
        assert result[1]["efficiency"] is not None
        # Markets should become more efficient closer to resolution
        assert result[1]["efficiency"] < result[7]["efficiency"]


# ---------------------------------------------------------------------------
# 8.5 Test category_calibration()
# ---------------------------------------------------------------------------


class TestCategoryCalibration:
    def _make_market(self, market_id, category, outcome, final_price):
        return {
            "id": market_id,
            "question": f"Q {market_id}",
            "category": category,
            "resolution_outcome": "YES" if outcome == 1.0 else "NO",
            "price_history": [{"t": 1000000, "p": final_price}],
        }

    def test_detects_bullish_bias(self):
        from polymarket_agent.backtest.analysis import category_calibration

        # Crypto markets priced high but resolve NO
        markets = [
            self._make_market("m1", "crypto", 0.0, 0.7),
            self._make_market("m2", "crypto", 0.0, 0.6),
            self._make_market("m3", "crypto", 1.0, 0.8),
        ]

        result = category_calibration(markets)
        assert "crypto" in result
        # avg_price = (0.7 + 0.6 + 0.8) / 3 = 0.7
        # avg_outcome = (0 + 0 + 1) / 3 = 0.333
        # bias = 0.7 - 0.333 = 0.367 (bullish)
        assert result["crypto"]["bias"] > 0.3
        assert result["crypto"]["count"] == 3

    def test_well_calibrated(self):
        from polymarket_agent.backtest.analysis import category_calibration

        # Balanced outcomes
        markets = [
            self._make_market("m1", "science", 1.0, 0.5),
            self._make_market("m2", "science", 0.0, 0.5),
        ]

        result = category_calibration(markets)
        assert abs(result["science"]["bias"]) < 0.01


# ---------------------------------------------------------------------------
# 8.6 Test price_momentum()
# ---------------------------------------------------------------------------


class TestPriceMomentum:
    def _make_market_with_trajectory(self, market_id, outcome, prices_over_time):
        """Create a market with a known price trajectory.

        prices_over_time: list of (days_before_resolution, price).
        """
        res_dt = datetime(2024, 6, 1, tzinfo=timezone.utc)
        history = []
        for days_before, price in prices_over_time:
            ts = int((res_dt - timedelta(days=days_before)).timestamp())
            history.append({"t": ts, "p": price})

        return {
            "id": market_id,
            "question": f"Q {market_id}",
            "category": "test",
            "end_date": "2024-06-01T00:00:00Z",
            "resolution_outcome": "YES" if outcome == 1.0 else "NO",
            "price_history": sorted(history, key=lambda h: h["t"]),
        }

    def test_upward_momentum(self):
        from polymarket_agent.backtest.analysis import price_momentum

        # Price goes from 0.3 to 0.6 over 7-day lookback, measured at 7 days before resolution
        market = self._make_market_with_trajectory("m1", 1.0, [
            (14, 0.3),  # 14 days before = start of lookback
            (7, 0.6),   # 7 days before = end of lookback / measurement point
        ])

        result = price_momentum([market], lookback_days=7, horizon=7)
        assert len(result) == 1
        assert result[0]["momentum"] > 0.2  # 0.6 - 0.3 = 0.3

    def test_downward_momentum(self):
        from polymarket_agent.backtest.analysis import price_momentum

        market = self._make_market_with_trajectory("m1", 0.0, [
            (14, 0.7),
            (7, 0.3),
        ])

        result = price_momentum([market], lookback_days=7, horizon=7)
        assert len(result) == 1
        assert result[0]["momentum"] < -0.3


# ---------------------------------------------------------------------------
# 8.7 Test cross_market_arbitrage()
# ---------------------------------------------------------------------------


class TestCrossMarketArbitrage:
    def test_overpriced_event(self):
        from polymarket_agent.backtest.analysis import cross_market_arbitrage

        # Event with 3 markets summing to 1.15
        markets = [
            {"id": "m1", "event_id": "evt1", "resolution_outcome": "YES",
             "price_history": [{"t": 1000, "p": 0.45}]},
            {"id": "m2", "event_id": "evt1", "resolution_outcome": "NO",
             "price_history": [{"t": 1000, "p": 0.40}]},
            {"id": "m3", "event_id": "evt1", "resolution_outcome": "NO",
             "price_history": [{"t": 1000, "p": 0.30}]},
        ]

        result = cross_market_arbitrage(markets)
        assert len(result) == 1
        assert result[0]["event_id"] == "evt1"
        assert result[0]["market_count"] == 3
        assert abs(result[0]["price_sum"] - 1.15) < 0.01
        assert abs(result[0]["deviation"] - 0.15) < 0.01

    def test_single_market_event_skipped(self):
        from polymarket_agent.backtest.analysis import cross_market_arbitrage

        markets = [
            {"id": "m1", "event_id": "evt1", "resolution_outcome": "YES",
             "price_history": [{"t": 1000, "p": 0.50}]},
        ]

        result = cross_market_arbitrage(markets)
        assert len(result) == 0

    def test_no_event_id_skipped(self):
        from polymarket_agent.backtest.analysis import cross_market_arbitrage

        markets = [
            {"id": "m1", "event_id": None, "resolution_outcome": "YES",
             "price_history": [{"t": 1000, "p": 0.50}]},
        ]

        result = cross_market_arbitrage(markets)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# 8.8 Test regime_comparison()
# ---------------------------------------------------------------------------


class TestRegimeComparison:
    def test_runs_fn_per_regime(self):
        from polymarket_agent.backtest.analysis import regime_comparison
        from polymarket_agent.backtest.database import init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)

        # Simple analysis function that counts markets
        def count_fn(markets):
            return {"count": len(markets)}

        result = regime_comparison(count_fn, db_path=TEST_BACKTEST_DB)

        # Should have an entry for each regime
        assert "pre-GPT4" in result
        assert "GPT4-era" in result
        assert "o1-era" in result
        assert "post-Claude4" in result

        # All counts should be 0 since we didn't seed data
        for regime, data in result.items():
            assert data["count"] == 0


# ---------------------------------------------------------------------------
# 8.9 Test market_baseline_brier()
# ---------------------------------------------------------------------------


class TestMarketBaselineBrier:
    def test_hand_computed_brier(self):
        from polymarket_agent.backtest.analysis import market_baseline_brier

        res_dt = datetime(2024, 6, 1, tzinfo=timezone.utc)
        ts_7d = int((res_dt - timedelta(days=7)).timestamp())

        markets = [
            {
                "id": "m1",
                "end_date": "2024-06-01T00:00:00Z",
                "resolution_outcome": "YES",
                "price_history": [{"t": ts_7d, "p": 0.8}],
            },
            {
                "id": "m2",
                "end_date": "2024-06-01T00:00:00Z",
                "resolution_outcome": "NO",
                "price_history": [{"t": ts_7d, "p": 0.2}],
            },
        ]

        result = market_baseline_brier(markets, horizon=7)

        # m1: (0.8 - 1.0)^2 = 0.04
        # m2: (0.2 - 0.0)^2 = 0.04
        # mean = 0.04
        assert result["count"] == 2
        assert abs(result["brier_score"] - 0.04) < 0.001

    def test_perfect_predictions(self):
        from polymarket_agent.backtest.analysis import market_baseline_brier

        res_dt = datetime(2024, 6, 1, tzinfo=timezone.utc)
        ts_7d = int((res_dt - timedelta(days=7)).timestamp())

        markets = [
            {
                "id": "m1",
                "end_date": "2024-06-01T00:00:00Z",
                "resolution_outcome": "YES",
                "price_history": [{"t": ts_7d, "p": 1.0}],
            },
        ]

        result = market_baseline_brier(markets, horizon=7)
        assert result["brier_score"] == 0.0

    def test_no_data_returns_none(self):
        from polymarket_agent.backtest.analysis import market_baseline_brier

        markets = [
            {"id": "m1", "end_date": "2024-06-01", "resolution_outcome": "YES", "price_history": []},
        ]
        result = market_baseline_brier(markets, horizon=7)
        assert result["brier_score"] is None
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# 8.10 Test strategy config
# ---------------------------------------------------------------------------


class TestStrategyConfig:
    def test_load_missing_returns_defaults(self):
        from polymarket_agent.backtest.strategy import load_strategy_config

        config = load_strategy_config(TEST_STRATEGY_PATH)
        assert config["version"] == 1
        assert config["market_selection"]["target_categories"] == []
        assert config["edge_thresholds"]["default"] == 0.10

    def test_create_default(self):
        from polymarket_agent.backtest.strategy import create_default_strategy_config, load_strategy_config

        path = create_default_strategy_config(TEST_STRATEGY_PATH)
        assert path.exists()

        config = load_strategy_config(path)
        assert config["version"] == 1
        assert "market_selection" in config
        assert "edge_thresholds" in config

    def test_update_increments_version(self):
        from polymarket_agent.backtest.strategy import (
            create_default_strategy_config,
            load_strategy_config,
            update_strategy_config,
        )

        create_default_strategy_config(TEST_STRATEGY_PATH)

        updated = update_strategy_config(
            TEST_STRATEGY_PATH,
            target_categories=["crypto"],
            insight="Test insight",
            insight_source="test",
        )

        assert updated["version"] == 2
        assert updated["market_selection"]["target_categories"] == ["crypto"]
        assert len(updated["insights"]) == 1
        assert updated["insights"][0]["finding"] == "Test insight"

    def test_update_category_overrides_merge(self):
        from polymarket_agent.backtest.strategy import (
            create_default_strategy_config,
            update_strategy_config,
        )

        create_default_strategy_config(TEST_STRATEGY_PATH)

        # First update: add crypto override
        update_strategy_config(
            TEST_STRATEGY_PATH,
            category_overrides={"crypto": 0.12},
        )

        # Second update: add politics override (crypto should persist)
        config = update_strategy_config(
            TEST_STRATEGY_PATH,
            category_overrides={"politics": 0.08},
        )

        overrides = config["edge_thresholds"]["category_overrides"]
        assert overrides["crypto"] == 0.12
        assert overrides["politics"] == 0.08


# ---------------------------------------------------------------------------
# 8.11 Test tactical integration
# ---------------------------------------------------------------------------


class TestTacticalIntegration:
    def test_edge_with_strategy_override(self):
        """compute_required_edge uses strategy override as base."""
        from polymarket_agent.models import Market
        from polymarket_agent.trading.edge import compute_required_edge

        market = Market(
            id="test-001",
            question="Test?",
            category="crypto",
            volume=50000,
            liquidity=5000,
            last_price_yes=0.5,
            active=True,
        )

        # Without strategy: uses default 0.10 base
        threshold_no_strategy = compute_required_edge(market, confidence_width=0.20)

        # With strategy override: uses 0.15 as base for crypto
        strategy = {
            "edge_thresholds": {
                "category_overrides": {"crypto": 0.15},
            }
        }
        threshold_with_strategy = compute_required_edge(
            market, confidence_width=0.20, strategy_config=strategy
        )

        # Strategy override should produce a higher threshold (0.15 base vs 0.10)
        assert threshold_with_strategy > threshold_no_strategy

    def test_edge_no_override_uses_default(self):
        """Market not in overrides uses default base."""
        from polymarket_agent.models import Market
        from polymarket_agent.trading.edge import compute_required_edge

        market = Market(
            id="test-001",
            question="Test?",
            category="science",
            volume=50000,
            liquidity=5000,
            last_price_yes=0.5,
            active=True,
        )

        strategy = {
            "edge_thresholds": {
                "category_overrides": {"crypto": 0.15},  # No science override
            }
        }

        threshold_default = compute_required_edge(market, confidence_width=0.20)
        threshold_strategy = compute_required_edge(
            market, confidence_width=0.20, strategy_config=strategy
        )

        # Should be the same since science has no override
        assert threshold_default == threshold_strategy

    def test_category_filter_in_analysis(self):
        """Strategy category filters applied to candidates list."""
        target_cats = ["crypto", "science"]
        avoid_cats = ["politics"]

        from polymarket_agent.models import Market

        candidates = [
            Market(id="m1", question="Q1?", category="crypto", volume=1000, liquidity=100, last_price_yes=0.5, active=True),
            Market(id="m2", question="Q2?", category="politics", volume=1000, liquidity=100, last_price_yes=0.5, active=True),
            Market(id="m3", question="Q3?", category="science", volume=1000, liquidity=100, last_price_yes=0.5, active=True),
            Market(id="m4", question="Q4?", category="sports", volume=1000, liquidity=100, last_price_yes=0.5, active=True),
        ]

        # Apply target filter
        if target_cats:
            candidates = [m for m in candidates if m.category in target_cats]
        if avoid_cats:
            candidates = [m for m in candidates if m.category not in avoid_cats]

        assert len(candidates) == 2
        assert {m.category for m in candidates} == {"crypto", "science"}


# ---------------------------------------------------------------------------
# 8.12 Test strategy drift monitoring
# ---------------------------------------------------------------------------


class TestStrategyDriftMonitoring:
    def test_drift_detected(self):
        """Flag when Brier diverges from expectations."""
        from polymarket_agent.backtest.database import init_backtest_db
        from polymarket_agent.storage.database import init_db

        init_db(Path("/tmp/test_polymarket_agent_bt.db"))

        # Insert predictions with known Brier scores
        from polymarket_agent.storage.database import get_db

        with get_db() as conn:
            for i in range(15):
                # Insert market first (foreign key target)
                conn.execute(
                    """INSERT OR IGNORE INTO markets (id, question, active)
                    VALUES (?, ?, 1)""",
                    (f"market-{i}", f"Test market {i}"),
                )
                # Crypto predictions: estimate=0.7, outcome=0.0 → Brier = 0.49 (very bad)
                conn.execute(
                    """INSERT INTO predictions (market_id, timestamp, market_price,
                        agent_estimate, confidence_low, confidence_high, category, outcome)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (f"market-{i}", "2024-06-01T00:00:00Z", 0.5, 0.7, 0.6, 0.8, "crypto", 0.0),
                )

        strategy = {
            "edge_thresholds": {
                "category_overrides": {"crypto": 0.12},
            }
        }

        # Check that per-category Brier can be computed
        with get_db() as conn:
            rows = conn.execute(
                """SELECT category,
                    AVG((agent_estimate - outcome) * (agent_estimate - outcome)) as brier,
                    COUNT(*) as count
                FROM predictions
                WHERE outcome IS NOT NULL AND category IS NOT NULL
                GROUP BY category"""
            ).fetchall()

        assert len(rows) == 1
        assert rows[0]["category"] == "crypto"
        assert rows[0]["count"] == 15
        # Brier = (0.7 - 0.0)^2 = 0.49
        assert abs(rows[0]["brier"] - 0.49) < 0.01
        # This exceeds 0.25 + 0.05 = 0.30, so drift should be flagged
        drift = rows[0]["brier"] - 0.25
        assert drift > 0.05


# ---------------------------------------------------------------------------
# Simulation Harness Tests
# ---------------------------------------------------------------------------


def _seed_simulation_markets(db_path):
    """Seed backtest DB with test markets and price histories for simulation tests."""
    from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

    init_backtest_db(db_path)

    now = datetime.now(timezone.utc).isoformat()
    # Market resolves in ~30 days, so horizon=7 means 23 days of price data is visible
    end_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    end_ts = int((datetime.now(timezone.utc) - timedelta(days=5)).timestamp())

    with get_backtest_db(db_path) as conn:
        # Market 1: YES resolution, price=0.60 at 7d horizon
        conn.execute(
            """INSERT INTO bt_markets (id, question, description, category, end_date,
                volume, liquidity, resolution_outcome, yes_token, no_token,
                has_history, collected_at, event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                "sim-market-1", "Will X happen?", "Test description", None,
                end_date, 500000, 10000, "YES", "token1", "token2",
                now, None,
            ),
        )
        # Price history: daily for 30 days, price drifts from 0.50 to 0.60
        for d in range(30, 0, -1):
            ts = end_ts - d * 86400
            price = 0.50 + (30 - d) * 0.003  # 0.50 → 0.59
            conn.execute(
                "INSERT INTO bt_price_history (market_id, timestamp, price) VALUES (?, ?, ?)",
                ("sim-market-1", ts, round(price, 3)),
            )

        # Market 2: NO resolution, price=0.70 at 7d horizon
        conn.execute(
            """INSERT INTO bt_markets (id, question, description, category, end_date,
                volume, liquidity, resolution_outcome, yes_token, no_token,
                has_history, collected_at, event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                "sim-market-2", "Will Y happen?", "Another test", None,
                end_date, 2000000, 50000, "NO", "token3", "token4",
                now, None,
            ),
        )
        for d in range(30, 0, -1):
            ts = end_ts - d * 86400
            price = 0.65 + (30 - d) * 0.002  # 0.65 → 0.72
            conn.execute(
                "INSERT INTO bt_price_history (market_id, timestamp, price) VALUES (?, ?, ?)",
                ("sim-market-2", ts, round(price, 3)),
            )

        # Market 3: YES, low volume, crypto category (for filter testing)
        conn.execute(
            """INSERT INTO bt_markets (id, question, description, category, end_date,
                volume, liquidity, resolution_outcome, yes_token, no_token,
                has_history, collected_at, event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                "sim-market-3", "Crypto question?", "Crypto desc", "crypto", end_date,
                50000, 5000, "YES", "token5", "token6",
                now, None,
            ),
        )
        for d in range(30, 0, -1):
            ts = end_ts - d * 86400
            conn.execute(
                "INSERT INTO bt_price_history (market_id, timestamp, price) VALUES (?, ?, ?)",
                ("sim-market-3", ts, 0.40),
            )


class TestSimulationSchema:
    """6.6 Test schema: simulation tables created correctly."""

    def test_tables_created(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [t["name"] for t in tables]

        assert "bt_simulation_runs" in table_names
        assert "bt_simulation_trials" in table_names

    def test_run_insert(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute(
                """INSERT INTO bt_simulation_runs (started_at, config, market_count)
                VALUES (?, ?, ?)""",
                ("2024-01-01T00:00:00Z", '{"horizon": 7}', 10),
            )
            row = conn.execute("SELECT * FROM bt_simulation_runs WHERE id = 1").fetchone()

        assert row["market_count"] == 10
        assert row["started_at"] == "2024-01-01T00:00:00Z"


class TestHistoricalResearchGatherer:
    """6.1 Test HistoricalResearchGatherer."""

    def test_gather_returns_dossier(self):
        from polymarket_agent.backtest.simulator import HistoricalResearchGatherer
        from polymarket_agent.models import Market

        market = Market(
            id="test-1",
            question="Will it rain?",
            description="Test market",
            category="weather",
            last_price_yes=0.55,
        )
        market._price_history_for_dossier = [
            {"t": 1000000, "p": 0.50},
            {"t": 1086400, "p": 0.55},
        ]

        gatherer = HistoricalResearchGatherer()
        dossier = gatherer.gather(market)

        assert dossier.market_id == "test-1"
        assert dossier.market_question == "Will it rain?"
        assert dossier.current_price_yes == 0.55
        assert len(dossier.web_search_results) == 0
        assert len(dossier.polymarket_comments) == 0
        assert dossier.order_book_signals is None
        assert len(dossier.price_history) == 2

    def test_format_dossier_contains_price_summary(self):
        from polymarket_agent.backtest.simulator import HistoricalResearchGatherer
        from polymarket_agent.models import Market

        market = Market(
            id="test-2",
            question="Will BTC hit 100k?",
            last_price_yes=0.60,
            category="crypto",
        )
        market._price_history_for_dossier = [
            {"t": i * 86400, "p": 0.50 + i * 0.01} for i in range(10)
        ]

        gatherer = HistoricalResearchGatherer()
        dossier = gatherer.gather(market)
        text = gatherer.format_dossier_for_llm(dossier)

        assert "Will BTC hit 100k?" in text
        assert "Price History" in text
        assert "Open:" in text
        assert "web search results" in text.lower() or "Web search" in text

    def test_horizon_truncation(self):
        from polymarket_agent.backtest.simulator import build_market_at_horizon

        end_ts = int(datetime(2024, 6, 30, tzinfo=timezone.utc).timestamp())
        market_dict = {
            "id": "trunc-test",
            "question": "Test?",
            "end_date": "2024-06-30T00:00:00+00:00",
            "volume": 100000,
            "price_history": [
                {"t": end_ts - 20 * 86400, "p": 0.40},  # 20 days before
                {"t": end_ts - 10 * 86400, "p": 0.50},  # 10 days before
                {"t": end_ts - 5 * 86400, "p": 0.60},   # 5 days before (after horizon=7)
                {"t": end_ts - 1 * 86400, "p": 0.90},   # 1 day before (after horizon=7)
            ],
        }

        result = build_market_at_horizon(market_dict, horizon=7)
        assert result is not None
        market_obj, truncated = result

        # Only prices at 20d and 10d should survive (both before 7d horizon)
        assert len(truncated) == 2
        assert market_obj.last_price_yes == 0.50  # Last price before cutoff


class TestSelectMarkets:
    """6.2 Test select_markets()."""

    def test_respects_volume_filter(self):
        from polymarket_agent.backtest.simulator import select_markets

        _seed_simulation_markets(TEST_BACKTEST_DB)

        # min_volume=100000 should get market 1 (500K) and 2 (2M), not 3 (50K)
        markets = select_markets(
            count=10, volume_min=100000, db_path=TEST_BACKTEST_DB
        )
        ids = {m["id"] for m in markets}
        assert "sim-market-1" in ids
        assert "sim-market-2" in ids
        assert "sim-market-3" not in ids

    def test_respects_category_filter(self):
        from polymarket_agent.backtest.simulator import select_markets

        _seed_simulation_markets(TEST_BACKTEST_DB)

        markets = select_markets(
            count=10, category="crypto", volume_min=0, db_path=TEST_BACKTEST_DB
        )
        assert len(markets) == 1
        assert markets[0]["id"] == "sim-market-3"

    def test_respects_count_limit(self):
        from polymarket_agent.backtest.simulator import select_markets

        _seed_simulation_markets(TEST_BACKTEST_DB)

        markets = select_markets(count=1, volume_min=0, db_path=TEST_BACKTEST_DB)
        assert len(markets) == 1


class TestSimulatedPnL:
    """6.3 Test simulated P&L computation."""

    def test_yes_trade_correct_outcome(self):
        from polymarket_agent.backtest.simulator import compute_simulated_trade

        trade = compute_simulated_trade(
            agent_estimate=0.80, market_price=0.55, outcome=1.0,
            edge_threshold=0.10, bankroll=1000, fee_rate=0.02,
        )
        assert trade is not None
        assert trade["side"] == "YES"
        assert trade["entry_price"] == 0.55
        assert trade["exit_price"] == 1.0
        assert trade["net_pnl"] > 0

    def test_yes_trade_wrong_outcome(self):
        from polymarket_agent.backtest.simulator import compute_simulated_trade

        trade = compute_simulated_trade(
            agent_estimate=0.80, market_price=0.55, outcome=0.0,
            edge_threshold=0.10, bankroll=1000, fee_rate=0.02,
        )
        assert trade is not None
        assert trade["side"] == "YES"
        assert trade["net_pnl"] < 0

    def test_no_trade_below_threshold(self):
        from polymarket_agent.backtest.simulator import compute_simulated_trade

        trade = compute_simulated_trade(
            agent_estimate=0.56, market_price=0.55, outcome=1.0,
            edge_threshold=0.10,
        )
        assert trade is None

    def test_no_side_trade(self):
        from polymarket_agent.backtest.simulator import compute_simulated_trade

        trade = compute_simulated_trade(
            agent_estimate=0.30, market_price=0.55, outcome=0.0,
            edge_threshold=0.10, bankroll=1000, fee_rate=0.02,
        )
        assert trade is not None
        assert trade["side"] == "NO"
        assert trade["net_pnl"] > 0  # Correct: bought NO, resolved NO

    def test_fee_deduction(self):
        from polymarket_agent.backtest.simulator import compute_simulated_trade

        trade = compute_simulated_trade(
            agent_estimate=0.80, market_price=0.55, outcome=1.0,
            edge_threshold=0.10, bankroll=1000, fee_rate=0.02,
        )
        assert trade is not None
        assert trade["fees"] > 0
        assert trade["net_pnl"] < trade["gross_pnl"]


class TestSimulationSummary:
    """6.4 Test simulation_summary()."""

    def test_aggregation(self):
        from polymarket_agent.backtest.analysis import simulation_summary
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)
        _seed_simulation_markets(TEST_BACKTEST_DB)

        # Insert a run and trials
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute(
                """INSERT INTO bt_simulation_runs (id, started_at, config, market_count)
                VALUES (1, '2024-01-01', '{}', 2)""",
            )
            # Trial 1: agent=0.80, market=0.60, outcome=1.0 (YES)
            conn.execute(
                """INSERT INTO bt_simulation_trials
                (run_id, market_id, horizon_days, market_price_at_horizon,
                 agent_estimate, outcome, agent_brier, market_brier, edge,
                 simulated_trade, llm_cost, duration_ms)
                VALUES (1, 'sim-market-1', 7, 0.60, 0.80, 1.0, 0.04, 0.16, 0.20,
                '{"net_pnl": 50.0}', 0.03, 5000)""",
            )
            # Trial 2: agent=0.40, market=0.70, outcome=0.0 (NO)
            conn.execute(
                """INSERT INTO bt_simulation_trials
                (run_id, market_id, horizon_days, market_price_at_horizon,
                 agent_estimate, outcome, agent_brier, market_brier, edge,
                 simulated_trade, llm_cost, duration_ms)
                VALUES (1, 'sim-market-2', 7, 0.70, 0.40, 0.0, 0.16, 0.49, -0.30,
                '{"net_pnl": -20.0}', 0.02, 4000)""",
            )

        summary = simulation_summary(1, db_path=TEST_BACKTEST_DB)

        assert summary["trial_count"] == 2
        assert summary["valid_trials"] == 2
        assert abs(summary["agent_brier"] - 0.10) < 0.01  # (0.04+0.16)/2
        assert abs(summary["market_brier"] - 0.325) < 0.01  # (0.16+0.49)/2
        assert summary["brier_diff"] < 0  # Agent is better
        assert abs(summary["simulated_pnl"] - 30.0) < 0.01  # 50 - 20
        assert summary["trade_count"] == 2
        assert summary["total_cost"] == 0.05


class TestSimulationByGrouping:
    """6.5 Test simulation_by_category() and simulation_by_volume_tier()."""

    def test_by_volume_tier(self):
        from polymarket_agent.backtest.analysis import simulation_by_volume_tier
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)
        _seed_simulation_markets(TEST_BACKTEST_DB)

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute(
                """INSERT INTO bt_simulation_runs (id, started_at, config, market_count)
                VALUES (1, '2024-01-01', '{}', 2)""",
            )
            # sim-market-1 has vol=500K (100K-1M tier)
            conn.execute(
                """INSERT INTO bt_simulation_trials
                (run_id, market_id, horizon_days, market_price_at_horizon,
                 agent_estimate, outcome, agent_brier, market_brier, edge,
                 llm_cost, duration_ms)
                VALUES (1, 'sim-market-1', 7, 0.60, 0.80, 1.0, 0.04, 0.16, 0.20,
                0.03, 5000)""",
            )
            # sim-market-2 has vol=2M (1M-10M tier)
            conn.execute(
                """INSERT INTO bt_simulation_trials
                (run_id, market_id, horizon_days, market_price_at_horizon,
                 agent_estimate, outcome, agent_brier, market_brier, edge,
                 llm_cost, duration_ms)
                VALUES (1, 'sim-market-2', 7, 0.70, 0.40, 0.0, 0.16, 0.49, -0.30,
                0.02, 4000)""",
            )

        by_vol = simulation_by_volume_tier(1, db_path=TEST_BACKTEST_DB)
        assert "100K-1M" in by_vol
        assert "1M-10M" in by_vol
        assert by_vol["100K-1M"]["trial_count"] == 1
        assert by_vol["1M-10M"]["trial_count"] == 1


class TestDryRun:
    """6.7 Test dry-run mode."""

    def test_no_db_records(self):
        from polymarket_agent.backtest.database import get_backtest_db
        from polymarket_agent.backtest.simulator import run_simulation

        _seed_simulation_markets(TEST_BACKTEST_DB)

        markets = [
            {
                "id": "sim-market-1", "question": "Will X happen?",
                "end_date": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
                "volume": 500000, "resolution_outcome": "YES",
                "price_history": [{"t": int(datetime.now(timezone.utc).timestamp()) - d * 86400, "p": 0.55} for d in range(30, 0, -1)],
            },
        ]

        result = run_simulation(markets, dry_run=True, db_path=TEST_BACKTEST_DB)
        assert result["dry_run"] is True

        # No run records should exist
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM bt_simulation_runs").fetchone()["c"]
        assert count == 0


class TestEstimationErrorHandling:
    """6.8 Test estimation error handling."""

    def test_continues_after_error(self):
        from polymarket_agent.backtest.database import get_backtest_db
        from polymarket_agent.backtest.simulator import (
            HistoricalResearchGatherer,
            run_simulation,
        )

        _seed_simulation_markets(TEST_BACKTEST_DB)

        # Create markets list
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            rows = conn.execute(
                "SELECT * FROM bt_markets WHERE id IN ('sim-market-1', 'sim-market-2')"
            ).fetchall()
            markets = []
            for row in rows:
                m = dict(row)
                history = conn.execute(
                    "SELECT timestamp as t, price as p FROM bt_price_history WHERE market_id = ?",
                    (row["id"],),
                ).fetchall()
                m["price_history"] = [{"t": h["t"], "p": h["p"]} for h in history]
                markets.append(m)

        # Mock the estimator to raise on first call, succeed on second
        with patch("polymarket_agent.analyst.estimator.ProbabilityEstimator") as mock_est_cls:
            mock_estimator = MagicMock()
            mock_estimate = MagicMock()
            mock_estimate.final_estimate = 0.70
            mock_estimate.confidence_low = 0.60
            mock_estimate.confidence_high = 0.80
            mock_estimate.thesis = "Test thesis"
            mock_estimator.estimate.side_effect = [Exception("LLM error"), mock_estimate]
            mock_est_cls.return_value = mock_estimator

            with patch("polymarket_agent.analyst.llm_client.LLMClient") as mock_llm_cls:
                mock_llm = MagicMock()
                mock_llm.get_usage_summary.return_value = {"estimated_cost": 0.0}
                mock_llm_cls.return_value = mock_llm

                result = run_simulation(markets, db_path=TEST_BACKTEST_DB)

        # Should have completed both trials (one with error, one success)
        assert result["market_count"] == 2
        assert result["valid_trials"] == 1  # Only 1 succeeded

        # Check that trial with error has NULL estimate
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            trials = conn.execute(
                "SELECT * FROM bt_simulation_trials WHERE run_id = ?",
                (result["run_id"],),
            ).fetchall()
        assert len(trials) == 2
        estimates = [t["agent_estimate"] for t in trials]
        assert None in estimates  # One should be NULL


class TestPerTrialCostDelta:
    """6.9 Test that per-trial LLM cost records the delta, not cumulative."""

    def test_cost_delta_per_trial(self):
        from polymarket_agent.backtest.database import get_backtest_db
        from polymarket_agent.backtest.simulator import run_simulation

        _seed_simulation_markets(TEST_BACKTEST_DB)

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            rows = conn.execute(
                "SELECT * FROM bt_markets WHERE id IN ('sim-market-1', 'sim-market-2')"
            ).fetchall()
            markets = []
            for row in rows:
                m = dict(row)
                history = conn.execute(
                    "SELECT timestamp as t, price as p FROM bt_price_history WHERE market_id = ?",
                    (row["id"],),
                ).fetchall()
                m["price_history"] = [{"t": h["t"], "p": h["p"]} for h in history]
                markets.append(m)

        # Mock estimator — LLM cost increases cumulatively: 0.03, then 0.07
        with patch("polymarket_agent.analyst.estimator.ProbabilityEstimator") as mock_est_cls:
            mock_estimator = MagicMock()
            mock_estimate = MagicMock()
            mock_estimate.final_estimate = 0.70
            mock_estimate.confidence_low = 0.60
            mock_estimate.confidence_high = 0.80
            mock_estimate.thesis = "Test"
            mock_estimator.estimate.return_value = mock_estimate
            mock_est_cls.return_value = mock_estimator

            with patch("polymarket_agent.analyst.llm_client.LLMClient") as mock_llm_cls:
                mock_llm = MagicMock()
                # Simulate cumulative cost: 0.03 after trial 1, 0.07 after trial 2
                mock_llm.get_usage_summary.side_effect = [
                    {"estimated_cost": 0.03},
                    {"estimated_cost": 0.07},
                ]
                mock_llm_cls.return_value = mock_llm

                result = run_simulation(markets, db_path=TEST_BACKTEST_DB)

        # Per-trial costs should be deltas: 0.03 and 0.04
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            trials = conn.execute(
                "SELECT llm_cost FROM bt_simulation_trials WHERE run_id = ? ORDER BY id",
                (result["run_id"],),
            ).fetchall()

        costs = [t["llm_cost"] for t in trials]
        assert len(costs) == 2
        assert abs(costs[0] - 0.03) < 0.001
        assert abs(costs[1] - 0.04) < 0.001

        # Run-level total should equal sum of deltas
        assert abs(result["total_cost"] - 0.07) < 0.001
