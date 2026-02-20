"""Evaluation API: simulation results from backtest.db."""

import json

from fastapi import APIRouter, Request

router = APIRouter()


def _get_bt_db(request: Request):
    return request.app.state.backtest_db


def _volume_tier(vol: float) -> str:
    if vol >= 10_000_000:
        return ">10M"
    elif vol >= 1_000_000:
        return "1M-10M"
    elif vol >= 100_000:
        return "100K-1M"
    return "10K-100K"


@router.get("/runs")
async def evaluation_runs(request: Request):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "runs": []}

    async with bt_db.connection() as conn:
        rows = await conn.execute_fetchall(
            """SELECT r.id, r.started_at, r.completed_at, r.config,
                      r.market_count, r.agent_brier, r.market_brier,
                      r.simulated_pnl, r.total_cost,
                      COUNT(t.id) as trial_count,
                      SUM(CASE WHEN t.agent_brier IS NOT NULL THEN 1 ELSE 0 END) as valid_trials,
                      SUM(CASE WHEN t.simulated_trade IS NOT NULL THEN 1 ELSE 0 END) as trade_count
            FROM bt_simulation_runs r
            LEFT JOIN bt_simulation_trials t ON t.run_id = r.id
            GROUP BY r.id
            ORDER BY r.id DESC"""
        )

    runs = []
    for r in rows:
        model = None
        if r["config"]:
            try:
                cfg = json.loads(r["config"])
                model = cfg.get("model")
            except (json.JSONDecodeError, TypeError):
                pass

        brier_diff = None
        if r["agent_brier"] is not None and r["market_brier"] is not None:
            brier_diff = round(r["agent_brier"] - r["market_brier"], 4)

        runs.append({
            "id": r["id"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
            "model": model,
            "market_count": r["market_count"],
            "trial_count": r["trial_count"],
            "agent_brier": round(r["agent_brier"], 4) if r["agent_brier"] is not None else None,
            "market_brier": round(r["market_brier"], 4) if r["market_brier"] is not None else None,
            "brier_diff": brier_diff,
            "simulated_pnl": round(r["simulated_pnl"], 2) if r["simulated_pnl"] is not None else None,
            "total_cost": round(r["total_cost"], 4) if r["total_cost"] is not None else None,
            "valid_trials": r["valid_trials"] or 0,
            "trade_count": r["trade_count"] or 0,
        })

    return {"available": True, "runs": runs}


@router.get("/trials/{run_id}")
async def evaluation_trials(
    request: Request,
    run_id: int,
    sort_by: str = "market_id",
    sort_dir: str = "desc",
    category: str | None = None,
    volume_tier: str | None = None,
):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "trials": []}

    allowed_sorts = {"market_id", "agent_brier", "market_brier", "edge", "volume"}
    sort_col = sort_by if sort_by in ("market_id", "agent_brier", "market_brier", "edge") else "t.market_id"
    if sort_by == "volume":
        sort_col = "m.volume"
    direction = "ASC" if sort_dir.lower() == "asc" else "DESC"

    async with bt_db.connection() as conn:
        rows = await conn.execute_fetchall(
            f"""SELECT t.*, m.question, m.category, m.volume
            FROM bt_simulation_trials t
            JOIN bt_markets m ON t.market_id = m.id
            WHERE t.run_id = ?
            ORDER BY {sort_col} {direction}""",
            (run_id,),
        )

    trials = []
    for r in rows:
        vol = r["volume"] or 0
        tier = _volume_tier(vol)

        if category and (r["category"] or "(null)") != category:
            continue
        if volume_tier and tier != volume_tier:
            continue

        brier_diff = None
        if r["agent_brier"] is not None and r["market_brier"] is not None:
            brier_diff = round(r["agent_brier"] - r["market_brier"], 4)

        trade = None
        if r["simulated_trade"]:
            try:
                trade = json.loads(r["simulated_trade"])
            except (json.JSONDecodeError, TypeError):
                pass

        trials.append({
            "market_id": r["market_id"],
            "question": r["question"],
            "category": r["category"] or "(null)",
            "volume": vol,
            "volume_tier": tier,
            "agent_estimate": round(r["agent_estimate"], 4) if r["agent_estimate"] is not None else None,
            "market_price": round(r["market_price_at_horizon"], 4) if r["market_price_at_horizon"] is not None else None,
            "outcome": r["outcome"],
            "agent_brier": round(r["agent_brier"], 4) if r["agent_brier"] is not None else None,
            "market_brier": round(r["market_brier"], 4) if r["market_brier"] is not None else None,
            "brier_diff": brier_diff,
            "edge": round(r["edge"], 4) if r["edge"] is not None else None,
            "trade": trade,
            "model": r["model"] if "model" in r.keys() else None,
            "llm_cost": round(r["llm_cost"], 4) if r["llm_cost"] else None,
        })

    return {"available": True, "trials": trials}


@router.get("/by-category/{run_id}")
async def evaluation_by_category(request: Request, run_id: int):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "categories": []}

    async with bt_db.connection() as conn:
        rows = await conn.execute_fetchall(
            """SELECT COALESCE(m.category, '(null)') as cat,
                      COUNT(*) as trial_count,
                      AVG(t.agent_brier) as agent_brier,
                      AVG(t.market_brier) as market_brier
            FROM bt_simulation_trials t
            JOIN bt_markets m ON t.market_id = m.id
            WHERE t.run_id = ? AND t.agent_brier IS NOT NULL
            GROUP BY cat
            ORDER BY trial_count DESC""",
            (run_id,),
        )

    categories = []
    for r in rows:
        ab = r["agent_brier"]
        mb = r["market_brier"]
        categories.append({
            "category": r["cat"],
            "trial_count": r["trial_count"],
            "agent_brier": round(ab, 4) if ab else None,
            "market_brier": round(mb, 4) if mb else None,
            "brier_diff": round(ab - mb, 4) if ab is not None and mb is not None else None,
        })

    return {"available": True, "categories": categories}


@router.get("/by-volume-tier/{run_id}")
async def evaluation_by_volume_tier(request: Request, run_id: int):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "tiers": []}

    async with bt_db.connection() as conn:
        rows = await conn.execute_fetchall(
            """SELECT
                CASE
                    WHEN m.volume >= 10000000 THEN '>10M'
                    WHEN m.volume >= 1000000 THEN '1M-10M'
                    WHEN m.volume >= 100000 THEN '100K-1M'
                    ELSE '10K-100K'
                END as tier,
                COUNT(*) as trial_count,
                AVG(t.agent_brier) as agent_brier,
                AVG(t.market_brier) as market_brier
            FROM bt_simulation_trials t
            JOIN bt_markets m ON t.market_id = m.id
            WHERE t.run_id = ? AND t.agent_brier IS NOT NULL
            GROUP BY tier
            ORDER BY m.volume DESC""",
            (run_id,),
        )

    tiers = []
    for r in rows:
        ab = r["agent_brier"]
        mb = r["market_brier"]
        tiers.append({
            "tier": r["tier"],
            "trial_count": r["trial_count"],
            "agent_brier": round(ab, 4) if ab else None,
            "market_brier": round(mb, 4) if mb else None,
            "brier_diff": round(ab - mb, 4) if ab is not None and mb is not None else None,
        })

    return {"available": True, "tiers": tiers}


@router.get("/temporal/{run_id}")
async def evaluation_temporal(request: Request, run_id: int):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "trials": [], "regimes": []}

    async with bt_db.connection() as conn:
        trials = await conn.execute_fetchall(
            """SELECT t.agent_brier, t.market_brier, m.end_date, m.question,
                      t.training_recency_score
            FROM bt_simulation_trials t
            JOIN bt_markets m ON t.market_id = m.id
            WHERE t.run_id = ? AND t.agent_brier IS NOT NULL
            ORDER BY m.end_date ASC""",
            (run_id,),
        )

        regimes = []
        if await conn.table_exists("bt_regimes"):
            regimes = await conn.execute_fetchall(
                "SELECT name, start_date, end_date FROM bt_regimes ORDER BY start_date"
            )

    # Compute rolling Brier diff (10-trial window)
    data = []
    window = []
    for r in trials:
        diff = r["agent_brier"] - r["market_brier"]
        window.append(diff)
        if len(window) > 10:
            window.pop(0)
        rolling_avg = sum(window) / len(window)

        data.append({
            "end_date": r["end_date"],
            "question": r["question"][:60] if r["question"] else "",
            "brier_diff": round(diff, 4),
            "rolling_brier_diff": round(rolling_avg, 4),
            "training_recency": round(r["training_recency_score"], 2) if r["training_recency_score"] is not None else None,
        })

    regime_data = [
        {"name": r["name"], "start_date": r["start_date"], "end_date": r["end_date"]}
        for r in regimes
    ]

    return {"available": True, "trials": data, "regimes": regime_data}


@router.get("/compare")
async def evaluation_compare(
    request: Request,
    category: str | None = None,
    volume_tier: str | None = None,
):
    bt_db = _get_bt_db(request)
    if bt_db is None:
        return {"available": False, "runs": []}

    # Build filter conditions for per-trial aggregation
    trial_conditions = ["t.agent_brier IS NOT NULL"]
    trial_params: list = []
    if category:
        if category == "(null)":
            trial_conditions.append("m.category IS NULL")
        else:
            trial_conditions.append("m.category = ?")
            trial_params.append(category)
    if volume_tier:
        tier_ranges = {">10M": (10000000, None), "1M-10M": (1000000, 10000000),
                       "100K-1M": (100000, 1000000), "10K-100K": (10000, 100000)}
        if volume_tier in tier_ranges:
            vmin, vmax = tier_ranges[volume_tier]
            trial_conditions.append("m.volume >= ?")
            trial_params.append(vmin)
            if vmax is not None:
                trial_conditions.append("m.volume < ?")
                trial_params.append(vmax)

    trial_where = " AND ".join(trial_conditions)

    async with bt_db.connection() as conn:
        runs = await conn.execute_fetchall(
            f"""SELECT r.id, r.config, r.total_cost, r.started_at,
                      COUNT(t.id) as trial_count,
                      AVG(t.agent_brier) as agent_brier,
                      AVG(t.market_brier) as market_brier
            FROM bt_simulation_runs r
            LEFT JOIN bt_simulation_trials t ON t.run_id = r.id
            LEFT JOIN bt_markets m ON t.market_id = m.id
            WHERE r.completed_at IS NOT NULL AND {trial_where}
            GROUP BY r.id
            ORDER BY r.id DESC
            LIMIT 20""",
            trial_params,
        )

    result = []
    for r in runs:
        if r["trial_count"] == 0:
            continue
        model = None
        if r["config"]:
            try:
                cfg = json.loads(r["config"])
                model = cfg.get("model")
            except (json.JSONDecodeError, TypeError):
                pass

        ab = r["agent_brier"]
        mb = r["market_brier"]
        brier_diff = round(ab - mb, 4) if ab is not None and mb is not None else None

        result.append({
            "id": r["id"],
            "model": model,
            "agent_brier": round(ab, 4) if ab is not None else None,
            "market_brier": round(mb, 4) if mb is not None else None,
            "brier_diff": brier_diff,
            "trial_count": r["trial_count"],
            "total_cost": round(r["total_cost"], 4) if r["total_cost"] else None,
            "started_at": r["started_at"],
        })

    return {"available": True, "runs": result}
