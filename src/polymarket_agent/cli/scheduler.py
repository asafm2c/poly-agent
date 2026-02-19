"""Agent scheduler: orchestrates periodic scanning, analysis, and trading."""

import logging
import threading
from datetime import date, datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from polymarket_agent.analyst.estimator import ProbabilityEstimator
from polymarket_agent.config import settings
from polymarket_agent.market.clob_client import ClobClient
from polymarket_agent.market.scanner import MarketScanner
from polymarket_agent.market.scoring import score_candidates
from polymarket_agent.market.storage import (
    get_open_position_market_ids,
    get_unresolved_prediction_market_ids,
)
from polymarket_agent.models import Market, MarketEvent
from polymarket_agent.risk.manager import RiskManager
from polymarket_agent.storage.snapshots import (
    cleanup_old_snapshots,
    get_latest_prices,
    insert_price_snapshots,
    upsert_daily_pnl,
)
from polymarket_agent.trading.calibration import (
    export_calibration_for_llm,
    get_prediction_for_position,
    record_prediction,
    update_prediction_outcome,
)
from polymarket_agent.backtest.strategy import load_strategy_config
from polymarket_agent.trading.edge import build_recommendation
from polymarket_agent.trading.paper import PaperTrader

logger = logging.getLogger(__name__)


def compute_remaining_edge(side: str, original_estimate: float, current_price: float) -> float:
    """Compute remaining edge for a position.

    For YES positions: original_estimate - current_price
    For NO positions: current_price - original_estimate (because we bet against YES)
    """
    if side == "YES":
        return original_estimate - current_price
    else:
        return current_price - original_estimate


class AgentScheduler:
    def __init__(self, mode: str = "paper"):
        self.mode = mode
        self.scanner = MarketScanner()
        self.clob = ClobClient()
        self.estimator = ProbabilityEstimator(clob_client=self.clob)
        self.risk = RiskManager()
        self.paper = PaperTrader()
        self._scheduler = BlockingScheduler()
        self._candidates: list[Market] = []
        self._last_events: list[MarketEvent] = []
        self._running = False
        self._lock = threading.Lock()
        self.strategy_config = load_strategy_config()

        # Log active strategy
        ms = self.strategy_config.get("market_selection", {})
        et = self.strategy_config.get("edge_thresholds", {})
        ra = self.strategy_config.get("regime_awareness", {})
        logger.info(
            "Strategy config v%d: targets=%s, avoids=%s, overrides=%s, regime=%s",
            self.strategy_config.get("version", 0),
            ms.get("target_categories") or "all",
            ms.get("avoid_categories") or "none",
            et.get("category_overrides") or "none",
            ra.get("current_regime", "unvalidated"),
        )

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

        # Re-evaluation job (skip in predict mode — no positions to manage)
        if self.mode != "predict":
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
        """Periodic scan for new markets, price snapshots, and resolution detection."""
        if not self._running or self.risk.is_kill_switch_active():
            return

        logger.info("Running scan job...")
        with self._lock:
            candidates, events = self.scanner.scan()
            self._candidates = candidates
            self._last_events = events

        if events:
            logger.info("Detected %d events", len(events))
        logger.info("Scan complete: %d candidates", len(candidates))

        # Record price snapshots and detect resolutions (skip in predict mode)
        if self.mode != "predict":
            tracked_ids = get_open_position_market_ids() | get_unresolved_prediction_market_ids()
            if tracked_ids:
                all_markets = self.scanner.last_fetched_markets or []
                tracked_markets = [m for m in all_markets if m.id in tracked_ids]
                if tracked_markets:
                    count = insert_price_snapshots(tracked_markets)
                    logger.debug("Recorded %d price snapshots", count)

            self._detect_resolutions()
        else:
            # In predict mode, still detect resolutions for calibration
            self._detect_resolutions()

    def _detect_resolutions(self):
        """Check for resolved markets with open positions or unresolved predictions."""
        from polymarket_agent.storage.database import get_db

        with get_db() as conn:
            # Find resolved markets that have open positions
            pos_rows = conn.execute(
                """SELECT DISTINCT m.id, m.resolution_outcome, m.question
                FROM markets m
                JOIN positions p ON p.market_id = m.id
                WHERE m.resolved = 1 AND p.status = 'open'"""
            ).fetchall()

            # Find resolved markets that have unresolved predictions
            pred_rows = conn.execute(
                """SELECT DISTINCT m.id, m.resolution_outcome, m.question
                FROM markets m
                JOIN predictions pr ON pr.market_id = m.id
                WHERE m.resolved = 1 AND pr.outcome IS NULL"""
            ).fetchall()

        # Combine unique resolved market IDs
        resolved = {}
        for row in pos_rows + pred_rows:
            if row["id"] not in resolved and row["resolution_outcome"]:
                resolved[row["id"]] = (row["resolution_outcome"], row["question"])

        if not resolved:
            return

        logger.info("Detected %d resolved markets with open items", len(resolved))

        for market_id, (outcome_str, question) in resolved.items():
            # Map outcome string to numeric
            outcome_value = 1.0 if outcome_str.upper() == "YES" else 0.0

            # Update prediction outcomes
            updated = update_prediction_outcome(market_id, outcome_value)
            if updated:
                logger.info(
                    "Updated %d predictions for resolved market %s: %s",
                    updated, market_id[:8], question[:40],
                )

            # Resolve paper positions
            closed = self.paper.resolve_positions(market_id, outcome_str.upper())
            if closed:
                logger.info(
                    "Closed %d positions on resolved market %s",
                    len(closed), market_id[:8],
                )

    def _analysis_job(self):
        """Analyze candidate markets using opportunity-scored pipeline.

        Flow: screen all → score → sort by score → analyze top-N.
        In predict mode: estimate and record predictions only, no trading.
        """
        if not self._running or self.risk.is_kill_switch_active():
            return

        with self._lock:
            candidates = list(self._candidates)
            events = list(self._last_events)

        if not candidates:
            logger.info("No candidates for analysis")
            return

        # Apply strategy category filters
        ms = self.strategy_config.get("market_selection", {})
        target_cats = ms.get("target_categories") or []
        avoid_cats = ms.get("avoid_categories") or []
        if target_cats or avoid_cats:
            pre_filter = len(candidates)
            if target_cats:
                candidates = [m for m in candidates if m.category in target_cats]
            if avoid_cats:
                candidates = [m for m in candidates if m.category not in avoid_cats]
            if len(candidates) != pre_filter:
                logger.info(
                    "Strategy filter: %d → %d candidates (target=%s, avoid=%s)",
                    pre_filter, len(candidates), target_cats or "all", avoid_cats or "none",
                )

        if not candidates:
            logger.info("No candidates after strategy filtering")
            return

        cap = settings.max_analyses_per_cycle
        logger.info(
            "Running analysis (%s): %d candidates, screening all, analyzing top %d...",
            self.mode, len(candidates), cap if cap > 0 else len(candidates),
        )

        # Phase 1: Screen all candidates, collecting signals
        screening_results: dict[str, dict] = {}
        screened_candidates: list[Market] = []

        for market in candidates:
            if not self._running:
                return
            result = self.estimator.screen(market)
            screening_results[market.id] = result
            if result["worth_analyzing"]:
                screened_candidates.append(market)

        logger.info(
            "Screening complete: %d/%d passed",
            len(screened_candidates), len(candidates),
        )

        if not screened_candidates:
            return

        # Phase 2: Score and sort by opportunity
        scored = score_candidates(screened_candidates, events, screening_results)

        # Log top candidates
        for market, score in scored[:5]:
            logger.info(
                "  Top candidate: %s (score=%.3f, vol=$%.0f, price=%.2f) %s",
                market.id[:8], score, market.volume,
                market.last_price_yes or 0, market.question[:50],
            )

        # Phase 3: Analyze top-N
        calibration_text = export_calibration_for_llm()

        # Only compute portfolio state when trading
        bankroll = 0.0
        current_exposure = 0.0
        if self.mode != "predict":
            bankroll = self.paper.get_cash_balance()
            portfolio_summary = self.paper.get_portfolio_summary()
            current_exposure = portfolio_summary.total_position_value

        analyzed = 0
        for market, score in scored:
            if not self._running:
                break
            if cap > 0 and analyzed >= cap:
                logger.info("Analysis cap reached (%d), deferring remaining candidates", cap)
                break
            analyzed += 1

            token_id = market.outcome_yes_token

            # Full estimation
            try:
                estimate = self.estimator.estimate(
                    market, calibration_text, token_id=token_id,
                )
            except Exception as e:
                logger.error("Estimation failed for %s: %s", market.id[:8], e)
                continue

            # In predict mode: record prediction and move on, no trading
            if self.mode == "predict":
                record_prediction(
                    estimate, market.last_price_yes or 0.5, market.category,
                )
                continue

            # Get CLOB midpoint for accurate pricing
            midpoint = None
            if token_id:
                midpoint = self.clob.get_midpoint(token_id)

            # Get per-market fee rate
            fee_rate = market.taker_base_fee or settings.default_fee_rate
            fee_exponent = settings.default_fee_exponent

            # Build recommendation with real exposure, midpoint, and fees
            rec, adj_edge, req_threshold = build_recommendation(
                market, estimate, bankroll,
                current_exposure=current_exposure,
                clob_midpoint=midpoint,
                fee_rate=fee_rate,
                fee_exponent=fee_exponent,
                strategy_config=self.strategy_config,
            )

            # Record prediction with edge/threshold data (before trade decision)
            record_prediction(
                estimate, market.last_price_yes or 0.5, market.category,
                edge=adj_edge, threshold=req_threshold,
            )

            if not rec:
                continue

            # Risk checks
            risk_token = token_id if rec.side.value == "YES" else market.outcome_no_token
            risk_result = self.risk.check_all(rec, market.category, risk_token)

            if not risk_result.passed:
                logger.info("Risk rejected trade on %s: %s", market.id[:8], risk_result.reason)
                continue

            if risk_result.adjusted_size is not None:
                rec.recommended_size = risk_result.adjusted_size

            # Execute
            if self.mode == "paper":
                trade = self.paper.execute_trade(rec)
                if trade:
                    logger.info(
                        "Paper trade executed: %s %s $%.2f (score=%.3f)",
                        rec.side.value, market.id[:8], rec.recommended_size, score,
                    )
                    # Update exposure for next iteration
                    current_exposure += rec.recommended_size
            else:
                from polymarket_agent.trading.executor import LiveExecutor
                executor = LiveExecutor()
                order_id = executor.place_order(rec)
                if order_id:
                    logger.info("Live order placed: %s", order_id)

        usage = self.estimator.llm.get_usage_summary()
        logger.info("Analysis complete. LLM cost this session: $%.4f", usage["estimated_cost"])

    def _reevaluation_job(self):
        """Re-evaluate open positions with tiered decision framework."""
        if not self._running:
            return

        summary = self.paper.get_portfolio_summary()
        if summary.open_positions == 0:
            return

        logger.info("Re-evaluating %d open positions...", summary.open_positions)

        # Get latest prices for all position markets
        position_market_ids = [p.market_id for p in summary.positions]
        latest_prices = get_latest_prices(position_market_ids)

        reanalyze_queue: list[tuple] = []  # (position, original_estimate, current_price)
        reanalyses_done = 0
        exits = 0
        holds = 0

        for pos in summary.positions:
            current_price = latest_prices.get(pos.market_id)
            if current_price is None:
                # No snapshot available — use entry price as fallback
                logger.debug("No price snapshot for %s, skipping", pos.market_id[:8])
                holds += 1
                continue

            original_estimate = get_prediction_for_position(pos.market_id)
            if original_estimate is None:
                logger.debug("No prediction found for %s, skipping", pos.market_id[:8])
                holds += 1
                continue

            edge = compute_remaining_edge(pos.side.value, original_estimate, current_price)

            # Tier 1: Mechanical decision
            if edge < settings.reeval_edge_exit_threshold:
                # Edge reversed — exit immediately
                self.paper.exit_position(pos.id, current_price, reason="edge reversed")
                exits += 1
            elif edge >= settings.min_edge_threshold:
                # Edge still healthy — hold
                logger.debug(
                    "HOLD %s %s: edge=%.3f (estimate=%.3f, price=%.3f)",
                    pos.side.value, pos.market_id[:8], edge, original_estimate, current_price,
                )
                holds += 1
            else:
                # Ambiguous zone or stale — queue for re-analysis
                days_held = (datetime.utcnow() - pos.entry_timestamp).days
                if edge < settings.reeval_reanalysis_threshold or days_held >= settings.reeval_staleness_days:
                    reanalyze_queue.append((pos, original_estimate, current_price))
                else:
                    holds += 1

        # Tier 2: LLM re-analysis for ambiguous positions
        cap = settings.max_reanalyses_per_cycle
        for pos, original_estimate, current_price in reanalyze_queue:
            if not self._running:
                break
            if reanalyses_done >= cap:
                logger.info("Re-analysis cap reached (%d), deferring %d positions",
                           cap, len(reanalyze_queue) - reanalyses_done)
                holds += len(reanalyze_queue) - reanalyses_done
                break

            from polymarket_agent.market.storage import get_market
            market = get_market(pos.market_id)
            if not market:
                holds += 1
                continue

            logger.info("Re-analyzing %s %s (edge=%.3f)...",
                       pos.side.value, pos.market_id[:8],
                       compute_remaining_edge(pos.side.value, original_estimate, current_price))

            try:
                calibration_text = export_calibration_for_llm()
                new_estimate = self.estimator.estimate(market, calibration_text)
                reanalyses_done += 1

                new_edge = compute_remaining_edge(
                    pos.side.value, new_estimate.final_estimate, current_price
                )

                if new_edge < settings.min_edge_threshold:
                    # Re-analysis confirms edge is gone
                    self.paper.exit_position(
                        pos.id, current_price,
                        reason=f"re-analysis: new_est={new_estimate.final_estimate:.3f}, "
                               f"old_est={original_estimate:.3f}, edge={new_edge:.3f}",
                    )
                    exits += 1
                else:
                    logger.info(
                        "HOLD after re-analysis %s: new_edge=%.3f (new_est=%.3f)",
                        pos.market_id[:8], new_edge, new_estimate.final_estimate,
                    )
                    holds += 1
            except Exception as e:
                logger.error("Re-analysis failed for %s: %s", pos.market_id[:8], e)
                holds += 1

        logger.info(
            "Re-evaluation complete: %d exits, %d holds, %d re-analyses",
            exits, holds, reanalyses_done,
        )

    def _daily_report_job(self):
        """Generate daily report, persist P&L, and clean up old snapshots."""
        # Get latest prices for mark-to-market
        open_market_ids = list(self.paper.get_open_position_market_ids())
        latest_prices = get_latest_prices(open_market_ids) if open_market_ids else {}

        summary = self.paper.get_portfolio_summary(current_prices=latest_prices)
        usage = self.estimator.llm.get_usage_summary()

        # Compute daily P&L
        today = date.today().isoformat()
        from polymarket_agent.storage.database import get_db
        with get_db() as conn:
            # Realized P&L from positions closed today
            row = conn.execute(
                """SELECT COALESCE(SUM(realized_pnl), 0) as today_realized,
                          COUNT(*) as trade_count
                FROM positions
                WHERE status = 'closed' AND exit_timestamp >= ?""",
                (today,),
            ).fetchone()
            today_realized = row["today_realized"]
            trade_count = row["trade_count"]

        unrealized = summary.unrealized_pnl
        total_pnl = today_realized + unrealized

        # Persist daily P&L
        upsert_daily_pnl(
            date=today,
            realized_pnl=today_realized,
            unrealized_pnl=unrealized,
            total_pnl=total_pnl,
            portfolio_value=summary.total_portfolio_value,
            trade_count=trade_count,
        )

        # Clean up old snapshots and metrics
        deleted = cleanup_old_snapshots(settings.snapshot_retention_days)
        from polymarket_agent.metrics import cleanup_old_metrics
        metrics_deleted = cleanup_old_metrics(30)

        # Calibration stats
        from polymarket_agent.trading.calibration import compute_brier_comparison, compute_calibration
        cal = compute_calibration()

        logger.info("=== DAILY REPORT ===")
        logger.info("Portfolio: $%.2f (cash: $%.2f)", summary.total_portfolio_value, summary.cash_balance)
        logger.info("Positions: %d open", summary.open_positions)
        logger.info("P&L today: realized=$%.2f, unrealized=$%.2f, total=$%.2f",
                    today_realized, unrealized, total_pnl)
        logger.info("P&L all-time: realized=$%.2f, return=%+.2f%%",
                    summary.realized_pnl, summary.total_return_pct)
        logger.info("Predictions: %d total, %d resolved, %d unresolved",
                    cal.total_predictions, cal.resolved_predictions,
                    cal.total_predictions - cal.resolved_predictions)
        logger.info("Calibration: %d resolved%s",
                    cal.resolved_predictions,
                    f", Brier={cal.brier_score:.4f}" if cal.brier_score is not None else "")

        # Brier comparison: agent vs market
        brier_cmp = compute_brier_comparison()
        if brier_cmp:
            diff = brier_cmp["difference"]
            signal = "AGENT BETTER" if diff < 0 else "MARKET BETTER"
            logger.info(
                "Brier comparison (%d resolved): agent=%.4f, market=%.4f, diff=%+.4f (%s)",
                brier_cmp["resolved_count"],
                brier_cmp["agent_brier"], brier_cmp["market_brier"],
                diff, signal,
            )

        logger.info("LLM usage: %d calls, ~$%.4f total", usage["calls"], usage["estimated_cost"])
        if deleted:
            logger.info("Snapshot cleanup: %d old records removed", deleted)
        if metrics_deleted:
            logger.info("Metrics cleanup: %d old events removed", metrics_deleted)

        # Strategy drift monitoring
        self._check_strategy_drift()

        logger.info("=== END REPORT ===")

    def _check_strategy_drift(self):
        """Compare per-category Brier scores against strategy expectations."""
        from polymarket_agent.storage.database import get_db

        et = self.strategy_config.get("edge_thresholds", {})
        overrides = et.get("category_overrides", {})
        if not overrides:
            return

        # Expected efficiency baseline: 0.25 (coin-flip). Categories with overrides
        # imply the strategy believes they deviate from this.
        expected_brier = 0.25

        with get_db() as conn:
            rows = conn.execute(
                """SELECT category, AVG((agent_estimate - outcome) * (agent_estimate - outcome)) as brier,
                          COUNT(*) as count
                FROM predictions
                WHERE outcome IS NOT NULL AND category IS NOT NULL
                GROUP BY category"""
            ).fetchall()

        for row in rows:
            cat = row["category"]
            count = row["count"]
            brier = row["brier"]

            if count < 10:
                logger.info(
                    "Strategy drift: insufficient data for %s (%d predictions)",
                    cat, count,
                )
                continue

            if cat in overrides:
                drift = brier - expected_brier
                if abs(drift) > 0.05:
                    logger.warning(
                        "Strategy drift: %s Brier=%.4f vs expected=%.4f (drift=%+.4f). "
                        "Research review recommended.",
                        cat, brier, expected_brier, drift,
                    )
                else:
                    logger.info("Strategy aligned: %s Brier=%.4f", cat, brier)
