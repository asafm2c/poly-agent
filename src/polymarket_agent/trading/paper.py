"""Paper trading: virtual portfolio, trade execution, P&L tracking."""

import logging
from datetime import datetime

from polymarket_agent.config import settings
from polymarket_agent.models import (
    Position,
    PortfolioSummary,
    PositionStatus,
    Side,
    Trade,
    TradeAction,
    TradingMode,
    TradeRecommendation,
)
from polymarket_agent.storage.database import get_db

logger = logging.getLogger(__name__)


class PaperTrader:
    def __init__(self):
        self._ensure_portfolio()

    def _ensure_portfolio(self):
        """Create portfolio if it doesn't exist."""
        with get_db() as conn:
            row = conn.execute("SELECT id FROM portfolio WHERE id = 1").fetchone()
            if not row:
                now = datetime.utcnow().isoformat()
                conn.execute(
                    "INSERT INTO portfolio (id, cash_balance, mode, created_at, updated_at) "
                    "VALUES (1, ?, 'paper', ?, ?)",
                    (settings.paper_starting_balance, now, now),
                )

    def get_cash_balance(self) -> float:
        with get_db() as conn:
            row = conn.execute("SELECT cash_balance FROM portfolio WHERE id = 1").fetchone()
            return row["cash_balance"] if row else 0.0

    def execute_trade(self, rec: TradeRecommendation) -> Trade | None:
        """Execute a paper trade based on a recommendation."""
        cost = rec.recommended_size
        cash = self.get_cash_balance()

        if cost > cash:
            logger.warning(
                "Insufficient cash for paper trade: need $%.2f, have $%.2f", cost, cash
            )
            return None

        now = datetime.utcnow()
        shares = rec.recommended_size / rec.limit_price

        with get_db() as conn:
            # Create position
            cursor = conn.execute(
                """INSERT INTO positions
                (market_id, side, size, entry_price, entry_timestamp, status, mode)
                VALUES (?, ?, ?, ?, ?, 'open', 'paper')""",
                (rec.market_id, rec.side.value, shares, rec.limit_price, now.isoformat()),
            )
            position_id = cursor.lastrowid

            # Record trade
            conn.execute(
                """INSERT INTO trades
                (market_id, position_id, side, action, size, price, timestamp, mode, status)
                VALUES (?, ?, ?, 'buy', ?, ?, ?, 'paper', 'filled')""",
                (
                    rec.market_id,
                    position_id,
                    rec.side.value,
                    shares,
                    rec.limit_price,
                    now.isoformat(),
                ),
            )

            # Deduct cash
            conn.execute(
                "UPDATE portfolio SET cash_balance = cash_balance - ?, updated_at = ? WHERE id = 1",
                (cost, now.isoformat()),
            )

        logger.info(
            "Paper trade: BUY %.2f %s shares @ $%.4f ($%.2f) on %s",
            shares,
            rec.side.value,
            rec.limit_price,
            cost,
            rec.market_question[:40],
        )

        return Trade(
            market_id=rec.market_id,
            position_id=position_id,
            side=rec.side,
            action=TradeAction.BUY,
            size=shares,
            price=rec.limit_price,
            timestamp=now,
            mode=TradingMode.PAPER,
        )

    def resolve_positions(self, market_id: str, outcome: str) -> list[Position]:
        """Resolve positions when a market resolves. outcome is 'YES' or 'NO'."""
        resolved = []
        now = datetime.utcnow()

        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE market_id = ? AND status = 'open'",
                (market_id,),
            ).fetchall()

            for row in rows:
                side = row["side"]
                size = row["size"]
                entry_price = row["entry_price"]

                # Calculate P&L
                if side == outcome:
                    # Won: each share pays $1
                    payout = size * 1.0
                    cost = size * entry_price
                    pnl = payout - cost
                else:
                    # Lost: shares worth $0
                    pnl = -(size * entry_price)

                # Update position
                conn.execute(
                    """UPDATE positions SET
                    exit_price = ?, exit_timestamp = ?, realized_pnl = ?, status = 'closed'
                    WHERE id = ?""",
                    (1.0 if side == outcome else 0.0, now.isoformat(), pnl, row["id"]),
                )

                # Add payout to cash
                if side == outcome:
                    conn.execute(
                        "UPDATE portfolio SET cash_balance = cash_balance + ?, updated_at = ? "
                        "WHERE id = 1",
                        (payout, now.isoformat()),
                    )

                resolved.append(
                    Position(
                        id=row["id"],
                        market_id=market_id,
                        side=Side(side),
                        size=size,
                        entry_price=entry_price,
                        entry_timestamp=datetime.fromisoformat(row["entry_timestamp"]),
                        exit_price=1.0 if side == outcome else 0.0,
                        exit_timestamp=now,
                        realized_pnl=pnl,
                        status=PositionStatus.CLOSED,
                        mode=TradingMode.PAPER,
                    )
                )

                logger.info(
                    "Resolved position %d: %s %s → %s (P&L: $%.2f)",
                    row["id"],
                    side,
                    market_id[:8],
                    outcome,
                    pnl,
                )

        return resolved

    def get_portfolio_summary(self, current_prices: dict[str, float] | None = None) -> PortfolioSummary:
        """Get current portfolio summary."""
        cash = self.get_cash_balance()
        positions = []
        unrealized = 0.0
        realized = 0.0

        with get_db() as conn:
            # Open positions
            open_rows = conn.execute(
                "SELECT * FROM positions WHERE status = 'open' AND mode = 'paper'"
            ).fetchall()
            for row in open_rows:
                current_price = None
                if current_prices:
                    current_price = current_prices.get(row["market_id"])
                pos_value = row["size"] * (current_price or row["entry_price"])
                entry_cost = row["size"] * row["entry_price"]
                unrealized += pos_value - entry_cost

                positions.append(
                    Position(
                        id=row["id"],
                        market_id=row["market_id"],
                        side=Side(row["side"]),
                        size=row["size"],
                        entry_price=row["entry_price"],
                        entry_timestamp=datetime.fromisoformat(row["entry_timestamp"]),
                        status=PositionStatus.OPEN,
                        mode=TradingMode.PAPER,
                    )
                )

            # Realized P&L from closed positions
            row = conn.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0) as total FROM positions "
                "WHERE status = 'closed' AND mode = 'paper'"
            ).fetchone()
            realized = row["total"] if row else 0.0

        total_position_value = sum(
            p.size * (current_prices.get(p.market_id, p.entry_price) if current_prices else p.entry_price)
            for p in positions
        )
        total_value = cash + total_position_value
        starting = settings.paper_starting_balance
        total_return = ((total_value - starting) / starting * 100) if starting > 0 else 0.0

        return PortfolioSummary(
            cash_balance=round(cash, 2),
            total_position_value=round(total_position_value, 2),
            total_portfolio_value=round(total_value, 2),
            open_positions=len(positions),
            realized_pnl=round(realized, 2),
            unrealized_pnl=round(unrealized, 2),
            total_return_pct=round(total_return, 2),
            mode=TradingMode.PAPER,
            positions=positions,
        )

    def get_trade_history(self, limit: int = 50) -> list[Trade]:
        """Get trade history."""
        trades = []
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE mode = 'paper' ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            for row in rows:
                trades.append(
                    Trade(
                        id=row["id"],
                        market_id=row["market_id"],
                        position_id=row["position_id"],
                        side=Side(row["side"]),
                        action=TradeAction(row["action"]),
                        size=row["size"],
                        price=row["price"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        mode=TradingMode.PAPER,
                        status=row["status"],
                    )
                )
        return trades
