"""Live execution engine: py-clob-client integration for real CLOB orders."""

import logging
import time
from datetime import datetime

from polymarket_agent.config import settings
from polymarket_agent.models import (
    OrderStatus,
    Position,
    PositionStatus,
    Side,
    Trade,
    TradeAction,
    TradingMode,
    TradeRecommendation,
)
from polymarket_agent.storage.database import get_db

logger = logging.getLogger(__name__)


class LiveExecutor:
    def __init__(self):
        self._clob = None
        self._initialized = False

    def _init_client(self):
        """Lazily initialize the py-clob-client (requires private key)."""
        if self._initialized:
            return

        if not settings.polymarket_private_key:
            raise ValueError(
                "POLYMARKET_PRIVATE_KEY not configured. Set it in .env for live trading."
            )

        from py_clob_client.client import ClobClient

        self._clob = ClobClient(
            settings.clob_api_url,
            key=settings.polymarket_private_key,
            chain_id=settings.chain_id,
            signature_type=0,  # EOA wallet
        )

        # Derive API credentials
        creds = self._clob.create_or_derive_api_creds()
        self._clob.set_api_creds(creds)
        self._initialized = True
        logger.info("Live executor initialized with CLOB client")

    def check_balance(self) -> dict:
        """Check wallet USDC balance and allowances."""
        self._init_client()
        # The py-clob-client doesn't directly expose balance checks,
        # but we can check via the API
        try:
            bal = self._clob.get_balance_allowance(
                params={"asset_type": "COLLATERAL"}
            )
            return {"balance": bal.get("balance", "0"), "allowance": bal.get("allowance", "0")}
        except Exception as e:
            logger.error("Balance check failed: %s", e)
            return {"balance": "unknown", "allowance": "unknown", "error": str(e)}

    def place_order(self, rec: TradeRecommendation) -> str | None:
        """Place a limit order on the CLOB. Returns order ID or None on failure."""
        self._init_client()

        # Determine token ID
        with get_db() as conn:
            market = conn.execute(
                "SELECT outcome_yes_token, outcome_no_token FROM markets WHERE id = ?",
                (rec.market_id,),
            ).fetchone()

        if not market:
            logger.error("Market %s not found in database", rec.market_id)
            return None

        token_id = (
            market["outcome_yes_token"] if rec.side == Side.YES else market["outcome_no_token"]
        )
        if not token_id:
            logger.error("No token ID for %s side of market %s", rec.side.value, rec.market_id)
            return None

        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY

        shares = rec.recommended_size / rec.limit_price

        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=rec.limit_price,
                size=shares,
                side=BUY,
            )
            signed_order = self._clob.create_order(order_args)
            resp = self._clob.post_order(signed_order, OrderType.GTC)

            order_id = resp.get("orderID") or resp.get("id")
            if order_id:
                self._record_order(rec, order_id, shares)
                logger.info(
                    "Live order placed: %s %s %.2f shares @ $%.4f (order=%s)",
                    rec.side.value,
                    rec.market_id[:8],
                    shares,
                    rec.limit_price,
                    order_id,
                )
                return order_id
            else:
                logger.error("Order response missing ID: %s", resp)
                return None
        except Exception as e:
            logger.error("Order placement failed: %s", e)
            self._record_failed_order(rec, str(e))
            return None

    def _record_order(self, rec: TradeRecommendation, order_id: str, shares: float):
        """Record a placed order in the database."""
        now = datetime.utcnow().isoformat()
        with get_db() as conn:
            conn.execute(
                """INSERT INTO orders
                (id, market_id, side, action, price, size, status, created_at, updated_at)
                VALUES (?, ?, ?, 'buy', ?, ?, 'open', ?, ?)""",
                (order_id, rec.market_id, rec.side.value, rec.limit_price, shares, now, now),
            )

    def _record_failed_order(self, rec: TradeRecommendation, error: str):
        """Log a failed order attempt."""
        now = datetime.utcnow().isoformat()
        with get_db() as conn:
            conn.execute(
                """INSERT INTO trades
                (market_id, side, action, size, price, timestamp, mode, status)
                VALUES (?, ?, 'buy', ?, ?, ?, 'live', 'failed')""",
                (rec.market_id, rec.side.value, rec.recommended_size / rec.limit_price,
                 rec.limit_price, now),
            )

    def check_order_status(self, order_id: str) -> OrderStatus:
        """Check the current status of an order."""
        self._init_client()
        try:
            order = self._clob.get_order(order_id)
            status_map = {
                "LIVE": OrderStatus.OPEN,
                "MATCHED": OrderStatus.FILLED,
                "CANCELLED": OrderStatus.CANCELLED,
            }
            raw_status = order.get("status", "").upper()
            return status_map.get(raw_status, OrderStatus.OPEN)
        except Exception as e:
            logger.error("Order status check failed for %s: %s", order_id, e)
            return OrderStatus.OPEN

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        self._init_client()
        try:
            self._clob.cancel(order_id)
            now = datetime.utcnow().isoformat()
            with get_db() as conn:
                conn.execute(
                    "UPDATE orders SET status = 'cancelled', updated_at = ? WHERE id = ?",
                    (now, order_id),
                )
            logger.info("Cancelled order %s", order_id)
            return True
        except Exception as e:
            logger.error("Cancel failed for order %s: %s", order_id, e)
            return False

    def cancel_all_open_orders(self) -> int:
        """Cancel all open orders. Returns count cancelled."""
        count = 0
        with get_db() as conn:
            rows = conn.execute("SELECT id FROM orders WHERE status = 'open'").fetchall()
        for row in rows:
            if self.cancel_order(row["id"]):
                count += 1
        return count

    def check_and_update_orders(self) -> list[dict]:
        """Check status of all open orders and update accordingly."""
        updates = []
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM orders WHERE status = 'open'").fetchall()

        for row in rows:
            status = self.check_order_status(row["id"])
            if status != OrderStatus.OPEN:
                now = datetime.utcnow().isoformat()
                with get_db() as conn:
                    conn.execute(
                        "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                        (status.value, now, row["id"]),
                    )
                    if status == OrderStatus.FILLED:
                        # Create position and trade records
                        cursor = conn.execute(
                            """INSERT INTO positions
                            (market_id, side, size, entry_price, entry_timestamp, status, mode, order_id)
                            VALUES (?, ?, ?, ?, ?, 'open', 'live', ?)""",
                            (row["market_id"], row["side"], row["size"],
                             row["price"], now, row["id"]),
                        )
                        conn.execute(
                            """INSERT INTO trades
                            (market_id, position_id, side, action, size, price, timestamp, mode, order_id, status)
                            VALUES (?, ?, ?, 'buy', ?, ?, ?, 'live', ?, 'filled')""",
                            (row["market_id"], cursor.lastrowid, row["side"],
                             row["size"], row["price"], now, row["id"]),
                        )

                updates.append({"order_id": row["id"], "new_status": status.value})
                logger.info("Order %s → %s", row["id"], status.value)

        return updates

    def check_expired_orders(self) -> list[str]:
        """Cancel orders that have exceeded the timeout."""
        expired = []
        cutoff = datetime.utcnow().timestamp() - settings.order_timeout_seconds

        with get_db() as conn:
            rows = conn.execute("SELECT id, created_at FROM orders WHERE status = 'open'").fetchall()

        for row in rows:
            created = datetime.fromisoformat(row["created_at"]).timestamp()
            if created < cutoff:
                if self.cancel_order(row["id"]):
                    expired.append(row["id"])

        if expired:
            logger.info("Expired %d orders", len(expired))
        return expired
