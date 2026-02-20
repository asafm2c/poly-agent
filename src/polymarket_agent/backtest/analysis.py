"""Composable analysis library for backtest data.

All functions accept standard Python arguments and return structured dicts/lists.
Callable from CLI, notebooks, LLM agents, or scripts.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from polymarket_agent.backtest.database import get_backtest_db, REGIMES
from polymarket_agent.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core Functions (Group 3)
# ---------------------------------------------------------------------------


def load_markets(
    category: str | None = None,
    regime: str | None = None,
    volume_min: float | None = None,
    volume_max: float | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """Load markets from the backtest DB with optional filters.

    Returns list of dicts with metadata + price_history (list of {t, p}).
    Only markets with price history (has_history=1) are returned.
    """
    conditions = ["m.has_history = 1"]
    params: list = []

    if category:
        conditions.append("m.category = ?")
        params.append(category)
    if volume_min is not None:
        conditions.append("m.volume >= ?")
        params.append(volume_min)
    if volume_max is not None:
        conditions.append("m.volume <= ?")
        params.append(volume_max)
    if date_start:
        conditions.append("m.end_date >= ?")
        params.append(date_start)
    if date_end:
        conditions.append("m.end_date <= ?")
        params.append(date_end)

    # Regime filter: join with bt_regimes to filter by resolution date
    if regime:
        conditions.append(
            """EXISTS (
                SELECT 1 FROM bt_regimes r
                WHERE r.name = ? AND m.end_date >= r.start_date
                AND (r.end_date IS NULL OR m.end_date < r.end_date)
            )"""
        )
        params.append(regime)

    where_clause = " AND ".join(conditions)

    path = db_path or settings.backtest_db_path
    with get_backtest_db(path) as conn:
        rows = conn.execute(
            f"""SELECT m.id, m.question, m.description, m.category, m.end_date,
                    m.volume, m.liquidity, m.resolution_outcome, m.yes_token,
                    m.no_token, m.event_id
            FROM bt_markets m
            WHERE {where_clause}
            ORDER BY m.volume DESC""",
            params,
        ).fetchall()

        markets = []
        for row in rows:
            market = dict(row)
            # Load price history
            history = conn.execute(
                """SELECT timestamp as t, price as p
                FROM bt_price_history
                WHERE market_id = ?
                ORDER BY timestamp""",
                (row["id"],),
            ).fetchall()
            market["price_history"] = [{"t": h["t"], "p": h["p"]} for h in history]
            markets.append(market)

    return markets


def get_regime(resolution_date: str, db_path: Path | None = None) -> str | None:
    """Given a resolution date string, return the regime name.

    Falls back to in-memory regime list if db_path not available.
    """
    if not resolution_date:
        return None

    # Normalize date to just the date portion
    date_str = resolution_date[:10]

    for name, start_date, end_date in REGIMES:
        if date_str >= start_date and (end_date is None or date_str < end_date):
            return name
    return None


def get_price_at_horizon(
    price_history: list[dict],
    resolution_date: str,
    horizon_days: int,
) -> float | None:
    """Given a market's price history and horizon (days before resolution),
    return the price at that point.

    Uses the closest available price within +/- 1 day of the target.
    Returns None if no price data exists near the target.
    """
    if not price_history or not resolution_date:
        return None

    # Parse resolution date
    try:
        res_dt = datetime.fromisoformat(resolution_date.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            res_dt = datetime.strptime(resolution_date[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    target_dt = res_dt - timedelta(days=horizon_days)
    target_ts = int(target_dt.timestamp())

    # Find closest price within 1 day tolerance
    tolerance = 86400  # 1 day in seconds
    best_price = None
    best_dist = float("inf")

    for candle in price_history:
        dist = abs(candle["t"] - target_ts)
        if dist < best_dist and dist <= tolerance:
            best_dist = dist
            best_price = candle["p"]

    return best_price


def market_baseline_brier(markets: list[dict], horizon: int = 7) -> dict:
    """Compute Brier score using market price at horizon as prediction.

    Returns {brier_score, count, horizon}.
    """
    total_sq_error = 0.0
    count = 0

    for market in markets:
        outcome = _parse_outcome(market.get("resolution_outcome"))
        if outcome is None:
            continue

        price = get_price_at_horizon(
            market["price_history"], market.get("end_date", ""), horizon
        )
        if price is None:
            continue

        total_sq_error += (price - outcome) ** 2
        count += 1

    brier = total_sq_error / count if count > 0 else None
    return {"brier_score": brier, "count": count, "horizon": horizon}


# ---------------------------------------------------------------------------
# Signal Functions (Group 4)
# ---------------------------------------------------------------------------


def efficiency_index(
    markets: list[dict],
    horizons: list[int] | None = None,
) -> dict[int, dict]:
    """Compute mean |price_at_horizon - outcome| per horizon.

    Lower values = more efficient markets.
    Returns {horizon: {efficiency, count}}.
    """
    if horizons is None:
        horizons = [30, 7, 1]

    results = {}
    for h in horizons:
        total_dev = 0.0
        count = 0
        for market in markets:
            outcome = _parse_outcome(market.get("resolution_outcome"))
            if outcome is None:
                continue
            price = get_price_at_horizon(
                market["price_history"], market.get("end_date", ""), h
            )
            if price is None:
                continue
            total_dev += abs(price - outcome)
            count += 1

        results[h] = {
            "efficiency": total_dev / count if count > 0 else None,
            "count": count,
        }

    return results


def category_calibration(markets: list[dict]) -> dict[str, dict]:
    """Compute per-category calibration: avg price vs avg outcome.

    Uses the final price (horizon=0, closest to resolution).
    Returns {category: {avg_price, avg_outcome, bias, count}}.
    """
    by_category: dict[str, dict] = {}

    for market in markets:
        cat = market.get("category") or "unknown"
        outcome = _parse_outcome(market.get("resolution_outcome"))
        if outcome is None:
            continue

        # Use the last available price as "final price"
        history = market.get("price_history", [])
        if not history:
            continue
        final_price = history[-1]["p"]

        if cat not in by_category:
            by_category[cat] = {"total_price": 0.0, "total_outcome": 0.0, "count": 0}

        by_category[cat]["total_price"] += final_price
        by_category[cat]["total_outcome"] += outcome
        by_category[cat]["count"] += 1

    results = {}
    for cat, data in by_category.items():
        n = data["count"]
        avg_price = data["total_price"] / n
        avg_outcome = data["total_outcome"] / n
        results[cat] = {
            "avg_price": round(avg_price, 4),
            "avg_outcome": round(avg_outcome, 4),
            "bias": round(avg_price - avg_outcome, 4),
            "count": n,
        }

    return results


def price_momentum(
    markets: list[dict],
    lookback_days: int = 7,
    horizon: int = 7,
) -> list[dict]:
    """Compute price momentum: change over lookback window at measurement point.

    For each market, measures price change between (horizon + lookback) and horizon
    days before resolution.

    Returns list of {market_id, question, momentum, price_start, price_end, outcome}.
    """
    results = []

    for market in markets:
        outcome = _parse_outcome(market.get("resolution_outcome"))
        if outcome is None:
            continue

        end_date = market.get("end_date", "")
        price_start = get_price_at_horizon(
            market["price_history"], end_date, horizon + lookback_days
        )
        price_end = get_price_at_horizon(
            market["price_history"], end_date, horizon
        )

        if price_start is None or price_end is None:
            continue

        momentum = price_end - price_start

        results.append({
            "market_id": market["id"],
            "question": market.get("question", ""),
            "momentum": round(momentum, 4),
            "price_start": round(price_start, 4),
            "price_end": round(price_end, 4),
            "outcome": outcome,
        })

    return results


def cross_market_arbitrage(markets: list[dict]) -> list[dict]:
    """Detect event-level price inconsistencies.

    Groups markets by event_id, sums final YES prices, flags deviations from 1.0.
    Only considers events with 2+ markets.

    Returns list of {event_id, market_count, price_sum, deviation}.
    """
    by_event: dict[str, list] = {}

    for market in markets:
        event_id = market.get("event_id")
        if not event_id:
            continue

        history = market.get("price_history", [])
        if not history:
            continue

        final_price = history[-1]["p"]
        by_event.setdefault(event_id, []).append(final_price)

    results = []
    for event_id, prices in by_event.items():
        if len(prices) < 2:
            continue

        price_sum = sum(prices)
        deviation = price_sum - 1.0

        results.append({
            "event_id": event_id,
            "market_count": len(prices),
            "price_sum": round(price_sum, 4),
            "deviation": round(deviation, 4),
        })

    # Sort by absolute deviation descending
    results.sort(key=lambda x: abs(x["deviation"]), reverse=True)
    return results


def regime_comparison(analysis_fn, db_path: Path | None = None, **kwargs) -> dict[str, dict]:
    """Run an analysis function across all regimes.

    Returns {regime_name: result} in chronological order.
    """
    results = {}

    for name, start_date, end_date in REGIMES:
        regime_markets = load_markets(
            regime=name,
            db_path=db_path,
            **{k: v for k, v in kwargs.items() if k in ("category", "volume_min", "volume_max")},
        )

        if not regime_markets:
            results[name] = {"count": 0, "result": None}
            continue

        # Call the analysis function with regime-filtered markets
        fn_kwargs = {k: v for k, v in kwargs.items() if k not in ("category", "volume_min", "volume_max")}
        result = analysis_fn(regime_markets, **fn_kwargs)
        results[name] = {"count": len(regime_markets), "result": result}

    return results


# ---------------------------------------------------------------------------
# Simulation Results (Group 4)
# ---------------------------------------------------------------------------


def simulation_summary(run_id: int, db_path: Path | None = None) -> dict:
    """Load simulation run + trials, compute aggregate metrics.

    Returns dict with agent_brier, market_brier, brier_diff, simulated_pnl,
    trade_count, win_rate, total_cost, trial_count, valid_trials.
    """
    import json

    path = db_path or settings.backtest_db_path
    with get_backtest_db(path) as conn:
        run = conn.execute(
            "SELECT * FROM bt_simulation_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if not run:
            return {"error": f"Run {run_id} not found"}

        trials = conn.execute(
            "SELECT * FROM bt_simulation_trials WHERE run_id = ?", (run_id,)
        ).fetchall()

    total_agent_brier = 0.0
    total_market_brier = 0.0
    valid = 0
    trade_count = 0
    wins = 0
    total_pnl = 0.0
    total_cost = 0.0

    for t in trials:
        if t["agent_brier"] is not None:
            total_agent_brier += t["agent_brier"]
            valid += 1
        if t["market_brier"] is not None:
            total_market_brier += t["market_brier"]
        if t["simulated_trade"]:
            trade = json.loads(t["simulated_trade"])
            trade_count += 1
            total_pnl += trade.get("net_pnl", 0)
            if trade.get("net_pnl", 0) > 0:
                wins += 1
        total_cost += t["llm_cost"] or 0

    agent_brier = total_agent_brier / valid if valid > 0 else None
    market_brier = total_market_brier / len(trials) if trials else None

    return {
        "run_id": run_id,
        "started_at": run["started_at"],
        "completed_at": run["completed_at"],
        "trial_count": len(trials),
        "valid_trials": valid,
        "agent_brier": agent_brier,
        "market_brier": market_brier,
        "brier_diff": (agent_brier - market_brier)
        if agent_brier is not None and market_brier is not None
        else None,
        "simulated_pnl": total_pnl,
        "trade_count": trade_count,
        "win_rate": wins / trade_count if trade_count > 0 else None,
        "total_cost": total_cost,
    }


def simulation_by_category(run_id: int, db_path: Path | None = None) -> dict[str, dict]:
    """Group simulation trials by market category.

    Returns {category: {agent_brier, market_brier, brier_diff, trial_count, simulated_pnl}}.
    """
    import json

    path = db_path or settings.backtest_db_path
    with get_backtest_db(path) as conn:
        trials = conn.execute(
            """SELECT t.*, m.category, m.volume
            FROM bt_simulation_trials t
            JOIN bt_markets m ON t.market_id = m.id
            WHERE t.run_id = ?""",
            (run_id,),
        ).fetchall()

    by_cat: dict[str, dict] = {}
    for t in trials:
        cat = t["category"] or "(null)"
        if cat not in by_cat:
            by_cat[cat] = {
                "agent_brier_sum": 0.0, "market_brier_sum": 0.0,
                "valid": 0, "total": 0, "pnl": 0.0,
            }
        bucket = by_cat[cat]
        bucket["total"] += 1
        if t["agent_brier"] is not None:
            bucket["agent_brier_sum"] += t["agent_brier"]
            bucket["valid"] += 1
        if t["market_brier"] is not None:
            bucket["market_brier_sum"] += t["market_brier"]
        if t["simulated_trade"]:
            trade = json.loads(t["simulated_trade"])
            bucket["pnl"] += trade.get("net_pnl", 0)

    results = {}
    for cat, b in by_cat.items():
        ab = b["agent_brier_sum"] / b["valid"] if b["valid"] > 0 else None
        mb = b["market_brier_sum"] / b["total"] if b["total"] > 0 else None
        results[cat] = {
            "agent_brier": ab,
            "market_brier": mb,
            "brier_diff": (ab - mb) if ab is not None and mb is not None else None,
            "trial_count": b["total"],
            "simulated_pnl": b["pnl"],
        }

    return results


def simulation_by_volume_tier(run_id: int, db_path: Path | None = None) -> dict[str, dict]:
    """Group simulation trials by volume tier.

    Returns {tier: {agent_brier, market_brier, brier_diff, trial_count, simulated_pnl}}.
    """
    import json

    path = db_path or settings.backtest_db_path
    with get_backtest_db(path) as conn:
        trials = conn.execute(
            """SELECT t.*, m.volume
            FROM bt_simulation_trials t
            JOIN bt_markets m ON t.market_id = m.id
            WHERE t.run_id = ?""",
            (run_id,),
        ).fetchall()

    def _tier(vol):
        if vol >= 10_000_000:
            return ">10M"
        elif vol >= 1_000_000:
            return "1M-10M"
        elif vol >= 100_000:
            return "100K-1M"
        return "10K-100K"

    by_tier: dict[str, dict] = {}
    for t in trials:
        tier = _tier(t["volume"] or 0)
        if tier not in by_tier:
            by_tier[tier] = {
                "agent_brier_sum": 0.0, "market_brier_sum": 0.0,
                "valid": 0, "total": 0, "pnl": 0.0,
            }
        bucket = by_tier[tier]
        bucket["total"] += 1
        if t["agent_brier"] is not None:
            bucket["agent_brier_sum"] += t["agent_brier"]
            bucket["valid"] += 1
        if t["market_brier"] is not None:
            bucket["market_brier_sum"] += t["market_brier"]
        if t["simulated_trade"]:
            trade = json.loads(t["simulated_trade"])
            bucket["pnl"] += trade.get("net_pnl", 0)

    results = {}
    for tier, b in by_tier.items():
        ab = b["agent_brier_sum"] / b["valid"] if b["valid"] > 0 else None
        mb = b["market_brier_sum"] / b["total"] if b["total"] > 0 else None
        results[tier] = {
            "agent_brier": ab,
            "market_brier": mb,
            "brier_diff": (ab - mb) if ab is not None and mb is not None else None,
            "trial_count": b["total"],
            "simulated_pnl": b["pnl"],
        }

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_outcome(resolution_outcome: str | None) -> float | None:
    """Parse resolution outcome to numeric (1.0 for YES, 0.0 for NO).

    Returns None if outcome can't be determined.
    """
    if not resolution_outcome:
        return None

    outcome_upper = str(resolution_outcome).strip().upper()
    if outcome_upper in ("YES", "1", "1.0", "TRUE"):
        return 1.0
    elif outcome_upper in ("NO", "0", "0.0", "FALSE"):
        return 0.0
    return None
