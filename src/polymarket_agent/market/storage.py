"""Market storage: save/update markets in SQLite."""

import logging
from datetime import datetime

from polymarket_agent.models import Market
from polymarket_agent.storage.database import get_db

logger = logging.getLogger(__name__)


def _upsert_market_row(conn, market: Market) -> None:
    """Insert or update a market using an existing connection."""
    conn.execute(
        """
        INSERT INTO markets (
            id, condition_id, question, description, category, end_date,
            outcome_yes_token, outcome_no_token, volume, liquidity,
            last_price_yes, last_price_no, active, resolved,
            resolution_outcome, first_seen_at, last_updated_at,
            event_id, event_title
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            question = excluded.question,
            description = excluded.description,
            category = excluded.category,
            end_date = excluded.end_date,
            outcome_yes_token = excluded.outcome_yes_token,
            outcome_no_token = excluded.outcome_no_token,
            volume = excluded.volume,
            liquidity = excluded.liquidity,
            last_price_yes = excluded.last_price_yes,
            last_price_no = excluded.last_price_no,
            active = excluded.active,
            resolved = excluded.resolved,
            resolution_outcome = excluded.resolution_outcome,
            last_updated_at = excluded.last_updated_at,
            event_id = excluded.event_id,
            event_title = excluded.event_title
        """,
        (
            market.id,
            market.condition_id,
            market.question,
            market.description,
            market.category,
            market.end_date.isoformat() if market.end_date else None,
            market.outcome_yes_token,
            market.outcome_no_token,
            market.volume,
            market.liquidity,
            market.last_price_yes,
            market.last_price_no,
            1 if market.active else 0,
            1 if market.resolved else 0,
            market.resolution_outcome,
            market.first_seen_at.isoformat() if market.first_seen_at else None,
            datetime.utcnow().isoformat(),
            market.event_id,
            market.event_title,
        ),
    )


def upsert_market(market: Market) -> None:
    """Insert or update a market in the database."""
    with get_db() as conn:
        _upsert_market_row(conn, market)


def upsert_markets(markets: list[Market]) -> int:
    """Bulk upsert markets in a single transaction. Returns count processed."""
    with get_db() as conn:
        for market in markets:
            _upsert_market_row(conn, market)
    logger.info("Upserted %d markets", len(markets))
    return len(markets)


def get_market(market_id: str) -> Market | None:
    """Get a market by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
        if row is None:
            return None
        return _row_to_market(row)


def get_all_active_markets() -> list[Market]:
    """Get all active markets from the database."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM markets WHERE active = 1").fetchall()
        return [_row_to_market(row) for row in rows]


def get_markets_by_category(category: str) -> list[Market]:
    """Get active markets in a specific category."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM markets WHERE active = 1 AND lower(category) = lower(?)",
            (category,),
        ).fetchall()
        return [_row_to_market(row) for row in rows]


def _row_to_market(row) -> Market:
    return Market(
        id=row["id"],
        condition_id=row["condition_id"],
        question=row["question"],
        description=row["description"],
        category=row["category"],
        end_date=datetime.fromisoformat(row["end_date"]) if row["end_date"] else None,
        outcome_yes_token=row["outcome_yes_token"],
        outcome_no_token=row["outcome_no_token"],
        volume=row["volume"] or 0,
        liquidity=row["liquidity"] or 0,
        last_price_yes=row["last_price_yes"],
        last_price_no=row["last_price_no"],
        active=bool(row["active"]),
        resolved=bool(row["resolved"]),
        resolution_outcome=row["resolution_outcome"],
        first_seen_at=(
            datetime.fromisoformat(row["first_seen_at"]) if row["first_seen_at"] else None
        ),
        last_updated_at=(
            datetime.fromisoformat(row["last_updated_at"]) if row["last_updated_at"] else None
        ),
        event_id=row["event_id"],
        event_title=row["event_title"],
    )
