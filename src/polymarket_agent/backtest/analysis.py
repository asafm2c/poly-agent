"""Composable analysis library for backtest data.

All functions accept standard Python arguments and return structured dicts/lists.
Callable from CLI, notebooks, LLM agents, or scripts.
"""

import json
import logging
import random as _random
from datetime import datetime, timedelta
from pathlib import Path

from polymarket_agent.backtest.database import get_backtest_db, REGIMES
from polymarket_agent.config import settings

logger = logging.getLogger(__name__)

# Model training cutoff dates (best-guess knowledge cutoffs)
MODEL_TRAINING_CUTOFFS = {
    "claude-haiku-4-5-20251001": "2025-04-01",
    "claude-sonnet-4-6": "2025-04-01",
    "claude-opus-4-6": "2025-04-01",
}


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


# ---------------------------------------------------------------------------
# Training Recency & Temporal Confidence
# ---------------------------------------------------------------------------


def training_recency_score(resolution_date: str, model: str) -> float:
    """Compute training recency score (0.0 = in training window, 1.0 = clean).

    Linear interpolation from 0.0 to 1.0 over 180 days past the model's
    training cutoff date. Returns 1.0 for unknown models.
    """
    cutoff_str = MODEL_TRAINING_CUTOFFS.get(model)
    if cutoff_str is None:
        return 1.0

    try:
        # Parse dates (handle various formats)
        res_str = resolution_date[:10]
        cutoff_dt = datetime.strptime(cutoff_str, "%Y-%m-%d")
        res_dt = datetime.strptime(res_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return 1.0

    days_after = (res_dt - cutoff_dt).days

    if days_after <= 0:
        return 0.0
    elif days_after >= 180:
        return 1.0
    else:
        return days_after / 180.0


def weighted_brier(
    trials: list[dict],
    weight_key: str = "training_recency_score",
) -> dict:
    """Compute weighted mean Brier score using per-trial weights.

    Returns {"agent_brier_weighted", "market_brier_weighted",
             "brier_diff_weighted", "total_weight", "trial_count"}.
    """
    total_w_agent = 0.0
    total_w_market = 0.0
    total_weight = 0.0
    count = 0

    for t in trials:
        ab = t.get("agent_brier") if isinstance(t, dict) else t["agent_brier"]
        mb = t.get("market_brier") if isinstance(t, dict) else t["market_brier"]
        if ab is None or mb is None:
            continue

        w = t.get(weight_key) if isinstance(t, dict) else t[weight_key]
        if w is None:
            w = 1.0

        total_w_agent += ab * w
        total_w_market += mb * w
        total_weight += w
        count += 1

    if total_weight == 0:
        return {
            "agent_brier_weighted": None,
            "market_brier_weighted": None,
            "brier_diff_weighted": None,
            "total_weight": 0.0,
            "trial_count": 0,
        }

    awb = total_w_agent / total_weight
    mwb = total_w_market / total_weight
    return {
        "agent_brier_weighted": awb,
        "market_brier_weighted": mwb,
        "brier_diff_weighted": awb - mwb,
        "total_weight": total_weight,
        "trial_count": count,
    }


# ---------------------------------------------------------------------------
# Statistical Comparison (Bootstrap)
# ---------------------------------------------------------------------------


def brier_confidence_interval(
    agent_briers: list[float],
    market_briers: list[float],
    weights: list[float] | None = None,
    n_bootstrap: int = 10_000,
    confidence: float = 0.95,
    seed: int | None = None,
) -> dict:
    """Bootstrap confidence interval on Brier score difference.

    Computes paired differences (agent - market), bootstraps weighted mean.
    Returns {"mean_diff", "ci_low", "ci_high", "p_value", "n", "significant"}.
    """
    n = len(agent_briers)
    if n == 0:
        return {"mean_diff": 0.0, "ci_low": 0.0, "ci_high": 0.0,
                "p_value": 1.0, "n": 0, "significant": False}

    diffs = [a - m for a, m in zip(agent_briers, market_briers)]
    ws = weights or [1.0] * n

    def _weighted_mean(vals, wts):
        tw = sum(wts)
        if tw == 0:
            return 0.0
        return sum(v * w for v, w in zip(vals, wts)) / tw

    observed_mean = _weighted_mean(diffs, ws)

    rng = _random.Random(seed)
    bootstrap_means = []
    indices = list(range(n))
    for _ in range(n_bootstrap):
        sample_idx = rng.choices(indices, k=n)
        sample_diffs = [diffs[i] for i in sample_idx]
        sample_weights = [ws[i] for i in sample_idx]
        bootstrap_means.append(_weighted_mean(sample_diffs, sample_weights))

    bootstrap_means.sort()
    alpha = 1 - confidence
    ci_low = bootstrap_means[int(alpha / 2 * n_bootstrap)]
    ci_high = bootstrap_means[int((1 - alpha / 2) * n_bootstrap)]

    # Two-sided p-value
    if observed_mean < 0:
        p_value = sum(1 for b in bootstrap_means if b >= 0) / n_bootstrap
    else:
        p_value = sum(1 for b in bootstrap_means if b <= 0) / n_bootstrap

    significant = p_value < alpha

    return {
        "mean_diff": observed_mean,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "p_value": p_value,
        "n": n,
        "significant": significant,
    }


# ---------------------------------------------------------------------------
# Cross-Model Comparison
# ---------------------------------------------------------------------------


def _volume_tier(vol: float) -> str:
    """Classify volume into tier."""
    if vol >= 10_000_000:
        return ">10M"
    elif vol >= 1_000_000:
        return "1M-10M"
    elif vol >= 100_000:
        return "100K-1M"
    return "10K-100K"


def cross_model_comparison(
    run_ids: list[int],
    db_path: Path | None = None,
) -> dict:
    """Compare Brier scores across simulation runs (typically different models).

    Returns {"models": {model: summary}, "pairwise": {...},
             "by_category": {...}, "by_volume_tier": {...}, "by_cell": {...}}.
    """
    path = db_path or settings.backtest_db_path

    # Load all trials with market metadata
    runs_data = {}
    with get_backtest_db(path) as conn:
        for run_id in run_ids:
            run_row = conn.execute(
                "SELECT * FROM bt_simulation_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if not run_row:
                continue

            trials = conn.execute(
                """SELECT t.*, m.category, m.volume
                FROM bt_simulation_trials t
                JOIN bt_markets m ON t.market_id = m.id
                WHERE t.run_id = ?""",
                (run_id,),
            ).fetchall()

            model = None
            if run_row["config"]:
                try:
                    cfg = json.loads(run_row["config"])
                    model = cfg.get("model")
                except (json.JSONDecodeError, TypeError):
                    pass

            # Check trial-level model
            if model is None and trials:
                model = trials[0]["model"]

            model = model or f"run_{run_id}"
            runs_data[model] = {
                "run_id": run_id,
                "trials": [dict(t) for t in trials],
            }

    if not runs_data:
        return {}

    # Per-model aggregates
    models_summary = {}
    for model, data in runs_data.items():
        trials = data["trials"]
        valid = [t for t in trials if t.get("agent_brier") is not None]
        if not valid:
            continue

        ab_list = [t["agent_brier"] for t in valid]
        mb_list = [t["market_brier"] for t in valid if t.get("market_brier") is not None]

        avg_ab = sum(ab_list) / len(ab_list) if ab_list else None
        avg_mb = sum(mb_list) / len(mb_list) if mb_list else None

        wb = weighted_brier(valid)

        models_summary[model] = {
            "run_id": data["run_id"],
            "agent_brier": avg_ab,
            "market_brier": avg_mb,
            "brier_diff": (avg_ab - avg_mb) if avg_ab is not None and avg_mb is not None else None,
            "weighted": wb,
            "trial_count": len(valid),
        }

    # Pairwise comparisons (paired by market_id)
    model_names = list(runs_data.keys())
    pairwise = {}
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            ma, mb_name = model_names[i], model_names[j]
            trials_a = {t["market_id"]: t for t in runs_data[ma]["trials"] if t.get("agent_brier") is not None}
            trials_b = {t["market_id"]: t for t in runs_data[mb_name]["trials"] if t.get("agent_brier") is not None}

            shared_ids = set(trials_a.keys()) & set(trials_b.keys())
            if len(shared_ids) < 5:
                continue

            a_briers = [trials_a[mid]["agent_brier"] for mid in shared_ids]
            b_briers = [trials_b[mid]["agent_brier"] for mid in shared_ids]

            ci = brier_confidence_interval(a_briers, b_briers)
            pairwise[f"{ma} vs {mb_name}"] = ci

    # Per-category breakdown
    by_category = {}
    for model, data in runs_data.items():
        for t in data["trials"]:
            if t.get("agent_brier") is None:
                continue
            cat = t.get("category") or "(null)"
            if cat not in by_category:
                by_category[cat] = {}
            if model not in by_category[cat]:
                by_category[cat][model] = {"ab_sum": 0.0, "mb_sum": 0.0, "n": 0}
            by_category[cat][model]["ab_sum"] += t["agent_brier"]
            by_category[cat][model]["mb_sum"] += t.get("market_brier", 0)
            by_category[cat][model]["n"] += 1

    by_category_result = {}
    for cat, models_in_cat in by_category.items():
        by_category_result[cat] = {}
        for model, agg in models_in_cat.items():
            n = agg["n"]
            by_category_result[cat][model] = {
                "agent_brier": agg["ab_sum"] / n,
                "market_brier": agg["mb_sum"] / n,
                "brier_diff": (agg["ab_sum"] - agg["mb_sum"]) / n,
                "n": n,
                "sufficient": n >= 20,
            }

    # Per-volume-tier breakdown
    by_tier = {}
    for model, data in runs_data.items():
        for t in data["trials"]:
            if t.get("agent_brier") is None:
                continue
            tier = _volume_tier(t.get("volume", 0) or 0)
            if tier not in by_tier:
                by_tier[tier] = {}
            if model not in by_tier[tier]:
                by_tier[tier][model] = {"ab_sum": 0.0, "mb_sum": 0.0, "n": 0}
            by_tier[tier][model]["ab_sum"] += t["agent_brier"]
            by_tier[tier][model]["mb_sum"] += t.get("market_brier", 0)
            by_tier[tier][model]["n"] += 1

    by_tier_result = {}
    for tier, models_in_tier in by_tier.items():
        by_tier_result[tier] = {}
        for model, agg in models_in_tier.items():
            n = agg["n"]
            by_tier_result[tier][model] = {
                "agent_brier": agg["ab_sum"] / n,
                "market_brier": agg["mb_sum"] / n,
                "brier_diff": (agg["ab_sum"] - agg["mb_sum"]) / n,
                "n": n,
                "sufficient": n >= 20,
            }

    return {
        "models": models_summary,
        "pairwise": pairwise,
        "by_category": by_category_result,
        "by_volume_tier": by_tier_result,
    }
