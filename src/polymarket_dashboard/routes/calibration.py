"""Calibration & accuracy endpoints."""

from fastapi import APIRouter, Request

router = APIRouter()

BUCKETS = [(i / 10, (i + 1) / 10) for i in range(10)]


@router.get("/report")
async def calibration_report(request: Request):
    db = request.app.state.db

    async with db.connection() as conn:
        resolved = await conn.execute_fetchall(
            "SELECT agent_estimate, outcome, market_price, category "
            "FROM predictions WHERE outcome IS NOT NULL"
        )
        total_row = await conn.execute_fetchone("SELECT COUNT(*) as c FROM predictions")
        total = total_row["c"] if total_row else 0

    n = len(resolved)
    if n < 2:
        return {
            "total_predictions": total,
            "resolved_predictions": n,
            "brier_score": None,
            "market_brier_score": None,
            "buckets": [],
            "category_breakdown": [],
        }

    # Brier scores
    agent_brier = sum((r["agent_estimate"] - r["outcome"]) ** 2 for r in resolved) / n
    market_brier = sum((r["market_price"] - r["outcome"]) ** 2 for r in resolved) / n

    # Calibration buckets
    buckets = []
    for low, high in BUCKETS:
        bucket_rows = [
            r for r in resolved
            if low <= r["agent_estimate"] < high
            or (high == 1.0 and r["agent_estimate"] == 1.0)
        ]
        if not bucket_rows:
            continue
        avg_pred = sum(r["agent_estimate"] for r in bucket_rows) / len(bucket_rows)
        actual_rate = sum(r["outcome"] for r in bucket_rows) / len(bucket_rows)
        buckets.append({
            "range": f"{low:.1f}-{high:.1f}",
            "count": len(bucket_rows),
            "avg_predicted": round(avg_pred, 3),
            "actual_rate": round(actual_rate, 3),
            "calibration_error": round(avg_pred - actual_rate, 3),
        })

    # Category breakdown
    categories: dict[str, list] = {}
    for r in resolved:
        cat = r["category"] or "unknown"
        categories.setdefault(cat, []).append(r)

    category_breakdown = []
    for cat, rows in sorted(categories.items()):
        cat_brier = sum((r["agent_estimate"] - r["outcome"]) ** 2 for r in rows) / len(rows)
        cat_market = sum((r["market_price"] - r["outcome"]) ** 2 for r in rows) / len(rows)
        category_breakdown.append({
            "category": cat,
            "count": len(rows),
            "brier_score": round(cat_brier, 4),
            "market_brier": round(cat_market, 4),
        })

    return {
        "total_predictions": total,
        "resolved_predictions": n,
        "brier_score": round(agent_brier, 4),
        "market_brier_score": round(market_brier, 4),
        "buckets": buckets,
        "category_breakdown": category_breakdown,
    }


@router.get("/scatter")
async def calibration_scatter(request: Request):
    db = request.app.state.db

    async with db.connection() as conn:
        rows = await conn.execute_fetchall(
            """SELECT agent_estimate, outcome, market_price, category, market_id,
                      timestamp
            FROM predictions WHERE outcome IS NOT NULL
            ORDER BY timestamp ASC"""
        )

    return {
        "predictions": [
            {
                "agent_estimate": round(r["agent_estimate"], 4),
                "outcome": r["outcome"],
                "market_price": round(r["market_price"], 4),
                "category": r["category"],
                "market_id": r["market_id"],
                "timestamp": r["timestamp"],
            }
            for r in rows
        ]
    }
