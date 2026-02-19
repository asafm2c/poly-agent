"""Portfolio & P&L endpoints."""

from datetime import date

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/summary")
async def portfolio_summary(request: Request):
    db = request.app.state.db
    starting_balance = request.app.state.starting_balance

    async with db.connection() as conn:
        # Portfolio basics
        row = await conn.execute_fetchone(
            "SELECT cash_balance, mode FROM portfolio WHERE id = 1"
        )
        cash = row["cash_balance"] if row else 0.0
        mode = row["mode"] if row else "paper"

        # Kill switch
        ks = await conn.execute_fetchone(
            "SELECT active, reason, activated_at FROM kill_switch WHERE id = 1"
        )

        # Open positions with market prices
        positions = await conn.execute_fetchall("""
            SELECT p.id, p.market_id, p.side, p.size, p.entry_price,
                   m.last_price_yes
            FROM positions p
            JOIN markets m ON p.market_id = m.id
            WHERE p.status = 'open'
        """)

        # Try to get latest snapshot prices for mark-to-market
        market_ids = [p["market_id"] for p in positions]
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

        # Compute mark-to-market
        total_position_value = 0.0
        unrealized = 0.0
        for p in positions:
            current = snapshot_prices.get(p["market_id"]) or p["last_price_yes"] or p["entry_price"]
            if p["side"] == "YES":
                pos_value = p["size"] * current
                unrealized += (current - p["entry_price"]) * p["size"]
            else:
                no_price = 1.0 - current
                pos_value = p["size"] * no_price
                unrealized += (no_price - p["entry_price"]) * p["size"]
            total_position_value += pos_value

        # Realized P&L
        r = await conn.execute_fetchone(
            "SELECT COALESCE(SUM(realized_pnl), 0) as total FROM positions WHERE status = 'closed'"
        )
        realized = r["total"] if r else 0.0

        # Today's P&L
        today_row = await conn.execute_fetchone(
            "SELECT total_pnl FROM daily_pnl WHERE date = ?", (date.today().isoformat(),)
        )
        today_pnl = today_row["total_pnl"] if today_row else 0.0

    total_value = cash + total_position_value
    total_return = ((total_value - starting_balance) / starting_balance * 100) if starting_balance > 0 else 0.0

    return {
        "cash_balance": round(cash, 2),
        "mode": mode,
        "open_positions": len(positions),
        "total_position_value": round(total_position_value, 2),
        "total_portfolio_value": round(total_value, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_return_pct": round(total_return, 2),
        "today_pnl": round(today_pnl, 2),
        "kill_switch_active": bool(ks["active"]) if ks else False,
        "kill_switch_reason": ks["reason"] if ks else None,
    }


@router.get("/equity-curve")
async def equity_curve(request: Request):
    db = request.app.state.db

    async with db.connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT date, portfolio_value, realized_pnl, unrealized_pnl, total_pnl, trade_count "
            "FROM daily_pnl ORDER BY date ASC"
        )

    return {
        "dates": [r["date"] for r in rows],
        "portfolio_value": [r["portfolio_value"] for r in rows],
        "realized_pnl": [r["realized_pnl"] for r in rows],
        "unrealized_pnl": [r["unrealized_pnl"] for r in rows],
        "total_pnl": [r["total_pnl"] for r in rows],
        "trade_count": [r["trade_count"] for r in rows],
    }
