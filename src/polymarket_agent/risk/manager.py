"""Risk manager: enforce position limits, portfolio exposure, daily loss, kill switch."""

import logging
from datetime import date, datetime

from polymarket_agent.config import settings
from polymarket_agent.market.clob_client import ClobClient
from polymarket_agent.models import RiskCheckResult, Side, TradeRecommendation
from polymarket_agent.storage.database import get_db

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, clob_client: ClobClient | None = None):
        self.clob = clob_client or ClobClient()

    def check_all(
        self,
        recommendation: TradeRecommendation,
        market_category: str | None = None,
        token_id: str | None = None,
    ) -> RiskCheckResult:
        """Run all risk checks. Returns result with pass/fail and adjusted size."""
        checks = [
            self._check_kill_switch(),
            self._check_daily_loss(),
            self._check_per_market(recommendation),
            self._check_portfolio_exposure(recommendation),
        ]
        if market_category:
            checks.append(self._check_category_exposure(recommendation, market_category))
        if token_id:
            checks.append(self._check_liquidity(recommendation, token_id))

        for check in checks:
            if not check.passed:
                return check

        return RiskCheckResult(passed=True)

    def _check_kill_switch(self) -> RiskCheckResult:
        with get_db() as conn:
            row = conn.execute("SELECT active FROM kill_switch WHERE id = 1").fetchone()
            if row and row["active"]:
                return RiskCheckResult(passed=False, reason="Kill switch is active")
        return RiskCheckResult(passed=True)

    def _check_per_market(self, rec: TradeRecommendation) -> RiskCheckResult:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(size * entry_price), 0) as exposure "
                "FROM positions WHERE market_id = ? AND status = 'open'",
                (rec.market_id,),
            ).fetchone()
            current = row["exposure"] if row else 0.0

        max_allowed = settings.max_position_per_market
        remaining = max_allowed - current
        if remaining <= 0:
            return RiskCheckResult(
                passed=False,
                reason=f"Per-market limit reached (${current:.2f} / ${max_allowed:.2f})",
            )
        if rec.recommended_size > remaining:
            return RiskCheckResult(
                passed=True,
                adjusted_size=round(remaining, 2),
                reason=f"Size reduced to ${remaining:.2f} (per-market limit)",
            )
        return RiskCheckResult(passed=True)

    def _check_portfolio_exposure(self, rec: TradeRecommendation) -> RiskCheckResult:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(size * entry_price), 0) as exposure "
                "FROM positions WHERE status = 'open'"
            ).fetchone()
            current = row["exposure"] if row else 0.0

        max_allowed = settings.max_portfolio_exposure
        remaining = max_allowed - current
        if remaining <= 0:
            return RiskCheckResult(
                passed=False,
                reason=f"Portfolio exposure limit reached (${current:.2f} / ${max_allowed:.2f})",
            )
        if rec.recommended_size > remaining:
            return RiskCheckResult(
                passed=True,
                adjusted_size=round(remaining, 2),
                reason=f"Size reduced to ${remaining:.2f} (portfolio limit)",
            )
        return RiskCheckResult(passed=True)

    def _check_category_exposure(
        self, rec: TradeRecommendation, category: str
    ) -> RiskCheckResult:
        with get_db() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(p.size * p.entry_price), 0) as exposure
                FROM positions p JOIN markets m ON p.market_id = m.id
                WHERE p.status = 'open' AND lower(m.category) = lower(?)""",
                (category,),
            ).fetchone()
            current = row["exposure"] if row else 0.0

        max_allowed = settings.max_category_exposure
        remaining = max_allowed - current
        if remaining <= 0:
            return RiskCheckResult(
                passed=False,
                reason=f"Category '{category}' limit reached (${current:.2f} / ${max_allowed:.2f})",
            )
        if rec.recommended_size > remaining:
            return RiskCheckResult(
                passed=True,
                adjusted_size=round(remaining, 2),
                reason=f"Size reduced to ${remaining:.2f} ({category} category limit)",
            )
        return RiskCheckResult(passed=True)

    def _check_daily_loss(self) -> RiskCheckResult:
        today = date.today().isoformat()
        with get_db() as conn:
            row = conn.execute(
                "SELECT total_pnl FROM daily_pnl WHERE date = ?", (today,)
            ).fetchone()
            daily_pnl = row["total_pnl"] if row else 0.0

        if daily_pnl <= settings.daily_loss_limit:
            return RiskCheckResult(
                passed=False,
                reason=f"Daily loss limit breached (${daily_pnl:.2f} <= ${settings.daily_loss_limit:.2f})",
            )
        return RiskCheckResult(passed=True)

    def _check_liquidity(
        self, rec: TradeRecommendation, token_id: str
    ) -> RiskCheckResult:
        max_price = rec.limit_price * (1 + settings.max_slippage)
        depth = self.clob.get_order_book_depth(token_id, max_price, side="buy")
        shares_needed = rec.recommended_size / rec.limit_price

        if depth < shares_needed:
            if depth > 0:
                adjusted_size = round(depth * rec.limit_price, 2)
                return RiskCheckResult(
                    passed=True,
                    adjusted_size=adjusted_size,
                    reason=f"Size reduced to ${adjusted_size:.2f} (liquidity limit)",
                )
            return RiskCheckResult(
                passed=False, reason="Insufficient order book liquidity"
            )
        return RiskCheckResult(passed=True)

    def activate_kill_switch(self, reason: str = "Manual activation") -> None:
        with get_db() as conn:
            conn.execute(
                "UPDATE kill_switch SET active = 1, activated_at = ?, reason = ? WHERE id = 1",
                (datetime.utcnow().isoformat(), reason),
            )
        logger.warning("KILL SWITCH ACTIVATED: %s", reason)

    def deactivate_kill_switch(self) -> None:
        with get_db() as conn:
            conn.execute(
                "UPDATE kill_switch SET active = 0, activated_at = NULL, reason = NULL WHERE id = 1"
            )
        logger.info("Kill switch deactivated")

    def is_kill_switch_active(self) -> bool:
        with get_db() as conn:
            row = conn.execute("SELECT active FROM kill_switch WHERE id = 1").fetchone()
            return bool(row["active"]) if row else False
