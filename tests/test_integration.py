"""Integration tests for the Polymarket agent."""

import os
from datetime import datetime, timedelta, timezone
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
