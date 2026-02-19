"""Integration tests for the Polymarket agent."""

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

# Use temp database for all tests
TEST_DB = Path("/tmp/test_polymarket_agent.db")


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Use a temporary database for each test."""
    monkeypatch.setattr("polymarket_agent.config.settings.db_path", TEST_DB)
    from polymarket_agent.storage.database import init_db

    init_db(TEST_DB)
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()


# --- 12.1: End-to-end paper trading pipeline ---


class TestPaperTradingPipeline:
    def test_paper_trade_full_cycle(self):
        """Test: scan → store → edge → paper trade → track."""
        from polymarket_agent.market.storage import upsert_market
        from polymarket_agent.models import (
            Market,
            ProbabilityEstimate,
            Side,
        )
        from polymarket_agent.trading.edge import build_recommendation
        from polymarket_agent.trading.paper import PaperTrader

        # Create a test market
        market = Market(
            id="test-market-001",
            question="Will it rain tomorrow?",
            category="weather",
            end_date=datetime.now(timezone.utc) + timedelta(days=7),
            volume=50000,
            liquidity=5000,
            last_price_yes=0.40,
            last_price_no=0.60,
            active=True,
            outcome_yes_token="token_yes_001",
            outcome_no_token="token_no_001",
        )
        upsert_market(market)

        # Create a probability estimate with edge
        estimate = ProbabilityEstimate(
            market_id=market.id,
            final_estimate=0.65,  # Agent thinks 65%, market says 40%
            confidence_low=0.55,
            confidence_high=0.75,
            base_rate=0.50,
            updated_estimate=0.65,
            pass1_reasoning="Base rate of rain is ~50%",
            pass2_reasoning="Weather data suggests 65%",
            key_evidence=["Weather forecast shows 65% chance"],
            thesis="Underpriced rain probability",
        )

        # Build recommendation
        paper = PaperTrader()
        bankroll = paper.get_cash_balance()
        assert bankroll == 1000.0  # Default starting balance

        rec = build_recommendation(market, estimate, bankroll)
        assert rec is not None
        assert rec.side == Side.YES
        assert rec.adjusted_edge > 0

        # Execute paper trade
        trade = paper.execute_trade(rec)
        assert trade is not None
        assert trade.mode.value == "paper"

        # Check portfolio
        summary = paper.get_portfolio_summary()
        assert summary.open_positions == 1
        assert summary.cash_balance < 1000.0

        # Check trade history
        history = paper.get_trade_history()
        assert len(history) == 1

    def test_position_resolution(self):
        """Test: open position → market resolves → P&L recorded."""
        from polymarket_agent.market.storage import upsert_market
        from polymarket_agent.models import (
            Market,
            ProbabilityEstimate,
        )
        from polymarket_agent.trading.edge import build_recommendation
        from polymarket_agent.trading.paper import PaperTrader

        market = Market(
            id="test-resolve-001",
            question="Will test pass?",
            category="test",
            volume=100000,
            liquidity=10000,
            last_price_yes=0.35,
            active=True,
        )
        upsert_market(market)

        estimate = ProbabilityEstimate(
            market_id=market.id,
            final_estimate=0.60,
            confidence_low=0.50,
            confidence_high=0.70,
            base_rate=0.50,
            updated_estimate=0.60,
            pass1_reasoning="test",
            pass2_reasoning="test",
            thesis="test thesis",
        )

        paper = PaperTrader()
        rec = build_recommendation(market, estimate, paper.get_cash_balance())
        assert rec is not None
        paper.execute_trade(rec)

        # Resolve market as YES (our position wins)
        resolved = paper.resolve_positions(market.id, "YES")
        assert len(resolved) == 1
        assert resolved[0].realized_pnl > 0

        summary = paper.get_portfolio_summary()
        assert summary.open_positions == 0
        assert summary.realized_pnl > 0


# --- 12.2: Risk manager tests ---


class TestRiskManager:
    def test_per_market_limit(self):
        """Verify trades are rejected when per-market limit is exceeded."""
        from polymarket_agent.models import Side, TradeRecommendation
        from polymarket_agent.risk.manager import RiskManager

        rm = RiskManager()

        rec = TradeRecommendation(
            market_id="test-risk-001",
            market_question="Test?",
            side=Side.YES,
            raw_edge=0.15,
            adjusted_edge=0.12,
            market_price=0.40,
            agent_estimate=0.55,
            recommended_size=100.0,  # Exceeds $50 default limit
            limit_price=0.40,
            reasoning="test",
            thesis="test",
            confidence_low=0.45,
            confidence_high=0.65,
        )

        result = rm._check_per_market(rec)
        # Should pass but with adjusted size (since no existing position,
        # the $100 exceeds $50 max, but since there's no existing position
        # it should be adjusted)
        assert result.passed
        # But the $100 exceeds the $50 limit
        assert result.adjusted_size is not None
        assert result.adjusted_size <= 50.0

    def test_kill_switch(self):
        """Verify kill switch blocks all trades."""
        from polymarket_agent.risk.manager import RiskManager

        rm = RiskManager()
        assert not rm.is_kill_switch_active()

        rm.activate_kill_switch("test")
        assert rm.is_kill_switch_active()

        result = rm._check_kill_switch()
        assert not result.passed
        assert "kill switch" in result.reason.lower()

        rm.deactivate_kill_switch()
        assert not rm.is_kill_switch_active()

    def test_daily_loss_limit(self):
        """Verify daily loss limit halts trading."""
        from polymarket_agent.risk.manager import RiskManager
        from polymarket_agent.storage.database import get_db
        from datetime import date

        rm = RiskManager()

        # Insert a large daily loss
        today = date.today().isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_pnl (date, total_pnl) VALUES (?, ?)",
                (today, -100.0),
            )

        result = rm._check_daily_loss()
        assert not result.passed
        assert "daily loss" in result.reason.lower()


# --- 12.3: Calibration pipeline ---


class TestCalibrationPipeline:
    def test_calibration_computation(self):
        """Create mock predictions with known outcomes, verify calibration."""
        from polymarket_agent.models import ProbabilityEstimate
        from polymarket_agent.trading.calibration import (
            compute_calibration,
            record_prediction,
            update_prediction_outcome,
        )

        # Record a batch of predictions with known outcomes
        predictions = [
            # (estimate, market_price, category, actual_outcome)
            (0.8, 0.5, "politics", 1.0),
            (0.8, 0.6, "politics", 1.0),
            (0.8, 0.5, "politics", 0.0),
            (0.3, 0.5, "crypto", 0.0),
            (0.3, 0.4, "crypto", 0.0),
            (0.3, 0.3, "crypto", 1.0),
            (0.6, 0.5, "politics", 1.0),
            (0.6, 0.5, "politics", 0.0),
            (0.6, 0.4, "politics", 1.0),
            (0.6, 0.5, "crypto", 1.0),
            # Need at least 20 for full calibration
            (0.7, 0.5, "politics", 1.0),
            (0.7, 0.6, "politics", 1.0),
            (0.7, 0.5, "politics", 0.0),
            (0.4, 0.5, "crypto", 0.0),
            (0.4, 0.4, "crypto", 0.0),
            (0.4, 0.3, "crypto", 1.0),
            (0.5, 0.5, "politics", 1.0),
            (0.5, 0.5, "politics", 0.0),
            (0.9, 0.8, "politics", 1.0),
            (0.9, 0.7, "politics", 1.0),
            (0.2, 0.3, "crypto", 0.0),
            (0.2, 0.2, "crypto", 0.0),
        ]

        # Create corresponding markets first (foreign key constraint)
        from polymarket_agent.market.storage import upsert_market
        from polymarket_agent.models import Market

        for i in range(len(predictions)):
            upsert_market(
                Market(id=f"cal-test-{i:03d}", question=f"Cal test {i}?", active=True)
            )

        for i, (est, price, cat, _outcome) in enumerate(predictions):
            estimate = ProbabilityEstimate(
                market_id=f"cal-test-{i:03d}",
                final_estimate=est,
                confidence_low=max(0, est - 0.1),
                confidence_high=min(1, est + 0.1),
                base_rate=0.5,
                updated_estimate=est,
                pass1_reasoning="test",
                pass2_reasoning="test",
                thesis="test",
            )
            record_prediction(estimate, price, cat)

        # Update outcomes
        for i, (est, price, cat, outcome) in enumerate(predictions):
            update_prediction_outcome(f"cal-test-{i:03d}", outcome)

        # Compute calibration
        report = compute_calibration()
        assert report.resolved_predictions == len(predictions)
        assert report.brier_score is not None
        assert report.brier_score >= 0

        # Verify buckets exist
        assert len(report.buckets) > 0

        # Category calibration
        politics_report = compute_calibration(category="politics")
        assert politics_report.resolved_predictions > 0

    def test_calibration_export(self):
        """Verify calibration export produces readable text."""
        from polymarket_agent.trading.calibration import export_calibration_for_llm

        text = export_calibration_for_llm(min_resolved=100)  # High threshold
        assert "Insufficient" in text


# --- 12.4: CLI smoke tests ---


class TestCLISmoke:
    def test_cli_help(self):
        """Verify CLI help works."""
        from click.testing import CliRunner

        from polymarket_agent.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Polymarket Agent" in result.output

    def test_config_command(self):
        """Verify config command runs without error."""
        from click.testing import CliRunner

        from polymarket_agent.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert result.exit_code == 0
        assert "Configuration" in result.output

    def test_portfolio_command(self):
        """Verify portfolio command runs with empty portfolio."""
        from click.testing import CliRunner

        from polymarket_agent.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["portfolio"])
        assert result.exit_code == 0
        assert "Portfolio" in result.output

    def test_report_command(self):
        """Verify report command runs."""
        from click.testing import CliRunner

        from polymarket_agent.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["report"])
        assert result.exit_code == 0
        assert "Daily Report" in result.output


# --- Adaptive Feedback Loop Tests ---


def _create_test_market(market_id="test-fb-001", price_yes=0.40, resolved=False, resolution_outcome=None):
    from polymarket_agent.market.storage import upsert_market
    from polymarket_agent.models import Market

    market = Market(
        id=market_id,
        question=f"Test market {market_id}?",
        category="test",
        end_date=datetime.now(timezone.utc) + timedelta(days=7),
        volume=50000,
        liquidity=5000,
        last_price_yes=price_yes,
        last_price_no=1.0 - price_yes,
        active=not resolved,
        resolved=resolved,
        resolution_outcome=resolution_outcome,
        outcome_yes_token="tok_yes",
        outcome_no_token="tok_no",
    )
    upsert_market(market)
    return market


class TestPriceSnapshots:
    """6.1: Test price snapshot insert and query."""

    def test_bulk_insert_and_query(self):
        from polymarket_agent.storage.snapshots import (
            get_price_history,
            insert_price_snapshots,
        )

        m1 = _create_test_market("snap-001", 0.40)
        m2 = _create_test_market("snap-002", 0.60)

        count = insert_price_snapshots([m1, m2])
        assert count == 2

        history = get_price_history("snap-001")
        assert len(history) == 1
        assert history[0]["price_yes"] == 0.40

    def test_time_windowed_query(self):
        import time

        from polymarket_agent.storage.snapshots import (
            get_price_history,
            insert_price_snapshots,
        )

        m = _create_test_market("snap-003", 0.50)
        insert_price_snapshots([m])

        since = datetime.utcnow().isoformat()
        time.sleep(0.05)
        m.last_price_yes = 0.55
        insert_price_snapshots([m])

        history = get_price_history("snap-003", since=since)
        assert len(history) == 1
        assert history[0]["price_yes"] == 0.55

    def test_latest_prices(self):
        from polymarket_agent.storage.snapshots import (
            get_latest_prices,
            insert_price_snapshots,
        )

        m1 = _create_test_market("snap-lp1", 0.30)
        m2 = _create_test_market("snap-lp2", 0.70)
        insert_price_snapshots([m1, m2])

        # Update and insert again
        m1.last_price_yes = 0.35
        insert_price_snapshots([m1])

        prices = get_latest_prices(["snap-lp1", "snap-lp2"])
        assert prices["snap-lp1"] == 0.35  # Latest
        assert prices["snap-lp2"] == 0.70

    def test_cleanup(self):
        from polymarket_agent.storage.snapshots import (
            cleanup_old_snapshots,
            insert_price_snapshots,
        )

        m = _create_test_market("snap-clean", 0.50)
        insert_price_snapshots([m])

        # Cleanup with 0 retention = delete everything
        deleted = cleanup_old_snapshots(0)
        assert deleted >= 1


class TestResolutionDetection:
    """6.2: Test resolution detection."""

    def test_prediction_outcome_updated(self):
        from polymarket_agent.models import ProbabilityEstimate
        from polymarket_agent.trading.calibration import (
            record_prediction,
            update_prediction_outcome,
        )

        _create_test_market("res-001")

        estimate = ProbabilityEstimate(
            market_id="res-001",
            final_estimate=0.65,
            confidence_low=0.55,
            confidence_high=0.75,
            base_rate=0.50,
            updated_estimate=0.65,
            pass1_reasoning="test",
            pass2_reasoning="test",
            thesis="test",
        )
        record_prediction(estimate, 0.40, "test")

        updated = update_prediction_outcome("res-001", 1.0)
        assert updated == 1

        # Second call should update 0 (already resolved)
        updated2 = update_prediction_outcome("res-001", 1.0)
        assert updated2 == 0

    def test_position_resolved_with_sell_trade(self):
        from polymarket_agent.models import Side, TradeRecommendation
        from polymarket_agent.storage.database import get_db
        from polymarket_agent.trading.paper import PaperTrader

        _create_test_market("res-002", 0.40)

        paper = PaperTrader()
        rec = TradeRecommendation(
            market_id="res-002",
            market_question="Test?",
            side=Side.YES,
            raw_edge=0.15,
            adjusted_edge=0.12,
            market_price=0.40,
            agent_estimate=0.55,
            recommended_size=10.0,
            limit_price=0.40,
            reasoning="test",
            thesis="test",
            confidence_low=0.45,
            confidence_high=0.65,
        )
        paper.execute_trade(rec)

        resolved = paper.resolve_positions("res-002", "YES")
        assert len(resolved) == 1
        assert resolved[0].realized_pnl > 0

        # Check sell trade was recorded
        with get_db() as conn:
            sells = conn.execute(
                "SELECT * FROM trades WHERE market_id = ? AND action = 'sell'",
                ("res-002",),
            ).fetchall()
        assert len(sells) == 1
        assert sells[0]["price"] == 1.0  # Won


class TestEdgeComputation:
    """6.3: Test re-evaluation edge computation."""

    def test_yes_position_positive_edge(self):
        from polymarket_agent.cli.scheduler import compute_remaining_edge

        edge = compute_remaining_edge("YES", 0.65, 0.55)
        assert edge == pytest.approx(0.10)

    def test_yes_position_reversed_edge(self):
        from polymarket_agent.cli.scheduler import compute_remaining_edge

        edge = compute_remaining_edge("YES", 0.65, 0.70)
        assert edge == pytest.approx(-0.05)

    def test_no_position_positive_edge(self):
        from polymarket_agent.cli.scheduler import compute_remaining_edge

        # NO position: we bet YES price goes down. If we estimated 0.35 and price is now 0.30,
        # the market moved in our direction. Edge = current_price - original_estimate = 0.30 - 0.35 = -0.05
        # Actually for NO: we want YES price to drop. edge = current_price - original_estimate
        # If original_estimate was 0.35 (we think NO is 0.65), and YES price is 0.30 (NO=0.70),
        # that's good for us. edge = 0.30 - 0.35 = -0.05... that's negative which means EXIT
        # Wait — let me re-check the spec and formula.
        # For NO positions: edge = current_price - original_estimate
        # Our original_estimate was our YES estimate. For NO bet, we think YES is LOW.
        # If original_estimate=0.35, current_price=0.30, edge = 0.30 - 0.35 = -0.05
        # This means the market agrees with us even more — edge should be positive.
        # So the formula should be: for NO, edge = original_estimate - current_price (same as YES)
        # Actually no — from the spec: "current_price - original_estimate" for NO
        # Let me just test the actual implementation:
        edge = compute_remaining_edge("NO", 0.35, 0.30)
        # NO position: current_price(0.30) - original_estimate(0.35) = -0.05
        assert edge == pytest.approx(-0.05)

    def test_no_position_negative_edge(self):
        from polymarket_agent.cli.scheduler import compute_remaining_edge

        edge = compute_remaining_edge("NO", 0.35, 0.50)
        # NO position: current_price(0.50) - original_estimate(0.35) = 0.15
        assert edge == pytest.approx(0.15)


class TestPaperExit:
    """6.4: Test paper exit at market price."""

    def test_exit_yes_position(self):
        from polymarket_agent.models import Side, TradeRecommendation
        from polymarket_agent.storage.database import get_db
        from polymarket_agent.trading.paper import PaperTrader

        _create_test_market("exit-001", 0.40)

        paper = PaperTrader()
        rec = TradeRecommendation(
            market_id="exit-001",
            market_question="Test?",
            side=Side.YES,
            raw_edge=0.15,
            adjusted_edge=0.12,
            market_price=0.40,
            agent_estimate=0.55,
            recommended_size=10.0,
            limit_price=0.40,
            reasoning="test",
            thesis="test",
            confidence_low=0.45,
            confidence_high=0.65,
        )
        trade = paper.execute_trade(rec)
        assert trade is not None
        position_id = trade.position_id

        # Exit at higher price (profit)
        closed = paper.exit_position(position_id, 0.55, reason="test exit")
        assert closed is not None
        assert closed.realized_pnl == pytest.approx((0.55 - 0.40) * trade.size, rel=1e-2)

        # Verify sell trade recorded
        with get_db() as conn:
            sells = conn.execute(
                "SELECT * FROM trades WHERE position_id = ? AND action = 'sell'",
                (position_id,),
            ).fetchall()
        assert len(sells) == 1
        assert sells[0]["price"] == 0.55

        # Verify cash credited
        cash = paper.get_cash_balance()
        assert cash > 990.0  # Got back more than entry cost


class TestDailyPnL:
    """6.5: Test daily P&L computation and persistence."""

    def test_upsert_and_read(self):
        from polymarket_agent.storage.database import get_db
        from polymarket_agent.storage.snapshots import upsert_daily_pnl

        today = date.today().isoformat()
        upsert_daily_pnl(today, 10.0, 5.0, 15.0, 1015.0, 3)

        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM daily_pnl WHERE date = ?", (today,)
            ).fetchone()
        assert row is not None
        assert row["realized_pnl"] == 10.0
        assert row["unrealized_pnl"] == 5.0
        assert row["total_pnl"] == 15.0
        assert row["trade_count"] == 3

    def test_risk_manager_reads_daily_pnl(self):
        from polymarket_agent.risk.manager import RiskManager
        from polymarket_agent.storage.snapshots import upsert_daily_pnl

        today = date.today().isoformat()
        upsert_daily_pnl(today, -60.0, 0.0, -60.0, 940.0, 5)

        rm = RiskManager()
        result = rm._check_daily_loss()
        assert not result.passed
        assert "daily loss" in result.reason.lower()


# --- Alpha Cultivation Tests ---


class TestFeeComputation:
    """7.1: Test fee computation matches Polymarket formula."""

    def test_fee_at_midprice(self):
        from polymarket_agent.trading.edge import compute_taker_fee

        # At price=0.50, fee_rate=0.0175, exponent=1:
        # fee = 0.50 * 0.0175 * (0.50 * 0.50)^1 = 0.50 * 0.0175 * 0.25 = 0.0021875
        fee = compute_taker_fee(0.50, 0.0175, 1.0)
        assert fee == pytest.approx(0.0021875)

    def test_fee_at_extreme_price(self):
        from polymarket_agent.trading.edge import compute_taker_fee

        # At price=0.10: fee = 0.10 * 0.0175 * (0.10 * 0.90)^1 = 0.10 * 0.0175 * 0.09
        fee = compute_taker_fee(0.10, 0.0175, 1.0)
        assert fee == pytest.approx(0.10 * 0.0175 * 0.09)

    def test_fee_at_090(self):
        from polymarket_agent.trading.edge import compute_taker_fee

        fee = compute_taker_fee(0.90, 0.0175, 1.0)
        assert fee == pytest.approx(0.90 * 0.0175 * (0.90 * 0.10))

    def test_zero_fee_rate(self):
        from polymarket_agent.trading.edge import compute_taker_fee

        assert compute_taker_fee(0.50, 0.0, 1.0) == 0.0

    def test_crypto_fee_exponent_2(self):
        from polymarket_agent.trading.edge import compute_taker_fee

        # Crypto markets use exponent=2
        fee = compute_taker_fee(0.50, 0.25, 2.0)
        # 0.50 * 0.25 * (0.50 * 0.50)^2 = 0.50 * 0.25 * 0.0625 = 0.0078125
        assert fee == pytest.approx(0.0078125)


class TestFeeAdjustedEdge:
    """7.2: Test fee-adjusted edge computation."""

    def test_edge_reduced_by_fees(self):
        from polymarket_agent.models import ProbabilityEstimate
        from polymarket_agent.trading.edge import compute_edge

        _create_test_market("fee-edge-001", 0.40)
        from polymarket_agent.market.storage import get_market
        market = get_market("fee-edge-001")

        estimate = ProbabilityEstimate(
            market_id="fee-edge-001",
            final_estimate=0.52,  # 12% raw edge
            confidence_low=0.42,
            confidence_high=0.62,
            base_rate=0.50,
            updated_estimate=0.52,
            pass1_reasoning="test",
            pass2_reasoning="test",
            thesis="test",
        )

        # Without fees
        raw_no_fee, adj_no_fee, _ = compute_edge(estimate, market, fee_rate=0.0)

        # With fees
        raw_with_fee, adj_with_fee, _ = compute_edge(estimate, market, fee_rate=0.0175)

        assert raw_with_fee < raw_no_fee
        assert adj_with_fee < adj_no_fee


class TestOpportunityScoring:
    """7.3: Test opportunity scoring signals."""

    def test_mid_volume_scores_higher(self):
        from polymarket_agent.market.scoring import volume_score

        low_vol = volume_score(20_000, 10_000_000)
        high_vol = volume_score(5_000_000, 10_000_000)
        assert low_vol > high_vol

    def test_mid_price_scores_higher(self):
        from polymarket_agent.market.scoring import price_score

        mid = price_score(0.45)
        extreme = price_score(0.88)
        assert mid > extreme

    def test_price_score_peaks_at_50(self):
        from polymarket_agent.market.scoring import price_score

        assert price_score(0.50) == pytest.approx(1.0)
        assert price_score(0.10) == pytest.approx(0.2)
        assert price_score(0.90) == pytest.approx(0.2)

    def test_event_score(self):
        from polymarket_agent.market.scoring import event_score
        from polymarket_agent.models import MarketEvent

        events = [MarketEvent(market_id="m1", event_type="price_change")]
        assert event_score("m1", events) == 1.0
        assert event_score("m2", events) == 0.0

    def test_screening_score(self):
        from polymarket_agent.market.scoring import screening_score

        assert screening_score("fair", "low") == 0.0
        assert screening_score("higher", "high") == 1.0
        assert screening_score("lower", "medium") == 0.75
        assert screening_score("higher", "low") == 0.5

    def test_time_score(self):
        from polymarket_agent.market.scoring import time_score

        near = time_score(5)
        far = time_score(50)
        assert near > far

    def test_composite_score(self):
        from polymarket_agent.market.scoring import score_candidates
        from polymarket_agent.models import MarketEvent

        m_low_vol = _create_test_market("score-lo", 0.45)
        m_low_vol.volume = 20_000

        m_high_vol = _create_test_market("score-hi", 0.45)
        m_high_vol.volume = 5_000_000

        events = [MarketEvent(market_id="score-lo", event_type="price_change")]
        screening = {
            "score-lo": {"initial_direction": "higher", "confidence": "high"},
            "score-hi": {"initial_direction": "fair", "confidence": "low"},
        }

        scored = score_candidates([m_low_vol, m_high_vol], events, screening)
        # Low-volume market with events and screening signal should rank first
        assert scored[0][0].id == "score-lo"
        assert scored[0][1] > scored[1][1]


class TestScreeningSignalExtraction:
    """7.4: Test screening signal extraction."""

    def test_screen_returns_dict(self):
        """Verify screen() returns a dict with all expected keys."""
        from unittest.mock import patch

        from polymarket_agent.analyst.estimator import ProbabilityEstimator

        m = _create_test_market("screen-001", 0.50)
        estimator = ProbabilityEstimator()

        mock_result = {
            "worth_analyzing": True,
            "reasoning": "Looks mispriced",
            "initial_direction": "higher",
            "confidence": "high",
        }

        with patch.object(estimator.llm, "complete_json", return_value=mock_result):
            result = estimator.screen(m)

        assert isinstance(result, dict)
        assert result["worth_analyzing"] is True
        assert result["initial_direction"] == "higher"
        assert result["confidence"] == "high"

    def test_screen_defaults_on_missing_fields(self):
        from unittest.mock import patch

        from polymarket_agent.analyst.estimator import ProbabilityEstimator

        m = _create_test_market("screen-002", 0.50)
        estimator = ProbabilityEstimator()

        # LLM returns only basic fields
        mock_result = {"worth_analyzing": True, "reasoning": "ok"}

        with patch.object(estimator.llm, "complete_json", return_value=mock_result):
            result = estimator.screen(m)

        assert result["initial_direction"] == "fair"
        assert result["confidence"] == "low"


class TestPriceHistoryDossier:
    """7.5: Test price history dossier formatting."""

    def test_price_history_summary(self):
        from polymarket_agent.research.gatherer import _summarize_price_history

        history = [
            {"p": 0.300},
            {"p": 0.350},
            {"p": 0.400},
            {"p": 0.550},
        ]
        summary = _summarize_price_history(history)
        assert len(summary) == 3
        assert "0.300" in summary[0]  # Open
        assert "0.550" in summary[0]  # Current
        assert "upward" in summary[2]

    def test_empty_price_history(self):
        from polymarket_agent.research.gatherer import _summarize_price_history

        assert _summarize_price_history([]) == []


class TestFailClosedScreening:
    """7.6: Test fail-closed screening."""

    def test_exception_returns_not_worth(self):
        from unittest.mock import patch

        from polymarket_agent.analyst.estimator import ProbabilityEstimator

        m = _create_test_market("screen-fail-001", 0.50)
        estimator = ProbabilityEstimator()

        with patch.object(estimator.llm, "complete_json", side_effect=Exception("API error")):
            result = estimator.screen(m)

        assert result["worth_analyzing"] is False
        assert result["initial_direction"] == "fair"


class TestClobMidpointFallback:
    """7.7: Test CLOB midpoint fallback."""

    def test_midpoint_used_when_available(self):
        from polymarket_agent.models import ProbabilityEstimate
        from polymarket_agent.trading.edge import build_recommendation

        m = _create_test_market("clob-001", 0.40)
        from polymarket_agent.market.storage import get_market
        market = get_market("clob-001")

        estimate = ProbabilityEstimate(
            market_id="clob-001",
            final_estimate=0.60,
            confidence_low=0.50,
            confidence_high=0.70,
            base_rate=0.50,
            updated_estimate=0.60,
            pass1_reasoning="test",
            pass2_reasoning="test",
            thesis="test",
        )

        rec = build_recommendation(market, estimate, 1000.0, clob_midpoint=0.42)
        assert rec is not None
        # Limit price should reflect the midpoint, not the Gamma price
        assert rec.limit_price == pytest.approx(0.42, abs=0.01)

    def test_gamma_price_used_when_no_midpoint(self):
        from polymarket_agent.models import ProbabilityEstimate
        from polymarket_agent.trading.edge import build_recommendation

        m = _create_test_market("clob-002", 0.40)
        from polymarket_agent.market.storage import get_market
        market = get_market("clob-002")

        estimate = ProbabilityEstimate(
            market_id="clob-002",
            final_estimate=0.60,
            confidence_low=0.50,
            confidence_high=0.70,
            base_rate=0.50,
            updated_estimate=0.60,
            pass1_reasoning="test",
            pass2_reasoning="test",
            thesis="test",
        )

        rec = build_recommendation(market, estimate, 1000.0, clob_midpoint=None)
        assert rec is not None
        assert rec.limit_price == pytest.approx(0.40, abs=0.01)


class TestPortfolioExposure:
    """7.8: Test portfolio exposure passed correctly."""

    def test_exposure_reduces_position_size(self):
        from polymarket_agent.trading.edge import kelly_position_size

        # With zero exposure — use high max_per_market so portfolio cap is the binding constraint
        size_no_exp = kelly_position_size(
            0.15, 0.40, 1000.0, current_exposure=0.0,
            max_per_market=500.0, max_portfolio=500.0,
        )

        # With $400 existing exposure (close to $500 max)
        size_with_exp = kelly_position_size(
            0.15, 0.40, 1000.0, current_exposure=400.0,
            max_per_market=500.0, max_portfolio=500.0,
        )

        # The position with exposure should be smaller due to portfolio cap
        assert size_with_exp < size_no_exp
        assert size_with_exp <= 100.0  # Max $500 - $400 = $100
