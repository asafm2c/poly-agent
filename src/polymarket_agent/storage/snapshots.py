"""Price snapshot storage: append-only price history and daily P&L."""

import logging
from datetime import datetime, timedelta

from polymarket_agent.models import Market
from polymarket_agent.storage.database import get_db

logger = logging.getLogger(__name__)


def insert_price_snapshots(markets: list[Market]) -> int:
    """Bulk insert price snapshots for a list of markets. Returns count inserted."""
    if not markets:
        return 0
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.executemany(
            """INSERT INTO price_snapshots (market_id, timestamp, price_yes, price_no, volume)
            VALUES (?, ?, ?, ?, ?)""",
            [
                (m.id, now, m.last_price_yes, m.last_price_no, m.volume)
                for m in markets
            ],
        )
    return len(markets)


def get_price_history(
    market_id: str, since: str | None = None
) -> list[dict]:
    """Get price snapshots for a market, optionally filtered by time.

    Returns list of dicts with keys: timestamp, price_yes, price_no, volume.
    """
    with get_db() as conn:
        if since:
            rows = conn.execute(
                """SELECT timestamp, price_yes, price_no, volume
                FROM price_snapshots
                WHERE market_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC""",
                (market_id, since),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT timestamp, price_yes, price_no, volume
                FROM price_snapshots
                WHERE market_id = ?
                ORDER BY timestamp ASC""",
                (market_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_latest_prices(market_ids: list[str]) -> dict[str, float]:
    """Get the most recent price_yes for each market ID.

    Returns dict mapping market_id → latest price_yes.
    """
    if not market_ids:
        return {}
    with get_db() as conn:
        placeholders = ",".join("?" for _ in market_ids)
        rows = conn.execute(
            f"""SELECT market_id, price_yes
            FROM price_snapshots
            WHERE id IN (
                SELECT MAX(id) FROM price_snapshots
                WHERE market_id IN ({placeholders})
                GROUP BY market_id
            )""",
            market_ids,
        ).fetchall()
    return {r["market_id"]: r["price_yes"] for r in rows if r["price_yes"] is not None}


def cleanup_old_snapshots(retention_days: int) -> int:
    """Delete snapshots older than retention_days. Returns count deleted."""
    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM price_snapshots WHERE timestamp < ?", (cutoff,)
        )
        count = cursor.rowcount
    if count:
        logger.info("Cleaned up %d price snapshots older than %d days", count, retention_days)
    return count


def upsert_daily_pnl(
    date: str,
    realized_pnl: float,
    unrealized_pnl: float,
    total_pnl: float,
    portfolio_value: float,
    trade_count: int,
) -> None:
    """Insert or update daily P&L record."""
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_pnl
            (date, realized_pnl, unrealized_pnl, total_pnl, portfolio_value, trade_count)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (date, realized_pnl, unrealized_pnl, total_pnl, portfolio_value, trade_count),
        )
