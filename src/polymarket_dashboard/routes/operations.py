"""Operations & agent status endpoints."""

from fastapi import APIRouter, Query, Request

router = APIRouter()


@router.get("/status")
async def operations_status(request: Request):
    db = request.app.state.db

    async with db.connection() as conn:
        active = await conn.execute_fetchone(
            "SELECT COUNT(*) as c FROM markets WHERE active = 1"
        )
        total = await conn.execute_fetchone("SELECT COUNT(*) as c FROM markets")
        cats = await conn.execute_fetchone(
            "SELECT COUNT(DISTINCT category) as c FROM markets WHERE active = 1"
        )
        ks = await conn.execute_fetchone(
            "SELECT active, reason, activated_at FROM kill_switch WHERE id = 1"
        )
        pending = await conn.execute_fetchone(
            "SELECT COUNT(*) as c FROM predictions WHERE outcome IS NULL"
        )
        open_orders = await conn.execute_fetchone(
            "SELECT COUNT(*) as c FROM orders WHERE status = 'open'"
        )
        recent_days = await conn.execute_fetchall(
            "SELECT date, trade_count, total_pnl, portfolio_value "
            "FROM daily_pnl ORDER BY date DESC LIMIT 30"
        )

    return {
        "active_markets": active["c"] if active else 0,
        "total_markets": total["c"] if total else 0,
        "categories_tracked": cats["c"] if cats else 0,
        "kill_switch": {
            "active": bool(ks["active"]) if ks else False,
            "reason": ks["reason"] if ks else None,
            "activated_at": ks["activated_at"] if ks else None,
        },
        "pending_predictions": pending["c"] if pending else 0,
        "open_orders": open_orders["c"] if open_orders else 0,
        "recent_activity": [
            {
                "date": r["date"],
                "trades": r["trade_count"],
                "pnl": round(r["total_pnl"], 2),
                "portfolio_value": round(r["portfolio_value"], 2),
            }
            for r in recent_days
        ],
    }


@router.get("/predictions")
async def recent_predictions(
    request: Request, limit: int = Query(20, ge=1, le=200)
):
    db = request.app.state.db

    async with db.connection() as conn:
        # Detect available columns (edge_at_prediction/threshold_at_prediction may not exist yet)
        cursor = await conn.execute("PRAGMA table_info(predictions)")
        cols = {row[1] for row in await cursor.fetchall()}
        has_edge = "edge_at_prediction" in cols

        edge_cols = ", p.edge_at_prediction, p.threshold_at_prediction" if has_edge else ""
        rows = await conn.execute_fetchall(
            f"""SELECT p.timestamp, p.market_id, p.agent_estimate, p.market_price,
                      p.final_estimate, p.confidence_low, p.confidence_high,
                      p.thesis, p.outcome{edge_cols},
                      m.question, m.category
            FROM predictions p
            JOIN markets m ON p.market_id = m.id
            ORDER BY p.timestamp DESC
            LIMIT ?""",
            (limit,),
        )

    def _get(r, key):
        try:
            return r[key]
        except (IndexError, KeyError):
            return None

    return {
        "predictions": [
            {
                "timestamp": r["timestamp"],
                "market_id": r["market_id"],
                "market_question": r["question"],
                "category": r["category"],
                "agent_estimate": round(r["agent_estimate"], 4),
                "final_estimate": round(r["final_estimate"], 4) if r["final_estimate"] else None,
                "market_price": round(r["market_price"], 4),
                "confidence_low": round(r["confidence_low"], 4) if r["confidence_low"] else None,
                "confidence_high": round(r["confidence_high"], 4) if r["confidence_high"] else None,
                "edge": round(_get(r, "edge_at_prediction"), 4) if _get(r, "edge_at_prediction") else None,
                "threshold": round(_get(r, "threshold_at_prediction"), 4) if _get(r, "threshold_at_prediction") else None,
                "thesis": r["thesis"],
                "resolved": r["outcome"] is not None,
                "outcome": r["outcome"],
            }
            for r in rows
        ]
    }
