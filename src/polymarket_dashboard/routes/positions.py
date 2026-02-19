"""Positions, trades, and price history endpoints."""

from datetime import datetime

from fastapi import APIRouter, Query, Request

router = APIRouter()


@router.get("/open")
async def open_positions(request: Request):
    db = request.app.state.db

    async with db.connection() as conn:
        rows = await conn.execute_fetchall("""
            SELECT p.id, p.market_id, p.side, p.size, p.entry_price, p.entry_timestamp,
                   m.question, m.last_price_yes, m.category,
                   pr.final_estimate, pr.confidence_low, pr.confidence_high
            FROM positions p
            JOIN markets m ON p.market_id = m.id
            LEFT JOIN (
                SELECT market_id, final_estimate, confidence_low, confidence_high,
                       ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY timestamp DESC) as rn
                FROM predictions
            ) pr ON pr.market_id = p.market_id AND pr.rn = 1
            WHERE p.status = 'open'
            ORDER BY p.entry_timestamp DESC
        """)

        # Get latest snapshot prices
        market_ids = [r["market_id"] for r in rows]
        snapshot_prices = {}
        has_snapshots = await conn.table_exists("price_snapshots")
        if market_ids and has_snapshots:
            placeholders = ",".join("?" for _ in market_ids)
            snap_rows = await conn.execute_fetchall(
                f"""SELECT market_id, price_yes
                FROM price_snapshots
                WHERE id IN (
                    SELECT MAX(id) FROM price_snapshots
                    WHERE market_id IN ({placeholders})
                    GROUP BY market_id
                )""",
                market_ids,
            )
            snapshot_prices = {
                r["market_id"]: r["price_yes"]
                for r in snap_rows
                if r["price_yes"] is not None
            }

    now = datetime.utcnow()
    positions = []
    for r in rows:
        current_price = snapshot_prices.get(r["market_id"]) or r["last_price_yes"] or r["entry_price"]

        if r["side"] == "YES":
            unrealized = (current_price - r["entry_price"]) * r["size"]
            edge_remaining = (r["final_estimate"] - current_price) if r["final_estimate"] else None
        else:
            no_current = 1.0 - current_price
            unrealized = (no_current - r["entry_price"]) * r["size"]
            edge_remaining = (current_price - r["final_estimate"]) if r["final_estimate"] else None

        entry_dt = datetime.fromisoformat(r["entry_timestamp"])
        days_held = (now - entry_dt).days

        positions.append({
            "id": r["id"],
            "market_id": r["market_id"],
            "market_question": r["question"],
            "category": r["category"],
            "side": r["side"],
            "size": round(r["size"], 4),
            "entry_price": round(r["entry_price"], 4),
            "current_price": round(current_price, 4),
            "unrealized_pnl": round(unrealized, 2),
            "return_pct": round(unrealized / (r["entry_price"] * r["size"]) * 100, 1) if r["entry_price"] * r["size"] > 0 else 0.0,
            "agent_estimate": round(r["final_estimate"], 4) if r["final_estimate"] else None,
            "edge_remaining": round(edge_remaining, 4) if edge_remaining is not None else None,
            "confidence_low": round(r["confidence_low"], 4) if r["confidence_low"] else None,
            "confidence_high": round(r["confidence_high"], 4) if r["confidence_high"] else None,
            "entry_timestamp": r["entry_timestamp"],
            "days_held": days_held,
        })

    return {"positions": positions}


@router.get("/closed")
async def closed_positions(request: Request, limit: int = Query(50, ge=1, le=500)):
    db = request.app.state.db

    async with db.connection() as conn:
        rows = await conn.execute_fetchall(
            """SELECT p.id, p.market_id, p.side, p.size, p.entry_price, p.exit_price,
                      p.entry_timestamp, p.exit_timestamp, p.realized_pnl,
                      m.question, m.category
            FROM positions p
            JOIN markets m ON p.market_id = m.id
            WHERE p.status = 'closed'
            ORDER BY p.exit_timestamp DESC
            LIMIT ?""",
            (limit,),
        )

    return {
        "positions": [
            {
                "id": r["id"],
                "market_id": r["market_id"],
                "market_question": r["question"],
                "category": r["category"],
                "side": r["side"],
                "size": round(r["size"], 4),
                "entry_price": round(r["entry_price"], 4),
                "exit_price": round(r["exit_price"], 4) if r["exit_price"] is not None else None,
                "realized_pnl": round(r["realized_pnl"], 2) if r["realized_pnl"] is not None else 0.0,
                "entry_timestamp": r["entry_timestamp"],
                "exit_timestamp": r["exit_timestamp"],
            }
            for r in rows
        ]
    }


@router.get("/trades")
async def trade_history(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    db = request.app.state.db

    async with db.connection() as conn:
        rows = await conn.execute_fetchall(
            """SELECT t.id, t.market_id, t.position_id, t.side, t.action,
                      t.size, t.price, t.timestamp, t.mode,
                      m.question
            FROM trades t
            JOIN markets m ON t.market_id = m.id
            ORDER BY t.timestamp DESC
            LIMIT ? OFFSET ?""",
            (limit, offset),
        )

    return {
        "trades": [
            {
                "id": r["id"],
                "market_id": r["market_id"],
                "market_question": r["question"],
                "side": r["side"],
                "action": r["action"],
                "size": round(r["size"], 4),
                "price": round(r["price"], 4),
                "cost": round(r["size"] * r["price"], 2),
                "timestamp": r["timestamp"],
                "mode": r["mode"],
            }
            for r in rows
        ]
    }


@router.get("/price-history/{market_id}")
async def price_history(request: Request, market_id: str):
    db = request.app.state.db

    async with db.connection() as conn:
        if not await conn.table_exists("price_snapshots"):
            return {"market_id": market_id, "timestamps": [], "price_yes": [], "price_no": [], "volume": []}

        rows = await conn.execute_fetchall(
            """SELECT timestamp, price_yes, price_no, volume
            FROM price_snapshots
            WHERE market_id = ?
            ORDER BY timestamp ASC""",
            (market_id,),
        )

    return {
        "market_id": market_id,
        "timestamps": [r["timestamp"] for r in rows],
        "price_yes": [r["price_yes"] for r in rows],
        "price_no": [r["price_no"] for r in rows],
        "volume": [r["volume"] for r in rows],
    }
