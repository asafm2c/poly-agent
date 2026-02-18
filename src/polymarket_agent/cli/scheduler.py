"""Agent scheduler: orchestrates periodic scanning, analysis, and trading."""

import logging
import threading
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from polymarket_agent.analyst.estimator import ProbabilityEstimator
from polymarket_agent.config import settings
from polymarket_agent.market.scanner import MarketScanner
from polymarket_agent.models import Market
from polymarket_agent.risk.manager import RiskManager
from polymarket_agent.trading.calibration import export_calibration_for_llm, record_prediction
from polymarket_agent.trading.edge import build_recommendation
from polymarket_agent.trading.paper import PaperTrader

logger = logging.getLogger(__name__)


class AgentScheduler:
    def __init__(self, mode: str = "paper"):
        self.mode = mode
        self.scanner = MarketScanner()
        self.estimator = ProbabilityEstimator()
        self.risk = RiskManager()
        self.paper = PaperTrader()
        self._scheduler = BlockingScheduler()
        self._candidates: list[Market] = []
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        """Start the scheduler with configured intervals."""
        self._running = True

        # Scan job
        self._scheduler.add_job(
            self._scan_job,
            IntervalTrigger(seconds=settings.scan_interval),
            id="scan",
            next_run_time=datetime.utcnow(),  # Run immediately
            misfire_grace_time=60,
            coalesce=True,
        )

        # Analysis job
        self._scheduler.add_job(
            self._analysis_job,
            IntervalTrigger(seconds=settings.analysis_interval),
            id="analysis",
            misfire_grace_time=120,
            coalesce=True,
        )

        # Re-evaluation job
        self._scheduler.add_job(
            self._reevaluation_job,
            IntervalTrigger(seconds=settings.reevaluation_interval),
            id="reevaluation",
            misfire_grace_time=120,
            coalesce=True,
        )

        # Daily report
        self._scheduler.add_job(
            self._daily_report_job,
            CronTrigger(hour=settings.daily_report_hour, minute=0),
            id="daily_report",
            misfire_grace_time=3600,
        )

        logger.info(
            "Scheduler started (%s mode): scan=%dm, analysis=%dm, reeval=%dm",
            self.mode,
            settings.scan_interval // 60,
            settings.analysis_interval // 60,
            settings.reevaluation_interval // 60,
        )

        try:
            self._scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.stop()

    def stop(self):
        """Stop the scheduler gracefully."""
        self._running = False
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
        self.scanner.close()
        logger.info("Scheduler stopped")

    def _scan_job(self):
        """Periodic scan for new markets and events."""
        if not self._running or self.risk.is_kill_switch_active():
            return

        logger.info("Running scan job...")
        with self._lock:
            candidates, events = self.scanner.scan()
            self._candidates = candidates

        if events:
            logger.info("Detected %d events", len(events))
        logger.info("Scan complete: %d candidates", len(candidates))

    def _analysis_job(self):
        """Analyze candidate markets and generate trade recommendations."""
        if not self._running or self.risk.is_kill_switch_active():
            return

        with self._lock:
            candidates = list(self._candidates)

        if not candidates:
            logger.info("No candidates for analysis")
            return

        logger.info("Running analysis on %d candidates...", len(candidates))
        calibration_text = export_calibration_for_llm()
        bankroll = self.paper.get_cash_balance()

        for market in candidates:
            if not self._running:
                break

            # Screen first
            worth, reasoning = self.estimator.screen(market)
            if not worth:
                continue

            # Full estimation
            try:
                estimate = self.estimator.estimate(market, calibration_text)
            except Exception as e:
                logger.error("Estimation failed for %s: %s", market.id[:8], e)
                continue

            # Record prediction
            record_prediction(estimate, market.last_price_yes or 0.5, market.category)

            # Build recommendation
            rec = build_recommendation(market, estimate, bankroll)
            if not rec:
                continue

            # Risk checks
            token_id = market.outcome_yes_token if rec.side.value == "YES" else market.outcome_no_token
            risk_result = self.risk.check_all(rec, market.category, token_id)

            if not risk_result.passed:
                logger.info("Risk rejected trade on %s: %s", market.id[:8], risk_result.reason)
                continue

            if risk_result.adjusted_size is not None:
                rec.recommended_size = risk_result.adjusted_size

            # Execute
            if self.mode == "paper":
                trade = self.paper.execute_trade(rec)
                if trade:
                    logger.info("Paper trade executed: %s %s $%.2f", rec.side.value, market.id[:8], rec.recommended_size)
            else:
                from polymarket_agent.trading.executor import LiveExecutor
                executor = LiveExecutor()
                order_id = executor.place_order(rec)
                if order_id:
                    logger.info("Live order placed: %s", order_id)

        usage = self.estimator.llm.get_usage_summary()
        logger.info("Analysis complete. LLM cost this session: $%.4f", usage["estimated_cost"])

    def _reevaluation_job(self):
        """Re-evaluate open positions."""
        if not self._running:
            return

        summary = self.paper.get_portfolio_summary()
        if summary.open_positions == 0:
            return

        logger.info("Re-evaluating %d open positions...", summary.open_positions)
        # For now, just log status. Full re-evaluation with exit signals
        # would require re-running analysis on each position's market.
        for pos in summary.positions:
            logger.info(
                "Position: %s %s %.2f shares @ $%.4f",
                pos.side.value,
                pos.market_id[:8],
                pos.size,
                pos.entry_price,
            )

    def _daily_report_job(self):
        """Generate daily report."""
        summary = self.paper.get_portfolio_summary()
        usage = self.estimator.llm.get_usage_summary()

        logger.info("=== DAILY REPORT ===")
        logger.info("Portfolio: $%.2f (cash: $%.2f)", summary.total_portfolio_value, summary.cash_balance)
        logger.info("Positions: %d open", summary.open_positions)
        logger.info("P&L: realized=$%.2f, unrealized=$%.2f", summary.realized_pnl, summary.unrealized_pnl)
        logger.info("Return: %+.2f%%", summary.total_return_pct)
        logger.info("LLM usage: %d calls, ~$%.4f total", usage["calls"], usage["estimated_cost"])
        logger.info("=== END REPORT ===")
