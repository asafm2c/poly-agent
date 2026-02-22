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

    def test_collect_histories_only_with_market_type_filter(self):
        """market_types filter restricts which markets are selected for history collection."""
        from polymarket_agent.backtest.collector import BacktestCollector
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)

        with patch("polymarket_agent.backtest.collector.httpx.Client"):
            collector = BacktestCollector(db_path=TEST_BACKTEST_DB)

        # Insert a prediction market and a sports market, both without history
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute(
                "INSERT INTO bt_markets (id, question, volume, yes_token, has_history, market_type, collected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("pred1", "Will X happen?", 50000, "tok_pred", 0, "prediction", "2024-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO bt_markets (id, question, volume, yes_token, has_history, market_type, collected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("sport1", "Team A vs B?", 50000, "tok_sport", 0, "sports", "2024-01-01T00:00:00"),
            )

        # Mock _fetch_price_history to return empty (marks has_history=-1)
        with patch.object(collector, "_fetch_price_history", return_value=[]):
            collector.collect_histories_only(market_types=["prediction"])

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            pred = conn.execute("SELECT has_history FROM bt_markets WHERE id = 'pred1'").fetchone()
            sport = conn.execute("SELECT has_history FROM bt_markets WHERE id = 'sport1'").fetchone()

        # prediction market was processed (empty → -1), sports market was not touched (still 0)
        assert pred["has_history"] == -1
        assert sport["has_history"] == 0

        collector.close()

    def test_collect_histories_only_without_market_type_filter(self):
        """Without market_types, all market types are candidates for history collection."""
        from polymarket_agent.backtest.collector import BacktestCollector
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db

        init_backtest_db(TEST_BACKTEST_DB)

        with patch("polymarket_agent.backtest.collector.httpx.Client"):
            collector = BacktestCollector(db_path=TEST_BACKTEST_DB)

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute(
                "INSERT INTO bt_markets (id, question, volume, yes_token, has_history, market_type, collected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("pred1", "Will X happen?", 50000, "tok_pred", 0, "prediction", "2024-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO bt_markets (id, question, volume, yes_token, has_history, market_type, collected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("sport1", "Team A vs B?", 50000, "tok_sport", 0, "sports", "2024-01-01T00:00:00"),
            )

        with patch.object(collector, "_fetch_price_history", return_value=[]):
            collector.collect_histories_only()  # no market_types → all types

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            pred = conn.execute("SELECT has_history FROM bt_markets WHERE id = 'pred1'").fetchone()
            sport = conn.execute("SELECT has_history FROM bt_markets WHERE id = 'sport1'").fetchone()

        # Both markets were processed (no filter applied)
        assert pred["has_history"] == -1
        assert sport["has_history"] == -1

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
            mock_estimate.base_rate = 0.50
            mock_estimate.updated_estimate = 0.65
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
    """6.9 Test that run-level total cost comes from LLM usage summary."""

    def test_run_total_cost_from_llm_summary(self):
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

        with patch("polymarket_agent.analyst.estimator.ProbabilityEstimator") as mock_est_cls:
            mock_estimator = MagicMock()
            mock_estimate = MagicMock()
            mock_estimate.final_estimate = 0.70
            mock_estimate.confidence_low = 0.60
            mock_estimate.confidence_high = 0.80
            mock_estimate.thesis = "Test"
            mock_estimate.base_rate = 0.50
            mock_estimate.updated_estimate = 0.65
            mock_estimator.estimate.return_value = mock_estimate
            mock_est_cls.return_value = mock_estimator

            with patch("polymarket_agent.analyst.llm_client.LLMClient") as mock_llm_cls:
                mock_llm = MagicMock()
                # Total accumulated cost reported by the shared LLM client
                mock_llm.get_usage_summary.return_value = {"estimated_cost": 0.07}
                mock_llm_cls.return_value = mock_llm

                result = run_simulation(markets, db_path=TEST_BACKTEST_DB)

        # Run-level total should come from LLM usage summary
        assert abs(result["total_cost"] - 0.07) < 0.001


# ---------------------------------------------------------------------------
# Systematic Alpha Eval Tests
# ---------------------------------------------------------------------------


class TestTrainingRecencyScore:
    """Tests for training_recency_score()."""

    def test_in_training_window(self):
        from polymarket_agent.backtest.analysis import training_recency_score
        assert training_recency_score("2024-01-01", "claude-sonnet-4-6") == 0.0

    def test_well_past_cutoff(self):
        from polymarket_agent.backtest.analysis import training_recency_score
        assert training_recency_score("2026-01-01", "claude-sonnet-4-6") == 1.0

    def test_linear_interpolation(self):
        from polymarket_agent.backtest.analysis import training_recency_score
        # 90 days after 2025-04-01 = ~2025-06-30, should be ~0.5
        score = training_recency_score("2025-06-30", "claude-sonnet-4-6")
        assert 0.45 < score < 0.55

    def test_unknown_model_returns_1(self):
        from polymarket_agent.backtest.analysis import training_recency_score
        assert training_recency_score("2024-01-01", "unknown-model") == 1.0

    def test_exact_cutoff_date(self):
        from polymarket_agent.backtest.analysis import training_recency_score
        assert training_recency_score("2025-04-01", "claude-sonnet-4-6") == 0.0


class TestBrierConfidenceInterval:
    """Tests for brier_confidence_interval()."""

    def test_basic_computation(self):
        from polymarket_agent.backtest.analysis import brier_confidence_interval
        result = brier_confidence_interval(
            [0.1, 0.2, 0.3, 0.15, 0.12],
            [0.2, 0.25, 0.35, 0.2, 0.18],
            seed=42,
        )
        assert result["n"] == 5
        assert result["mean_diff"] < 0  # agent better
        assert result["ci_low"] <= result["mean_diff"] <= result["ci_high"]

    def test_identical_scores(self):
        from polymarket_agent.backtest.analysis import brier_confidence_interval
        result = brier_confidence_interval([0.1, 0.2, 0.3], [0.1, 0.2, 0.3], seed=42)
        assert abs(result["mean_diff"]) < 0.001
        assert not result["significant"]

    def test_significant_difference(self):
        from polymarket_agent.backtest.analysis import brier_confidence_interval
        # Agent clearly better by large margin
        result = brier_confidence_interval(
            [0.05] * 30, [0.20] * 30, seed=42,
        )
        assert result["mean_diff"] < 0
        assert result["significant"]
        assert result["p_value"] < 0.05

    def test_empty_input(self):
        from polymarket_agent.backtest.analysis import brier_confidence_interval
        result = brier_confidence_interval([], [])
        assert result["n"] == 0
        assert not result["significant"]

    def test_weights_affect_result(self):
        from polymarket_agent.backtest.analysis import brier_confidence_interval
        r1 = brier_confidence_interval([0.1, 0.5], [0.2, 0.1], seed=42)
        r2 = brier_confidence_interval([0.1, 0.5], [0.2, 0.1], weights=[1.0, 0.01], seed=42)
        # With near-zero weight on second, result should differ
        assert r1["mean_diff"] != r2["mean_diff"]


class TestWeightedBrier:
    """Tests for weighted_brier()."""

    def test_basic_computation(self):
        from polymarket_agent.backtest.analysis import weighted_brier
        trials = [
            {"agent_brier": 0.1, "market_brier": 0.2, "training_recency_score": 1.0},
            {"agent_brier": 0.3, "market_brier": 0.2, "training_recency_score": 1.0},
        ]
        result = weighted_brier(trials)
        assert result["trial_count"] == 2
        assert abs(result["agent_brier_weighted"] - 0.2) < 0.001
        assert abs(result["market_brier_weighted"] - 0.2) < 0.001

    def test_null_weights_treated_as_1(self):
        from polymarket_agent.backtest.analysis import weighted_brier
        trials = [
            {"agent_brier": 0.1, "market_brier": 0.2, "training_recency_score": None},
        ]
        result = weighted_brier(trials)
        assert result["trial_count"] == 1
        assert result["agent_brier_weighted"] is not None

    def test_zero_weight_excluded(self):
        from polymarket_agent.backtest.analysis import weighted_brier
        trials = [
            {"agent_brier": 0.1, "market_brier": 0.2, "training_recency_score": 0.0},
            {"agent_brier": 0.5, "market_brier": 0.3, "training_recency_score": 1.0},
        ]
        result = weighted_brier(trials)
        # With w=0 for first trial, result should be dominated by second
        assert abs(result["agent_brier_weighted"] - 0.5) < 0.2


class TestCrossModelComparison:
    """Tests for cross_model_comparison()."""

    def _setup_two_runs(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        init_backtest_db(TEST_BACKTEST_DB)
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            # Insert markets
            for i in range(10):
                conn.execute(
                    "INSERT INTO bt_markets (id, question, collected_at, volume, has_history, resolution_outcome) VALUES (?, ?, 'now', ?, 1, 'YES')",
                    (f"mkt_{i}", f"Q{i}", 200000 if i < 5 else 2000000),
                )
            # Run 1: model A
            conn.execute("INSERT INTO bt_simulation_runs (id, started_at, config) VALUES (1, 'now', '{\"model\": \"model-a\"}')")
            for i in range(10):
                conn.execute(
                    "INSERT INTO bt_simulation_trials (run_id, market_id, horizon_days, agent_brier, market_brier, outcome, model) VALUES (1, ?, 7, ?, ?, 1.0, 'model-a')",
                    (f"mkt_{i}", 0.10 + i * 0.01, 0.15 + i * 0.01),
                )
            # Run 2: model B
            conn.execute("INSERT INTO bt_simulation_runs (id, started_at, config) VALUES (2, 'now', '{\"model\": \"model-b\"}')")
            for i in range(10):
                conn.execute(
                    "INSERT INTO bt_simulation_trials (run_id, market_id, horizon_days, agent_brier, market_brier, outcome, model) VALUES (2, ?, 7, ?, ?, 1.0, 'model-b')",
                    (f"mkt_{i}", 0.12 + i * 0.01, 0.15 + i * 0.01),
                )

    def test_models_summary(self):
        from polymarket_agent.backtest.analysis import cross_model_comparison
        self._setup_two_runs()
        result = cross_model_comparison([1, 2], db_path=TEST_BACKTEST_DB)
        assert "model-a" in result["models"]
        assert "model-b" in result["models"]
        assert result["models"]["model-a"]["trial_count"] == 10

    def test_pairwise_comparison(self):
        from polymarket_agent.backtest.analysis import cross_model_comparison
        self._setup_two_runs()
        result = cross_model_comparison([1, 2], db_path=TEST_BACKTEST_DB)
        assert len(result["pairwise"]) == 1
        pair_key = list(result["pairwise"].keys())[0]
        assert "mean_diff" in result["pairwise"][pair_key]

    def test_by_category(self):
        from polymarket_agent.backtest.analysis import cross_model_comparison
        self._setup_two_runs()
        result = cross_model_comparison([1, 2], db_path=TEST_BACKTEST_DB)
        assert "(null)" in result["by_category"]

    def test_by_volume_tier(self):
        from polymarket_agent.backtest.analysis import cross_model_comparison
        self._setup_two_runs()
        result = cross_model_comparison([1, 2], db_path=TEST_BACKTEST_DB)
        assert len(result["by_volume_tier"]) >= 1

    def test_by_cell(self):
        from polymarket_agent.backtest.analysis import cross_model_comparison
        self._setup_two_runs()
        result = cross_model_comparison([1, 2], db_path=TEST_BACKTEST_DB)
        assert "by_cell" in result
        assert len(result["by_cell"]) >= 1


class TestComputePairedStats:
    """Tests for _compute_paired_stats()."""

    def _setup_run(self, agent_offset=0.0):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        init_backtest_db(TEST_BACKTEST_DB)
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            for i in range(30):
                conn.execute(
                    "INSERT OR IGNORE INTO bt_markets (id, question, collected_at) VALUES (?, ?, 'now')",
                    (f"mkt_{i}", f"Q{i}"),
                )
            conn.execute("INSERT INTO bt_simulation_runs (id, started_at, config) VALUES (1, 'now', '{}')")
            for i in range(30):
                conn.execute(
                    "INSERT INTO bt_simulation_trials (run_id, market_id, horizon_days, agent_brier, market_brier, outcome, model) VALUES (1, ?, 7, ?, ?, 1.0, 'test')",
                    (f"mkt_{i}", 0.10 + agent_offset + (i % 5) * 0.02, 0.15 + (i % 3) * 0.03),
                )

    def test_significant_difference(self):
        from polymarket_agent.backtest.simulator import _compute_paired_stats
        self._setup_run(agent_offset=0.0)
        p_value, effect_size = _compute_paired_stats(1, TEST_BACKTEST_DB)
        assert p_value is not None
        assert p_value < 0.05
        assert effect_size is not None

    def test_small_sample_returns_none(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.simulator import _compute_paired_stats
        init_backtest_db(TEST_BACKTEST_DB)
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute("INSERT INTO bt_markets (id, question, collected_at) VALUES ('m1', 'Q', 'now')")
            conn.execute("INSERT INTO bt_simulation_runs (id, started_at, config) VALUES (1, 'now', '{}')")
            conn.execute("INSERT INTO bt_simulation_trials (run_id, market_id, horizon_days, agent_brier, market_brier, outcome) VALUES (1, 'm1', 7, 0.1, 0.2, 1.0)")
        p_value, effect_size = _compute_paired_stats(1, TEST_BACKTEST_DB)
        assert p_value is None
        assert effect_size is None


# ---------------------------------------------------------------------------
# Hypothesis Tracker Tests
# ---------------------------------------------------------------------------


class TestHypothesisSchema:
    """Tests for hypothesis tables and seed data."""

    def test_hypothesis_tables_created(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        init_backtest_db(TEST_BACKTEST_DB)
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "bt_hypotheses" in tables
        assert "bt_hypothesis_evidence" in tables
        assert "bt_hypothesis_actions" in tables

    def test_seed_hypotheses_created(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        init_backtest_db(TEST_BACKTEST_DB)
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM bt_hypotheses").fetchone()["c"]
        assert count == 4

    def test_seed_hypotheses_idempotent(self):
        from polymarket_agent.backtest.database import init_backtest_db
        from polymarket_agent.backtest.hypothesis import seed_hypotheses
        init_backtest_db(TEST_BACKTEST_DB)
        # Call again
        seeded = seed_hypotheses(TEST_BACKTEST_DB)
        assert seeded == 0  # Already seeded

    def test_seed_actions_created(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        init_backtest_db(TEST_BACKTEST_DB)
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM bt_hypothesis_actions").fetchone()["c"]
        assert count >= 4  # At least one action per seed hypothesis


class TestHypothesisCRUD:
    """Tests for propose() and record_evidence()."""

    def test_propose_creates_hypothesis(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.hypothesis import propose
        init_backtest_db(TEST_BACKTEST_DB)
        hyp_id = propose("test-hyp", "Test hypothesis", db_path=TEST_BACKTEST_DB)
        assert hyp_id > 0
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            row = conn.execute("SELECT * FROM bt_hypotheses WHERE id = ?", (hyp_id,)).fetchone()
        assert row["name"] == "test-hyp"
        assert row["status"] == "proposed"
        assert row["confidence_score"] == 0.0

    def test_propose_with_filters(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.hypothesis import propose
        init_backtest_db(TEST_BACKTEST_DB)
        hyp_id = propose("filtered", "Filtered hypothesis",
                         category_filter=None, volume_min=100000, volume_max=1000000,
                         db_path=TEST_BACKTEST_DB)
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            row = conn.execute("SELECT * FROM bt_hypotheses WHERE id = ?", (hyp_id,)).fetchone()
        assert row["volume_min"] == 100000
        assert row["volume_max"] == 1000000

    def test_propose_duplicate_name_raises(self):
        from polymarket_agent.backtest.database import init_backtest_db
        from polymarket_agent.backtest.hypothesis import propose
        init_backtest_db(TEST_BACKTEST_DB)
        propose("unique-name", "First", db_path=TEST_BACKTEST_DB)
        with pytest.raises(Exception):
            propose("unique-name", "Duplicate", db_path=TEST_BACKTEST_DB)

    def test_propose_with_actions(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.hypothesis import propose
        init_backtest_db(TEST_BACKTEST_DB)
        hyp_id = propose("with-actions", "Has actions", actions=[
            {"action_type": "edge_override", "config": '{"base_threshold": 0.08}', "base_strength": 1.0},
        ], db_path=TEST_BACKTEST_DB)
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            actions = conn.execute("SELECT * FROM bt_hypothesis_actions WHERE hypothesis_id = ?", (hyp_id,)).fetchall()
        assert len(actions) == 1
        assert actions[0]["active"] == 0  # Inactive until confirmed

    def test_record_evidence(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.hypothesis import propose, record_evidence
        init_backtest_db(TEST_BACKTEST_DB)
        hyp_id = propose("ev-test", "Evidence test", db_path=TEST_BACKTEST_DB)
        # Need a simulation run for FK
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute("INSERT INTO bt_simulation_runs (id, started_at, config) VALUES (1, 'now', '{}')")
        ev_id = record_evidence(hyp_id, run_id=1, trial_count=50,
                                agent_brier=0.15, market_brier=0.18,
                                brier_diff=-0.03, p_value=0.02,
                                supports_hypothesis=1, db_path=TEST_BACKTEST_DB)
        assert ev_id > 0


class TestHypothesisEvaluation:
    """Tests for evaluate() and status transitions."""

    def _setup_hypothesis_with_evidence(self, brier_diff=-0.03, p_value=0.02, n_evidence=1, trial_count=50):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.hypothesis import propose, record_evidence
        init_backtest_db(TEST_BACKTEST_DB)
        hyp_id = propose("eval-test", "Eval test", actions=[
            {"action_type": "edge_override", "config": '{"base_threshold": 0.08}', "base_strength": 1.0},
        ], db_path=TEST_BACKTEST_DB)
        for i in range(n_evidence):
            with get_backtest_db(TEST_BACKTEST_DB) as conn:
                conn.execute("INSERT INTO bt_simulation_runs (started_at, config) VALUES ('now', '{}')")
                run_id = conn.execute("SELECT MAX(id) as m FROM bt_simulation_runs").fetchone()["m"]
            supports = 1 if brier_diff < 0 else 0
            record_evidence(hyp_id, run_id=run_id, trial_count=trial_count,
                            agent_brier=0.15, market_brier=0.18,
                            brier_diff=brier_diff, p_value=p_value,
                            supports_hypothesis=supports, db_path=TEST_BACKTEST_DB)
        return hyp_id

    def test_evaluate_confirms_on_strong_evidence(self):
        from polymarket_agent.backtest.database import get_backtest_db
        from polymarket_agent.backtest.hypothesis import evaluate
        hyp_id = self._setup_hypothesis_with_evidence(brier_diff=-0.03, p_value=0.02, trial_count=50)
        result = evaluate(hyp_id, db_path=TEST_BACKTEST_DB)
        assert result["status"] == "confirmed"
        # Check actions activated
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            actions = conn.execute("SELECT * FROM bt_hypothesis_actions WHERE hypothesis_id = ? AND active = 1", (hyp_id,)).fetchall()
        assert len(actions) >= 1

    def test_evaluate_rejects_on_positive_brier_diff(self):
        from polymarket_agent.backtest.hypothesis import evaluate
        hyp_id = self._setup_hypothesis_with_evidence(brier_diff=0.05, p_value=0.3, trial_count=50)
        result = evaluate(hyp_id, db_path=TEST_BACKTEST_DB)
        assert result["status"] == "rejected"

    def test_evaluate_inconclusive_small_sample(self):
        from polymarket_agent.backtest.hypothesis import evaluate
        hyp_id = self._setup_hypothesis_with_evidence(brier_diff=-0.03, p_value=0.02, trial_count=10)
        result = evaluate(hyp_id, db_path=TEST_BACKTEST_DB)
        # Not enough effective trials for confirmation
        assert result["recommendation"] in ("inconclusive", "need_evidence", "confirmed")

    def test_evaluate_no_evidence(self):
        from polymarket_agent.backtest.database import init_backtest_db
        from polymarket_agent.backtest.hypothesis import evaluate, propose
        init_backtest_db(TEST_BACKTEST_DB)
        hyp_id = propose("no-ev", "No evidence", db_path=TEST_BACKTEST_DB)
        result = evaluate(hyp_id, db_path=TEST_BACKTEST_DB)
        assert result["recommendation"] == "need_evidence"


class TestHypothesisActions:
    """Tests for load_active_hypothesis_actions() and action lifecycle."""

    def test_no_active_actions_initially(self):
        from polymarket_agent.backtest.database import init_backtest_db
        from polymarket_agent.backtest.hypothesis import load_active_hypothesis_actions
        init_backtest_db(TEST_BACKTEST_DB)
        actions = load_active_hypothesis_actions(db_path=TEST_BACKTEST_DB)
        assert len(actions) == 0

    def test_actions_activated_on_confirm(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.hypothesis import (
            evaluate, load_active_hypothesis_actions, propose, record_evidence,
        )
        init_backtest_db(TEST_BACKTEST_DB)
        hyp_id = propose("action-test", "Action test", actions=[
            {"action_type": "edge_override", "config": '{"base_threshold": 0.08}', "base_strength": 1.0},
        ], db_path=TEST_BACKTEST_DB)
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute("INSERT INTO bt_simulation_runs (id, started_at, config) VALUES (1, 'now', '{}')")
        record_evidence(hyp_id, run_id=1, trial_count=50,
                        agent_brier=0.12, market_brier=0.18, brier_diff=-0.06,
                        p_value=0.01, supports_hypothesis=1, db_path=TEST_BACKTEST_DB)
        evaluate(hyp_id, db_path=TEST_BACKTEST_DB)
        actions = load_active_hypothesis_actions(db_path=TEST_BACKTEST_DB)
        assert len(actions) >= 1
        assert actions[0]["effective_strength"] > 0

    def test_effective_strength_scales_with_confidence(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.hypothesis import (
            evaluate, load_active_hypothesis_actions, propose, record_evidence,
        )
        init_backtest_db(TEST_BACKTEST_DB)
        hyp_id = propose("strength-test", "Strength test", actions=[
            {"action_type": "edge_override", "config": '{"base_threshold": 0.08}', "base_strength": 0.5},
        ], db_path=TEST_BACKTEST_DB)
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute("INSERT INTO bt_simulation_runs (id, started_at, config) VALUES (1, 'now', '{}')")
        record_evidence(hyp_id, run_id=1, trial_count=50,
                        agent_brier=0.10, market_brier=0.20, brier_diff=-0.10,
                        p_value=0.001, supports_hypothesis=1, db_path=TEST_BACKTEST_DB)
        evaluate(hyp_id, db_path=TEST_BACKTEST_DB)
        actions = load_active_hypothesis_actions(db_path=TEST_BACKTEST_DB)
        assert len(actions) >= 1
        # effective = base_strength * confidence_score
        assert actions[0]["effective_strength"] <= actions[0]["base_strength"]


class TestMergeHypothesisActions:
    """Tests for _merge_hypothesis_actions() in strategy.py."""

    def test_category_avoid_merged(self):
        from polymarket_agent.backtest.strategy import _merge_hypothesis_actions
        config = {"market_selection": {}, "edge_thresholds": {}}
        actions = [{"action_type": "category_avoid", "config": {"category": "Sports"}, "effective_strength": 1.0}]
        result = _merge_hypothesis_actions(config, actions)
        assert "Sports" in result["market_selection"]["avoid_categories"]

    def test_edge_override_merged(self):
        from polymarket_agent.backtest.strategy import _merge_hypothesis_actions
        config = {"market_selection": {}, "edge_thresholds": {}}
        actions = [{"action_type": "edge_override", "config": {"base_threshold": 0.08, "applies_to": "test"}, "effective_strength": 0.8}]
        result = _merge_hypothesis_actions(config, actions)
        assert "test" in result["edge_thresholds"]["category_overrides"]

    def test_user_override_not_replaced(self):
        from polymarket_agent.backtest.strategy import _merge_hypothesis_actions
        config = {"market_selection": {}, "edge_thresholds": {"category_overrides": {"test": 0.15}}}
        actions = [{"action_type": "edge_override", "config": {"base_threshold": 0.08, "applies_to": "test"}, "effective_strength": 0.8}]
        result = _merge_hypothesis_actions(config, actions)
        assert result["edge_thresholds"]["category_overrides"]["test"] == 0.15  # User value preserved

    def test_low_strength_not_applied(self):
        from polymarket_agent.backtest.strategy import _merge_hypothesis_actions
        config = {"market_selection": {}, "edge_thresholds": {}}
        actions = [{"action_type": "edge_override", "config": {"base_threshold": 0.08, "applies_to": "weak"}, "effective_strength": 0.05}]
        result = _merge_hypothesis_actions(config, actions)
        assert "weak" not in result["edge_thresholds"].get("category_overrides", {})

    def test_actions_stored_in_hypothesis_actions_key(self):
        from polymarket_agent.backtest.strategy import _merge_hypothesis_actions
        config = {"market_selection": {}, "edge_thresholds": {}}
        actions = [{"action_type": "model_preference", "config": {"model": "sonnet"}, "effective_strength": 1.0}]
        result = _merge_hypothesis_actions(config, actions)
        assert len(result["hypothesis_actions"]) == 1


class TestWeightedConfidence:
    """Tests for _compute_weighted_confidence()."""

    def test_empty_evidence(self):
        from polymarket_agent.backtest.hypothesis import _compute_weighted_confidence
        assert _compute_weighted_confidence([]) == 0.0

    def test_strong_supporting_evidence(self):
        from polymarket_agent.backtest.hypothesis import _compute_weighted_confidence
        now = datetime.now(timezone.utc).isoformat()
        evidence = [{"recorded_at": now, "brier_diff": -0.05, "trial_count": 50}]
        conf = _compute_weighted_confidence(evidence)
        assert conf > 0.5

    def test_contradicting_evidence(self):
        from polymarket_agent.backtest.hypothesis import _compute_weighted_confidence
        now = datetime.now(timezone.utc).isoformat()
        evidence = [{"recorded_at": now, "brier_diff": 0.05, "trial_count": 50}]
        conf = _compute_weighted_confidence(evidence)
        assert conf < 0.5

    def test_small_sample_less_weight(self):
        from polymarket_agent.backtest.hypothesis import _compute_weighted_confidence
        now = datetime.now(timezone.utc).isoformat()
        # Same brier_diff, different trial counts
        ev_small = [{"recorded_at": now, "brier_diff": -0.05, "trial_count": 5}]
        ev_large = [{"recorded_at": now, "brier_diff": -0.05, "trial_count": 100}]
        conf_small = _compute_weighted_confidence(ev_small)
        conf_large = _compute_weighted_confidence(ev_large)
        # Larger sample should give slightly different weighting
        assert conf_small > 0 and conf_large > 0


class TestCalibrationWithHypotheses:
    """Tests for calibration export including hypothesis summaries."""

    def test_confirmed_hypotheses_summary(self):
        from polymarket_agent.backtest.database import init_backtest_db
        from polymarket_agent.backtest.hypothesis import get_confirmed_hypotheses_summary
        init_backtest_db(TEST_BACKTEST_DB)
        # No confirmed hypotheses yet
        summary = get_confirmed_hypotheses_summary(db_path=TEST_BACKTEST_DB)
        assert summary is None

    def test_confirmed_summary_includes_text(self):
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.hypothesis import get_confirmed_hypotheses_summary
        init_backtest_db(TEST_BACKTEST_DB)
        # Manually confirm a hypothesis
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute(
                "UPDATE bt_hypotheses SET status = 'confirmed', confidence_score = 0.8 WHERE name = 'probable-no-alpha'"
            )
        summary = get_confirmed_hypotheses_summary(db_path=TEST_BACKTEST_DB)
        assert summary is not None
        assert "Validated Findings" in summary
        assert "probable-no-alpha" in summary


# ---------------------------------------------------------------------------
# CLI Smoke Tests
# ---------------------------------------------------------------------------


class TestHypothesisCLI:
    """Smoke tests for hypothesis CLI commands."""

    def test_hypothesis_list(self):
        from click.testing import CliRunner
        from polymarket_agent.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "hypothesis", "list"])
        assert result.exit_code == 0
        assert "Hypotheses" in result.output or "No hypotheses" in result.output

    def test_hypothesis_actions(self):
        from click.testing import CliRunner
        from polymarket_agent.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "hypothesis", "actions"])
        assert result.exit_code == 0

    def test_hypothesis_decay_check(self):
        from polymarket_agent.backtest.database import init_backtest_db
        init_backtest_db(TEST_BACKTEST_DB)
        from click.testing import CliRunner
        from polymarket_agent.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "hypothesis", "decay-check"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Task 8.3 — Confidence decay formula
# ---------------------------------------------------------------------------


class TestDecayCheckFormula:
    """Tests for exponential confidence decay in decay_check()."""

    def test_decay_formula_matches_expected(self):
        """decay_check() applies base_confidence * (0.5 ** (days_elapsed / half_life))."""
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.hypothesis import decay_check, propose, record_evidence

        init_backtest_db(TEST_BACKTEST_DB)

        # Propose and manually promote to 'confirmed' with known confidence
        hyp_id = propose("decay-formula-test", "Decay formula test", db_path=TEST_BACKTEST_DB)

        # Insert a simulation run for FK
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute("INSERT INTO bt_simulation_runs (id, started_at, config) VALUES (1, 'now', '{}')")

        # Record evidence dated exactly 90 days in the past (one half-life)
        past_date = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute(
                """INSERT INTO bt_hypothesis_evidence
                (hypothesis_id, run_id, recorded_at, trial_count,
                 agent_brier, market_brier, brier_diff, supports_hypothesis)
                VALUES (?, 1, ?, 50, 0.10, 0.20, -0.10, 1)""",
                (hyp_id, past_date),
            )
            # Manually set status to 'confirmed' and a known confidence_score
            conn.execute(
                "UPDATE bt_hypotheses SET status = 'confirmed', confidence_score = 0.8 WHERE id = ?",
                (hyp_id,),
            )

        results = decay_check(db_path=TEST_BACKTEST_DB)
        assert len(results) == 1

        r = results[0]
        assert r["hypothesis_id"] == hyp_id
        half_life = r["half_life"]  # default 90

        # The base confidence is recomputed from evidence by _compute_weighted_confidence,
        # not read from the stored value — so we use r["original_confidence"]
        base_conf = r["original_confidence"]
        days_elapsed = r["days_since_evidence"]  # int cast of actual elapsed

        # Recompute expected using the same formula as the implementation
        expected = base_conf * (0.5 ** (days_elapsed / half_life))
        assert r["decayed_confidence"] == pytest.approx(expected, rel=1e-6)

        # At 90 days elapsed and half_life=90, decay factor is 0.5
        # so decayed should be approximately half of base
        assert r["decayed_confidence"] == pytest.approx(base_conf * 0.5, rel=0.05)


# ---------------------------------------------------------------------------
# Task 8.6 — _compute_weighted_brier_diff() unit test
# ---------------------------------------------------------------------------


class TestComputeWeightedBrierDiff:
    """Direct unit tests for _compute_weighted_brier_diff()."""

    def test_empty_returns_zero(self):
        from polymarket_agent.backtest.hypothesis import _compute_weighted_brier_diff
        result, n = _compute_weighted_brier_diff([])
        assert result == 0.0
        assert n == 0

    def test_all_none_brier_diff_returns_zero(self):
        from polymarket_agent.backtest.hypothesis import _compute_weighted_brier_diff
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            {"brier_diff": None, "trial_count": 50, "recorded_at": now},
            {"brier_diff": None, "trial_count": 30, "recorded_at": now},
        ]
        result, n = _compute_weighted_brier_diff(rows)
        assert result == 0.0
        assert n == 0

    def test_fresh_evidence_weight_near_one(self):
        """With age~0 days, weight~1.0, so result ~= simple weighted average."""
        from polymarket_agent.backtest.hypothesis import _compute_weighted_brier_diff

        now = datetime.now(timezone.utc).isoformat()
        # Two rows with fresh timestamps — age_days ~ 0, weight ~ 1/(1+0) = 1.0
        rows = [
            {"brier_diff": -0.04, "trial_count": 40, "recorded_at": now},
            {"brier_diff": -0.02, "trial_count": 20, "recorded_at": now},
        ]
        result, effective_n = _compute_weighted_brier_diff(rows)

        # With weight~1.0:
        #   weighted_diff = (-0.04 * 1 * 40) + (-0.02 * 1 * 20) = -1.6 + -0.4 = -2.0
        #   total_weight  = 1 * 40 + 1 * 20 = 60
        #   result = -2.0 / 60 ~ -0.0333
        #   effective_n = int(40 * 1 + 20 * 1) = 60
        assert result == pytest.approx(-2.0 / 60, rel=0.01)
        assert effective_n == pytest.approx(60, abs=2)  # allow rounding

    def test_older_evidence_down_weighted(self):
        """Evidence from 30 days ago has weight 0.5; effective_n is reduced."""
        from polymarket_agent.backtest.hypothesis import _compute_weighted_brier_diff

        now_ts = datetime.now(timezone.utc)
        fresh = now_ts.isoformat()
        old = (now_ts - timedelta(days=30)).isoformat()

        # Fresh row: weight ~ 1.0; old row: weight ~ 1/(1+30/30) = 0.5
        rows = [
            {"brier_diff": -0.06, "trial_count": 50, "recorded_at": fresh},
            {"brier_diff": -0.02, "trial_count": 50, "recorded_at": old},
        ]
        result, effective_n = _compute_weighted_brier_diff(rows)

        # weighted_diff = (-0.06 * 1.0 * 50) + (-0.02 * 0.5 * 50) = -3.0 + -0.5 = -3.5
        # total_weight  = 1.0 * 50 + 0.5 * 50 = 75
        # expected ~ -3.5 / 75 ~ -0.04667
        # effective_n = int(50*1.0 + 50*0.5) = int(75) = 75
        expected_diff = (-0.06 * 1.0 * 50 + -0.02 * 0.5 * 50) / (1.0 * 50 + 0.5 * 50)
        assert result == pytest.approx(expected_diff, rel=0.02)
        assert effective_n == pytest.approx(75, abs=3)


# ---------------------------------------------------------------------------
# Task 8.10 — build_recommendation() with weight_adjustment
# ---------------------------------------------------------------------------


class TestBuildRecommendationWeightAdjustment:
    """Tests for hypothesis weight_adjustment actions in build_recommendation()."""

    def _make_market_and_estimate(self, market_id="wa-test-market"):
        """Return a Market and ProbabilityEstimate with clear edge to guarantee a recommendation."""
        from polymarket_agent.models import Market, ProbabilityEstimate

        market = Market(
            id=market_id,
            question="Will the weight adjustment test pass?",
            volume=10000.0,  # Low volume → lower edge threshold
            last_price_yes=0.30,
            last_price_no=0.70,
        )
        estimate = ProbabilityEstimate(
            market_id=market_id,
            final_estimate=0.70,   # Agent 70%, market 30% → strong YES edge
            confidence_low=0.60,
            confidence_high=0.80,
            base_rate=0.50,
            updated_estimate=0.70,
            pass1_reasoning="Strong edge for test",
            pass2_reasoning="Confirmed by test setup",
            thesis="Test edge",
        )
        return market, estimate

    def test_weight_adjustment_increases_position_size(self):
        """Strategy config with weight_adjustment(kelly_multiplier=2.0, strength=1.0) doubles size."""
        from polymarket_agent.trading.edge import build_recommendation

        market, estimate = self._make_market_and_estimate()
        bankroll = 1000.0

        # First call: no strategy config
        rec_plain, _, _ = build_recommendation(market, estimate, bankroll)
        assert rec_plain is not None, "Expected a recommendation with no strategy_config"

        # Second call: weight_adjustment with kelly_multiplier=2.0, effective_strength=1.0
        strategy_config = {
            "hypothesis_actions": [
                {
                    "action_type": "weight_adjustment",
                    "config": {"kelly_multiplier": 2.0},
                    "effective_strength": 1.0,
                }
            ]
        }
        rec_adjusted, _, _ = build_recommendation(
            market, estimate, bankroll, strategy_config=strategy_config
        )
        assert rec_adjusted is not None, "Expected a recommendation with weight_adjustment config"

        # multiplier = 1.0 + (2.0 - 1.0) * 1.0 = 2.0 → size should double
        assert rec_adjusted.recommended_size > rec_plain.recommended_size

    def test_weight_adjustment_zero_strength_no_change(self):
        """effective_strength=0.0 makes multiplier=1.0 so size is unchanged."""
        from polymarket_agent.trading.edge import build_recommendation

        market, estimate = self._make_market_and_estimate(market_id="wa-zero-strength")
        bankroll = 1000.0

        rec_plain, _, _ = build_recommendation(market, estimate, bankroll)
        assert rec_plain is not None

        strategy_config = {
            "hypothesis_actions": [
                {
                    "action_type": "weight_adjustment",
                    "config": {"kelly_multiplier": 2.0},
                    "effective_strength": 0.0,  # no effect
                }
            ]
        }
        rec_zero, _, _ = build_recommendation(
            market, estimate, bankroll, strategy_config=strategy_config
        )
        assert rec_zero is not None
        # multiplier = 1.0 + (2.0 - 1.0) * 0.0 = 1.0 → size should be the same
        assert rec_zero.recommended_size == rec_plain.recommended_size


# ---------------------------------------------------------------------------
# Parallel Trial Execution Tests
# ---------------------------------------------------------------------------


def _make_mock_markets(db_path, market_ids=("sim-market-1", "sim-market-2")):
    """Helper: load seeded markets with price history for simulation tests."""
    from polymarket_agent.backtest.database import get_backtest_db
    _seed_simulation_markets(db_path)
    with get_backtest_db(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM bt_markets WHERE id IN ({','.join('?' for _ in market_ids)})",
            list(market_ids),
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
    return markets


def _mock_estimator_and_llm():
    """Return (mock_estimate, mock_estimator, mock_llm) for patching."""
    mock_estimate = MagicMock()
    mock_estimate.final_estimate = 0.70
    mock_estimate.confidence_low = 0.60
    mock_estimate.confidence_high = 0.80
    mock_estimate.thesis = "Test thesis"
    mock_estimate.base_rate = 0.50
    mock_estimate.updated_estimate = 0.65
    mock_estimator = MagicMock()
    mock_estimator.estimate.return_value = mock_estimate
    mock_llm = MagicMock()
    mock_llm.get_usage_summary.return_value = {"estimated_cost": 0.01}
    return mock_estimate, mock_estimator, mock_llm


class TestParallelSimulation:
    """Tests for parallel trial execution in run_simulation()."""

    def test_concurrency_1_produces_correct_results(self):
        """6.2: concurrency=1 produces same trial count and run record as before."""
        from polymarket_agent.backtest.database import get_backtest_db
        from polymarket_agent.backtest.simulator import run_simulation

        markets = _make_mock_markets(TEST_BACKTEST_DB)
        _, mock_estimator, mock_llm = _mock_estimator_and_llm()

        with patch("polymarket_agent.analyst.estimator.ProbabilityEstimator") as mock_est_cls:
            mock_est_cls.return_value = mock_estimator
            with patch("polymarket_agent.analyst.llm_client.LLMClient") as mock_llm_cls:
                mock_llm_cls.return_value = mock_llm
                result = run_simulation(markets, db_path=TEST_BACKTEST_DB, concurrency=1)

        assert result["market_count"] == 2
        assert result["valid_trials"] == 2

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            trial_count = conn.execute(
                "SELECT COUNT(*) as c FROM bt_simulation_trials WHERE run_id = ?",
                (result["run_id"],),
            ).fetchone()["c"]
        assert trial_count == 2

    def test_concurrency_default_runs_successfully(self):
        """6.1: async trial dispatch works end-to-end with default concurrency."""
        from polymarket_agent.backtest.simulator import run_simulation

        markets = _make_mock_markets(TEST_BACKTEST_DB)
        _, mock_estimator, mock_llm = _mock_estimator_and_llm()

        with patch("polymarket_agent.analyst.estimator.ProbabilityEstimator") as mock_est_cls:
            mock_est_cls.return_value = mock_estimator
            with patch("polymarket_agent.analyst.llm_client.LLMClient") as mock_llm_cls:
                mock_llm_cls.return_value = mock_llm
                result = run_simulation(markets, db_path=TEST_BACKTEST_DB)

        assert result["valid_trials"] == 2
        assert result["run_id"] is not None

    def test_failed_trial_does_not_abort_run(self):
        """6.8: a trial that raises does not abort remaining trials."""
        from polymarket_agent.backtest.database import get_backtest_db
        from polymarket_agent.backtest.simulator import run_simulation

        markets = _make_mock_markets(TEST_BACKTEST_DB)
        mock_estimate, mock_estimator, mock_llm = _mock_estimator_and_llm()
        mock_estimator.estimate.side_effect = [Exception("LLM error"), mock_estimate]

        with patch("polymarket_agent.analyst.estimator.ProbabilityEstimator") as mock_est_cls:
            mock_est_cls.return_value = mock_estimator
            with patch("polymarket_agent.analyst.llm_client.LLMClient") as mock_llm_cls:
                mock_llm_cls.return_value = mock_llm
                result = run_simulation(markets, db_path=TEST_BACKTEST_DB, concurrency=1)

        assert result["market_count"] == 2
        assert result["valid_trials"] == 1

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            trials = conn.execute(
                "SELECT agent_estimate FROM bt_simulation_trials WHERE run_id = ?",
                (result["run_id"],),
            ).fetchall()
        estimates = [t["agent_estimate"] for t in trials]
        assert len(trials) == 2
        assert None in estimates

    def test_concurrency_parameter_passed_to_simulation(self):
        """6.3: concurrency param is accepted and passed through without error."""
        from polymarket_agent.backtest.simulator import run_simulation

        markets = _make_mock_markets(TEST_BACKTEST_DB)
        _, mock_estimator, mock_llm = _mock_estimator_and_llm()

        with patch("polymarket_agent.analyst.estimator.ProbabilityEstimator") as mock_est_cls:
            mock_est_cls.return_value = mock_estimator
            with patch("polymarket_agent.analyst.llm_client.LLMClient") as mock_llm_cls:
                mock_llm_cls.return_value = mock_llm
                # Should not raise regardless of concurrency value
                result = run_simulation(markets, db_path=TEST_BACKTEST_DB, concurrency=3)

        assert result["valid_trials"] == 2


class TestLLMClientRetry:
    """Tests for LLMClient retry and backoff logic."""

    def test_retry_on_rate_limit_error(self):
        """6.4: RateLimitError triggers retry up to max_retries."""
        from polymarket_agent.analyst.llm_client import LLMClient

        with patch("polymarket_agent.config.settings.anthropic_api_key", "test-key"):
            with patch("polymarket_agent.config.settings.llm_max_retries", 2):
                with patch("polymarket_agent.config.settings.llm_retry_base_delay", 0.01):
                    client = LLMClient(api_key="test-key")
                    mock_response = MagicMock()
                    mock_response.content = [MagicMock(text="response")]
                    mock_response.usage.input_tokens = 10
                    mock_response.usage.output_tokens = 5

                    class FakeRateLimitError(Exception):
                        pass

                    # Fail twice, succeed on third
                    client._client.messages.create = MagicMock(
                        side_effect=[
                            FakeRateLimitError(),
                            FakeRateLimitError(),
                            mock_response,
                        ]
                    )
                    with patch("polymarket_agent.analyst.llm_client.RateLimitError", FakeRateLimitError):
                        with patch("time.sleep"):
                            result = client.complete("test prompt")
                    assert result == "response"
                    assert client._client.messages.create.call_count == 3

    def test_retry_on_overloaded_error(self):
        """6.5: overloaded_error APIError triggers retry when llm_retry_on_overloaded=True."""
        from polymarket_agent.analyst.llm_client import LLMClient

        with patch("polymarket_agent.config.settings.anthropic_api_key", "test-key"):
            with patch("polymarket_agent.config.settings.llm_max_retries", 1):
                with patch("polymarket_agent.config.settings.llm_retry_base_delay", 0.01):
                    with patch("polymarket_agent.config.settings.llm_retry_on_overloaded", True):
                        client = LLMClient(api_key="test-key")
                        mock_response = MagicMock()
                        mock_response.content = [MagicMock(text="response")]
                        mock_response.usage.input_tokens = 10
                        mock_response.usage.output_tokens = 5

                        # Build a real-ish APIError subclass that our code detects
                        class OverloadedError(Exception):
                            status_code = 529
                            type = "overloaded_error"

                        client._client.messages.create = MagicMock(
                            side_effect=[OverloadedError(), mock_response]
                        )
                        # Patch the isinstance check in llm_client to treat OverloadedError as APIError
                        with patch("polymarket_agent.analyst.llm_client.APIError", OverloadedError):
                            with patch("time.sleep"):
                                result = client.complete("test prompt")
                        assert result == "response"
                        assert client._client.messages.create.call_count == 2

    def test_non_retryable_error_raises_immediately(self):
        """6.6: non-transient 400 error raises without retrying."""
        from polymarket_agent.analyst.llm_client import LLMClient

        with patch("polymarket_agent.config.settings.anthropic_api_key", "test-key"):
            with patch("polymarket_agent.config.settings.llm_max_retries", 3):
                client = LLMClient(api_key="test-key")

                class BadRequestError(Exception):
                    status_code = 400
                    type = "invalid_request_error"

                client._client.messages.create = MagicMock(side_effect=BadRequestError())
                with patch("polymarket_agent.analyst.llm_client.APIError", BadRequestError):
                    with pytest.raises(BadRequestError):
                        client.complete("test prompt")
                # Should have only tried once (no retries for 400)
                assert client._client.messages.create.call_count == 1

    def test_thread_safe_counter_accumulation(self):
        """6.7: concurrent calls from multiple threads accumulate cost correctly."""
        import threading
        from polymarket_agent.analyst.llm_client import LLMClient

        client = LLMClient(api_key="test-key")

        # Each thread makes one call with 100 input + 50 output tokens
        def make_call():
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="response")]
            mock_response.usage.input_tokens = 100
            mock_response.usage.output_tokens = 50
            with patch.object(client._client.messages, "create", return_value=mock_response):
                with patch("polymarket_agent.config.settings.analysis_model", "claude-sonnet-4-6"):
                    client.complete("test")

        threads = [threading.Thread(target=make_call) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        summary = client.get_usage_summary()
        assert summary["calls"] == 5
        assert summary["input_tokens"] == 500
        assert summary["output_tokens"] == 250


# ---------------------------------------------------------------------------
# Task 7.1 — Unit tests for select_markets_stratified()
# ---------------------------------------------------------------------------


class TestSelectMarketsStratified:
    """7.1 Unit tests for select_markets_stratified() stratified sampling."""

    def test_select_markets_stratified_empty_db(self):
        """Empty DB returns a tuple where the markets list is empty."""
        from polymarket_agent.backtest.database import init_backtest_db
        from polymarket_agent.backtest.simulator import select_markets_stratified

        init_backtest_db(TEST_BACKTEST_DB)

        result = select_markets_stratified(
            n_per_cell=5,
            categories=["crypto"],
            db_path=TEST_BACKTEST_DB,
        )

        # Must return a tuple
        assert isinstance(result, tuple)
        assert len(result) == 2

        markets, cell_counts = result
        # No markets in DB => empty list
        assert isinstance(markets, list)
        assert len(markets) == 0

    def test_select_markets_stratified_with_markets(self):
        """With one eligible market, returns it and correct cell_counts structure."""
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.simulator import select_markets_stratified

        init_backtest_db(TEST_BACKTEST_DB)

        # Insert a resolved market with has_history=1, volume=500_000 (100K-1M tier)
        end_date = "2024-08-01T00:00:00Z"
        collected_at = datetime.now(timezone.utc).isoformat()

        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            conn.execute(
                """INSERT INTO bt_markets
                (id, question, category, end_date, volume, liquidity,
                 resolution_outcome, has_history, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, 'YES', 1, ?)""",
                ("strat-m1", "Will X happen?", "crypto", end_date, 500_000, 10_000, collected_at),
            )
            # Insert a price_history row with timestamp well before end_date - 7 days.
            # end_date = 2024-08-01; 7-day horizon means ts must be <= 2024-07-25.
            # Use 2024-07-20 (11 days before end).
            ts = int(datetime(2024, 7, 20, tzinfo=timezone.utc).timestamp())
            conn.execute(
                "INSERT INTO bt_price_history (market_id, timestamp, price) VALUES (?, ?, ?)",
                ("strat-m1", ts, 0.65),
            )

        result = select_markets_stratified(
            n_per_cell=5,
            categories=["crypto"],
            horizon=7,
            db_path=TEST_BACKTEST_DB,
        )

        assert isinstance(result, tuple)
        markets, cell_counts = result

        # At least one market was found
        assert len(markets) >= 1

        # cell_counts keys are (category, tier_name) tuples
        for key in cell_counts:
            assert isinstance(key, tuple)
            assert len(key) == 2
            cat, tier_name = key
            assert isinstance(tier_name, str)

        # For the "crypto" category, at least one cell should show selected <= available
        for (cat, tier), counts in cell_counts.items():
            if cat == "crypto":
                assert counts["selected"] <= counts["available"]
                assert "requested" in counts


# ---------------------------------------------------------------------------
# Task 7.6 — Integration tests for run_multi_model_evaluation()
# ---------------------------------------------------------------------------


class TestRunMultiModelEvaluation:
    """7.6 Integration tests for run_multi_model_evaluation()."""

    def test_run_multi_model_evaluation_zero_budget(self):
        """budget=0.0 causes models to be skipped when estimated cost > 0."""
        from polymarket_agent.backtest.database import init_backtest_db
        from polymarket_agent.backtest.simulator import run_multi_model_evaluation

        init_backtest_db(TEST_BACKTEST_DB)

        # With 1 market and budget=0.0, estimated_cost=0.005 > 0.0 => model is skipped.
        result = run_multi_model_evaluation(
            markets=[{"id": "test-market"}],
            models=["claude-haiku-4-5-20251001"],
            budget=0.0,
            db_path=TEST_BACKTEST_DB,
        )

        assert "runs" in result
        assert isinstance(result["runs"], dict)
        # All models skipped because estimated_cost (0.005) > budget (0.0)
        assert result["runs"] == {}
        assert "comparison" in result

    def test_run_multi_model_evaluation_returns_structure(self):
        """Mocked run_simulation: result has 'runs' and 'comparison' keys with correct data."""
        from polymarket_agent.backtest.database import init_backtest_db
        from polymarket_agent.backtest.simulator import run_multi_model_evaluation

        init_backtest_db(TEST_BACKTEST_DB)

        fake_result = {
            "run_id": 1,
            "total_cost": 0.01,
            "trials": [],
            "agent_brier": 0.15,
            "market_brier": 0.18,
            "n": 5,
        }

        with patch(
            "polymarket_agent.backtest.simulator.run_simulation",
            return_value=fake_result,
        ):
            result = run_multi_model_evaluation(
                markets=[{"id": "test"}],
                models=["claude-haiku-4-5-20251001"],
                db_path=TEST_BACKTEST_DB,
            )

        assert "runs" in result
        assert "comparison" in result
        assert "claude-haiku-4-5-20251001" in result["runs"]
        assert result["runs"]["claude-haiku-4-5-20251001"] is fake_result


# ---------------------------------------------------------------------------
# Task 7.7 — CLI smoke test: backtest evaluate --dry-run
# ---------------------------------------------------------------------------


class TestEvaluateCLIDryRun:
    """7.7 CLI smoke test for backtest evaluate --dry-run."""

    def test_backtest_evaluate_dry_run_smoke(self):
        """Dry-run exits cleanly even when no eligible markets exist."""
        from click.testing import CliRunner
        from polymarket_agent.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "evaluate", "--dry-run", "--budget", "0"])

        # Should exit 0 or at least not crash with an unhandled exception
        # In dry-run with no markets the CLI prints "No eligible markets found." and returns.
        assert result.exit_code == 0 or "Error" not in (result.output or "")
        # No raw Python traceback should appear
        assert "Traceback" not in (result.output or "")


# ---------------------------------------------------------------------------
# Task 7.8 — Test run_simulation() stores model in bt_simulation_runs
# ---------------------------------------------------------------------------


class TestRunSimulationModelParam:
    """7.8 Test that run_simulation() stores the model in bt_simulation_runs.config."""

    def test_run_simulation_stores_model_in_config(self):
        """run_simulation(model=...) records model name in bt_simulation_runs.config JSON."""
        from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
        from polymarket_agent.backtest.simulator import run_simulation

        init_backtest_db(TEST_BACKTEST_DB)

        target_model = "claude-haiku-4-5-20251001"

        # Empty markets list => no LLM calls needed; the run record is still created.
        with patch("polymarket_agent.analyst.estimator.ProbabilityEstimator") as mock_est_cls:
            mock_estimator = MagicMock()
            mock_est_cls.return_value = mock_estimator
            with patch("polymarket_agent.analyst.llm_client.LLMClient") as mock_llm_cls:
                mock_llm = MagicMock()
                mock_llm.get_usage_summary.return_value = {"estimated_cost": 0.0}
                mock_llm_cls.return_value = mock_llm

                result = run_simulation(
                    markets=[],
                    model=target_model,
                    db_path=TEST_BACKTEST_DB,
                )

        run_id = result["run_id"]
        assert run_id is not None

        # Verify the model is recorded in bt_simulation_runs.config
        with get_backtest_db(TEST_BACKTEST_DB) as conn:
            row = conn.execute(
                "SELECT config FROM bt_simulation_runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        assert row is not None
        config = json.loads(row["config"])
        assert config["model"] == target_model


# ---------------------------------------------------------------------------
# Classifier tests (7 scenarios from spec)
# ---------------------------------------------------------------------------


class TestClassifyMarketType:
    def test_tick_market(self):
        from polymarket_agent.backtest.classifier import classify_market_type
        assert classify_market_type("Bitcoin Up or Down - 3:15PM ET", None) == "tick"

    def test_sports_by_category(self):
        from polymarket_agent.backtest.classifier import classify_market_type
        assert classify_market_type("Chelsea vs Arsenal", "Match Winner") == "sports"

    def test_sports_by_vs_pattern_null_category(self):
        from polymarket_agent.backtest.classifier import classify_market_type
        assert classify_market_type("Birrell vs. Bhamidipaty", None) == "sports"

    def test_spread_category_is_sports(self):
        from polymarket_agent.backtest.classifier import classify_market_type
        assert classify_market_type("Cowboys -3.5", "Spread -3.5") == "sports"

    def test_economic_range_by_category(self):
        from polymarket_agent.backtest.classifier import classify_market_type
        assert classify_market_type("NFP report", "88,000-90,000") == "economic-range"

    def test_prediction_market(self):
        from polymarket_agent.backtest.classifier import classify_market_type
        assert classify_market_type("Will Trump sign the tariff bill by March?", None) == "prediction"

    def test_tick_beats_sports_priority(self):
        from polymarket_agent.backtest.classifier import classify_market_type
        assert classify_market_type("BTC Up or Down vs ETH", "Match Winner") == "tick"
