"""Data API: backtest corpus statistics from backtest.db."""

from fastapi import APIRouter, Request

router = APIRouter()


def _get_bt_db(request: Request):
    return request.app.state.backtest_db


@router.get("/summary")
async def data_summary(request: Request):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_markets"):
            return {"available": False}

        row = await conn.execute_fetchone(
            """SELECT
                COUNT(*) as total,
                SUM(has_history) as with_history,
                MIN(end_date) as date_start,
                MAX(end_date) as date_end,
                COUNT(DISTINCT COALESCE(category, 'unknown')) as category_count,
                MIN(volume) as volume_min,
                MAX(volume) as volume_max
            FROM bt_markets"""
        )

    if not row or not row["total"]:
        return {"available": False}

    total = row["total"] or 0
    with_history = row["with_history"] or 0
    coverage_pct = round(with_history / total * 100, 1) if total > 0 else 0.0

    return {
        "available": True,
        "total_markets": total,
        "with_history": with_history,
        "coverage_pct": coverage_pct,
        "date_range_start": row["date_start"],
        "date_range_end": row["date_end"],
        "category_count": row["category_count"] or 0,
        "volume_min": row["volume_min"],
        "volume_max": row["volume_max"],
    }


@router.get("/by-category")
async def data_by_category(request: Request):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "categories": []}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_markets"):
            return {"available": False, "categories": []}

        rows = await conn.execute_fetchall(
            """SELECT
                COALESCE(category, 'unknown') as category,
                COUNT(*) as total,
                SUM(has_history) as with_history
            FROM bt_markets
            GROUP BY COALESCE(category, 'unknown')
            ORDER BY total DESC"""
        )

    categories = [
        {
            "category": r["category"],
            "total": r["total"],
            "with_history": r["with_history"] or 0,
        }
        for r in rows
    ]

    return {"available": True, "categories": categories}


@router.get("/by-volume-tier")
async def data_by_volume_tier(request: Request):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "tiers": []}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_markets"):
            return {"available": False, "tiers": []}

        rows = await conn.execute_fetchall(
            """SELECT
                CASE
                    WHEN volume >= 10000000 THEN '>$10M'
                    WHEN volume >= 1000000  THEN '$1M-$10M'
                    WHEN volume >= 100000   THEN '$100K-$1M'
                    WHEN volume >= 10000    THEN '$10K-$100K'
                    ELSE '<$10K'
                END as tier,
                COUNT(*) as total,
                SUM(has_history) as with_history
            FROM bt_markets
            GROUP BY tier"""
        )

    # Enforce logical order
    tier_order = ['<$10K', '$10K-$100K', '$100K-$1M', '$1M-$10M', '>$10M']
    tier_map = {r["tier"]: r for r in rows}
    tiers = []
    for t in tier_order:
        if t in tier_map:
            r = tier_map[t]
            tiers.append({
                "tier": r["tier"],
                "total": r["total"],
                "with_history": r["with_history"] or 0,
            })

    return {"available": True, "tiers": tiers}


@router.get("/temporal")
async def data_temporal(request: Request):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "months": [], "regimes": []}

    async with bt_db.connection() as conn:
        if not await conn.table_exists("bt_markets"):
            return {"available": False, "months": [], "regimes": []}

        rows = await conn.execute_fetchall(
            """SELECT
                strftime('%Y-%m', end_date) as month,
                COUNT(*) as total,
                SUM(has_history) as with_history
            FROM bt_markets
            WHERE end_date IS NOT NULL
            GROUP BY month
            ORDER BY month ASC"""
        )

        regimes = []
        if await conn.table_exists("bt_regimes"):
            regime_rows = await conn.execute_fetchall(
                "SELECT name, start_date, end_date FROM bt_regimes ORDER BY start_date"
            )
            regimes = [
                {"name": r["name"], "start_date": r["start_date"], "end_date": r["end_date"]}
                for r in regime_rows
            ]

    months = [
        {
            "month": r["month"],
            "total": r["total"],
            "with_history": r["with_history"] or 0,
        }
        for r in rows
    ]

    return {"available": True, "months": months, "regimes": regimes}
