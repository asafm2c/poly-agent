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
