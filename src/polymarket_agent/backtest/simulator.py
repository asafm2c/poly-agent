"""Simulation harness: run estimation pipeline against historical markets."""

import asyncio
import json
import logging
import math
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
from polymarket_agent.config import settings
from polymarket_agent.models import Market, ResearchDossier

logger = logging.getLogger(__name__)

# Default simulation parameters
DEFAULT_HORIZON = 7
DEFAULT_COUNT = 50
DEFAULT_MIN_VOLUME = 100_000
DEFAULT_BANKROLL = 1000.0
DEFAULT_FEE_RATE = 0.02  # 2% round-trip
DEFAULT_EDGE_THRESHOLD = 0.10

# Multi-model evaluation constants
VOLUME_TIERS = {
    ">10M": (10_000_000, None),
    "1M-10M": (1_000_000, 10_000_000),
    "100K-1M": (100_000, 1_000_000),
    "10K-100K": (10_000, 100_000),
}

EVALUATION_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
]

MODEL_COST_PER_TRIAL = {
    "claude-haiku-4-5-20251001": 0.005,
    "claude-sonnet-4-6": 0.023,
    "claude-opus-4-6": 0.12,
}


# ---------------------------------------------------------------------------
# Historical Research Gatherer (replaces live ResearchGatherer)
# ---------------------------------------------------------------------------


class HistoricalResearchGatherer:
    """Builds research dossiers from backtest DB data only.

    Drop-in replacement for ResearchGatherer — implements gather() and
    format_dossier_for_llm() with the same signatures.
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or settings.backtest_db_path

    def gather(self, market: Market, token_id: str | None = None) -> ResearchDossier:
        """Build a dossier from historical data only."""
        return ResearchDossier(
            market_id=market.id,
            market_question=market.question,
            market_description=market.description,
            market_category=market.category,
            market_end_date=market.end_date,
            current_price_yes=market.last_price_yes,
            current_price_no=1.0 - market.last_price_yes if market.last_price_yes else None,
            web_search_results=[],
            polymarket_comments=[],
            comment_sentiment_summary=None,
            related_markets=[],
            domain_data=None,
            price_history=market._price_history_for_dossier
            if hasattr(market, "_price_history_for_dossier")
            else [],
            order_book_signals=None,
            cached=False,
        )

    def format_dossier_for_llm(self, dossier: ResearchDossier) -> str:
        """Format historical dossier as text for LLM consumption."""
        parts = [
            f"# Market Research: {dossier.market_question}",
            "",
        ]

        if dossier.market_description:
            parts.append(f"**Description:** {dossier.market_description}")
            parts.append("")

        if dossier.market_category:
            parts.append(f"**Category:** {dossier.market_category}")

        if dossier.market_end_date:
            parts.append(f"**Resolution date:** {dossier.market_end_date.strftime('%Y-%m-%d')}")

        if dossier.current_price_yes is not None:
            parts.append(f"**Current market price:** YES={dossier.current_price_yes:.2f}")
        parts.append("")

        # Price history summary
        if dossier.price_history:
            parts.append("## Price History")
            summary = _summarize_historical_prices(dossier.price_history)
            for line in summary:
                parts.append(line)
            parts.append("")

        parts.append("## Research Context")
        parts.append(
            "Note: Web search results and order book data are not available for "
            "this analysis. Base your estimate on the market question, description, "
            "category context, price history, and your general knowledge."
        )
        parts.append("")

        return "\n".join(parts)


def _summarize_historical_prices(history: list[dict]) -> list[str]:
    """Summarize price history into human-readable lines."""
    if not history:
        return ["- No price data available"]

    prices = []
    for point in history:
        try:
            p = float(point.get("p", point.get("price", 0)))
            if p > 0:
                prices.append(p)
        except (ValueError, TypeError):
            continue

    if not prices:
        return ["- No valid price data"]

    open_price = prices[0]
    current_price = prices[-1]
    high = max(prices)
    low = min(prices)

    lines = [
        f"- Open: {open_price:.3f}, Current: {current_price:.3f}",
        f"- High: {high:.3f}, Low: {low:.3f}",
    ]

    # 7-day change (last 7 points if daily data)
    if len(prices) >= 7:
        change_7d = current_price - prices[-7]
        lines.append(f"- 7-day change: {change_7d:+.3f}")

    # 30-day change
    if len(prices) >= 30:
        change_30d = current_price - prices[-30]
        lines.append(f"- 30-day change: {change_30d:+.3f}")

    # Trend direction
    change = current_price - open_price
    if change > 0.01:
        trend = "upward"
    elif change < -0.01:
        trend = "downward"
    else:
        trend = "flat"
    pct = (change / open_price * 100) if open_price > 0 else 0
    lines.append(f"- Overall trend: {trend} ({change:+.3f}, {pct:+.1f}%)")

    return lines


# ---------------------------------------------------------------------------
# Market Selection
# ---------------------------------------------------------------------------


def select_markets(
    count: int = DEFAULT_COUNT,
    category: str | None = None,
    volume_min: float | None = DEFAULT_MIN_VOLUME,
    volume_max: float | None = None,
    regime: str | None = None,
    horizon: int = DEFAULT_HORIZON,
    db_path: Path | None = None,
) -> list[dict]:
    """Select historical markets for simulation.

    Returns list of market dicts with metadata and price_history.
    Only markets with has_history=1 and a YES/NO outcome are eligible.
    """
    conditions = [
        "m.has_history = 1",
        "m.resolution_outcome IN ('YES', 'NO')",
        # Ensure price history spans at least `horizon` days before resolution
        """EXISTS (
            SELECT 1 FROM bt_price_history p
            WHERE p.market_id = m.id
            AND p.timestamp <= CAST(strftime('%%s', m.end_date, '-%d days') AS INTEGER)
        )""" % horizon,
    ]
    params: list = []

    if category == "*":
        pass  # No category filter — include all categories
    elif category is not None:
        conditions.append("m.category = ?")
        params.append(category)
    else:
        # Default: null-category (prediction markets, not sports)
        conditions.append("m.category IS NULL")

    if volume_min is not None:
        conditions.append("m.volume >= ?")
        params.append(volume_min)
    if volume_max is not None:
        conditions.append("m.volume <= ?")
        params.append(volume_max)

    if regime:
        conditions.append(
            """EXISTS (
                SELECT 1 FROM bt_regimes r
                WHERE r.name = ? AND m.end_date >= r.start_date
                AND (r.end_date IS NULL OR m.end_date < r.end_date)
            )"""
        )
        params.append(regime)

    where = " AND ".join(conditions)
    path = db_path or settings.backtest_db_path

    with get_backtest_db(path) as conn:
        # Get eligible market IDs
        rows = conn.execute(
            f"""SELECT m.id, m.question, m.description, m.category, m.end_date,
                    m.volume, m.liquidity, m.resolution_outcome, m.yes_token,
                    m.no_token, m.event_id
            FROM bt_markets m
            WHERE {where}
            ORDER BY m.volume DESC""",
            params,
        ).fetchall()

        if not rows:
            return []

        # Random sample
        selected = random.sample(rows, min(count, len(rows)))

        markets = []
        for row in selected:
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

    logger.info(
        "Selected %d markets from %d eligible (filters: cat=%s, vol=%s-%s, regime=%s)",
        len(markets), len(rows), category, volume_min, volume_max, regime,
    )
    return markets


# ---------------------------------------------------------------------------
# Context Construction
# ---------------------------------------------------------------------------


def build_market_at_horizon(market_dict: dict, horizon: int) -> tuple[Market, list[dict]] | None:
    """Construct a Market object as it would appear at `horizon` days before resolution.

    Returns (Market, truncated_price_history) or None if insufficient data.
    """
    end_date_str = market_dict.get("end_date")
    if not end_date_str:
        return None

    # Parse resolution date
    try:
        res_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            res_dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            return None

    horizon_dt = res_dt - timedelta(days=horizon)
    horizon_ts = int(horizon_dt.timestamp())

    # Truncate price history to horizon
    full_history = market_dict.get("price_history", [])
    truncated = [h for h in full_history if h["t"] <= horizon_ts]

    if not truncated:
        return None

    # Price at horizon is the last available price before cutoff
    price_at_horizon = truncated[-1]["p"]

    market = Market(
        id=market_dict["id"],
        question=market_dict.get("question", ""),
        description=market_dict.get("description"),
        category=market_dict.get("category"),
        end_date=res_dt,
        outcome_yes_token=market_dict.get("yes_token"),
        outcome_no_token=market_dict.get("no_token"),
        volume=market_dict.get("volume", 0),
        liquidity=market_dict.get("liquidity", 0),
        last_price_yes=price_at_horizon,
        last_price_no=1.0 - price_at_horizon,
        active=True,
        resolved=False,
        resolution_outcome=None,  # Hide outcome from the estimator
        event_id=market_dict.get("event_id"),
    )

    return market, truncated


# ---------------------------------------------------------------------------
# P&L Computation
# ---------------------------------------------------------------------------


def compute_simulated_trade(
    agent_estimate: float,
    market_price: float,
    outcome: float,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    bankroll: float = DEFAULT_BANKROLL,
    fee_rate: float = DEFAULT_FEE_RATE,
) -> dict | None:
    """Compute simulated trade if edge exceeds threshold.

    Returns trade dict with side, size, entry, exit, pnl, fees — or None.
    """
    edge = agent_estimate - market_price  # Positive = think YES is underpriced

    if abs(edge) < edge_threshold:
        return None

    # Determine trade side
    if edge > 0:
        side = "YES"
        entry_price = market_price
        exit_price = outcome  # 1.0 if YES, 0.0 if NO
        p_win = agent_estimate
    else:
        side = "NO"
        entry_price = 1.0 - market_price
        exit_price = 1.0 - outcome  # 1.0 if NO, 0.0 if YES
        p_win = 1.0 - agent_estimate

    # Kelly criterion: f* = (p*b - q) / b where b = (1-entry)/entry for binary
    if entry_price <= 0 or entry_price >= 1:
        return None

    b = (1.0 - entry_price) / entry_price  # Payout odds
    q = 1.0 - p_win
    kelly_fraction = (p_win * b - q) / b if b > 0 else 0

    # Half-Kelly, clamped
    half_kelly = max(0, kelly_fraction * 0.5)
    if half_kelly <= 0:
        return None

    position_size = bankroll * half_kelly
    shares = position_size / entry_price

    # P&L
    gross_pnl = shares * (exit_price - entry_price)
    fees = position_size * fee_rate
    net_pnl = gross_pnl - fees

    return {
        "side": side,
        "shares": round(shares, 2),
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "position_size": round(position_size, 2),
        "gross_pnl": round(gross_pnl, 2),
        "fees": round(fees, 2),
        "net_pnl": round(net_pnl, 2),
        "kelly_fraction": round(half_kelly, 4),
    }


# ---------------------------------------------------------------------------
# Simulation Runner
# ---------------------------------------------------------------------------


def _run_single_trial(
    market_dict: dict,
    run_id: int,
    horizon: int,
    edge_threshold: float,
    bankroll: float,
    fee_rate: float,
    effective_model: str,
    estimator,
    db_path: Path,
    db_lock: threading.Lock,
) -> dict:
    """Execute one simulation trial. Designed to run in a thread pool.

    Returns a result dict with trial metrics. DB insert is serialized via db_lock.
    """
    trial_start = time.time()

    # Build market at horizon
    built = build_market_at_horizon(market_dict, horizon)
    if built is None:
        logger.warning("Skipping %s: no price data at horizon", market_dict["id"][:16])
        return {"skipped": True, "market_id": market_dict["id"]}

    market_obj, truncated_history = built
    market_price = market_obj.last_price_yes
    market_obj._price_history_for_dossier = truncated_history
    outcome = 1.0 if market_dict["resolution_outcome"] == "YES" else 0.0

    # Run estimation (4 serial LLM passes)
    agent_estimate = None
    confidence_low = None
    confidence_high = None
    reasoning = None
    trial_cost = 0.0
    try:
        estimate = estimator.estimate(market_obj, model=effective_model)
        agent_estimate = estimate.final_estimate
        confidence_low = estimate.confidence_low
        confidence_high = estimate.confidence_high
        reasoning = estimate.thesis
        trial_cost = estimate.llm_cost if isinstance(getattr(estimate, "llm_cost", None), (int, float)) else 0.0
    except Exception as e:
        logger.error("Estimation failed for %s: %s", market_dict["id"][:16], e)

    agent_brier = (agent_estimate - outcome) ** 2 if agent_estimate is not None else None
    market_brier = (market_price - outcome) ** 2
    edge = (agent_estimate - market_price) if agent_estimate is not None else None
    trade = None
    if agent_estimate is not None:
        trade = compute_simulated_trade(
            agent_estimate, market_price, outcome,
            edge_threshold=edge_threshold, bankroll=bankroll, fee_rate=fee_rate,
        )

    trial_duration = int((time.time() - trial_start) * 1000)

    # Compute training recency score
    recency_score = None
    if market_dict.get("end_date"):
        from polymarket_agent.backtest.analysis import training_recency_score
        try:
            recency_score = training_recency_score(market_dict["end_date"], effective_model)
        except Exception:
            pass

    # Persist trial (serialized to avoid SQLite write contention)
    with db_lock:
        with get_backtest_db(db_path) as conn:
            conn.execute(
                """INSERT INTO bt_simulation_trials
                (run_id, market_id, horizon_days, market_price_at_horizon,
                 agent_estimate, confidence_low, confidence_high, outcome,
                 agent_brier, market_brier, edge, simulated_trade,
                 reasoning, llm_cost, duration_ms, model, training_recency_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, market_dict["id"], horizon, market_price,
                    agent_estimate, confidence_low, confidence_high, outcome,
                    agent_brier, market_brier, edge,
                    json.dumps(trade) if trade else None,
                    reasoning, trial_cost, trial_duration,
                    effective_model, recency_score,
                ),
            )

    return {
        "skipped": False,
        "market_id": market_dict["id"],
        "agent_brier": agent_brier,
        "market_brier": market_brier,
        "trade": trade,
        "trial_cost": trial_cost,
    }


def run_simulation(
    markets: list[dict],
    horizon: int = DEFAULT_HORIZON,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    bankroll: float = DEFAULT_BANKROLL,
    fee_rate: float = DEFAULT_FEE_RATE,
    dry_run: bool = False,
    db_path: Path | None = None,
    model: str | None = None,
    hypothesis_id: int | None = None,
    concurrency: int | None = None,
) -> dict:
    """Run a simulation across selected markets.

    Trials are executed concurrently (up to `concurrency` at a time) using
    asyncio + ThreadPoolExecutor. The public interface is synchronous.

    Returns run summary dict.
    """
    from polymarket_agent.analyst.estimator import ProbabilityEstimator
    from polymarket_agent.analyst.llm_client import LLMClient

    path = db_path or settings.backtest_db_path
    init_backtest_db(path)

    config = {
        "horizon": horizon,
        "edge_threshold": edge_threshold,
        "bankroll": bankroll,
        "fee_rate": fee_rate,
        "market_count": len(markets),
    }
    effective_model = model or settings.analysis_model
    config["model"] = effective_model
    if hypothesis_id is not None:
        config["hypothesis_id"] = hypothesis_id

    if dry_run:
        return _dry_run(markets, horizon, config)

    # Create run record
    started_at = datetime.now(timezone.utc).isoformat()
    with get_backtest_db(path) as conn:
        cursor = conn.execute(
            """INSERT INTO bt_simulation_runs (started_at, config, market_count)
            VALUES (?, ?, ?)""",
            (started_at, json.dumps(config), len(markets)),
        )
        run_id = cursor.lastrowid

    # Set up shared estimator (LLMClient is thread-safe after our changes)
    gatherer = HistoricalResearchGatherer(db_path=path)
    llm = LLMClient()
    estimator = ProbabilityEstimator(llm_client=llm, research_gatherer=gatherer)

    max_concurrency = concurrency if concurrency is not None else settings.simulation_concurrency
    db_lock = threading.Lock()
    start_time = time.time()

    # Run trials concurrently
    trial_results = asyncio.run(
        _run_trials_async(
            markets=markets,
            run_id=run_id,
            horizon=horizon,
            edge_threshold=edge_threshold,
            bankroll=bankroll,
            fee_rate=fee_rate,
            effective_model=effective_model,
            estimator=estimator,
            db_path=path,
            db_lock=db_lock,
            max_concurrency=max_concurrency,
            total=len(markets),
        )
    )

    # Accumulate results
    total_agent_brier = 0.0
    total_market_brier = 0.0
    total_pnl = 0.0
    total_cost = 0.0
    valid_trials = 0
    processed = 0

    for r in trial_results:
        if r.get("skipped"):
            continue
        processed += 1
        market_brier = r.get("market_brier", 0.0)
        agent_brier = r.get("agent_brier")
        total_market_brier += market_brier
        if agent_brier is not None:
            total_agent_brier += agent_brier
            valid_trials += 1
        trade = r.get("trade")
        if trade:
            total_pnl += trade["net_pnl"]
        total_cost += r.get("trial_cost", 0.0)

    # Use actual LLM cost from the shared client (more accurate than per-trial estimates)
    actual_cost = llm.get_usage_summary().get("estimated_cost", total_cost)

    # Finalize run
    completed_at = datetime.now(timezone.utc).isoformat()
    avg_agent_brier = total_agent_brier / valid_trials if valid_trials > 0 else None
    avg_market_brier = total_market_brier / processed if processed > 0 else None

    with get_backtest_db(path) as conn:
        conn.execute(
            """UPDATE bt_simulation_runs
            SET completed_at = ?, agent_brier = ?, market_brier = ?,
                simulated_pnl = ?, total_cost = ?
            WHERE id = ?""",
            (completed_at, avg_agent_brier, avg_market_brier, total_pnl, actual_cost, run_id),
        )

    # Auto-record hypothesis evidence if linked
    if hypothesis_id is not None and valid_trials > 0:
        try:
            from polymarket_agent.backtest.hypothesis import record_evidence
            brier_diff = None
            if avg_agent_brier is not None and avg_market_brier is not None:
                brier_diff = avg_agent_brier - avg_market_brier
            supports = None
            if brier_diff is not None and valid_trials >= 5:
                supports = 1 if brier_diff < 0 else 0

            p_value, effect_size = None, None
            if valid_trials >= 5:
                p_value, effect_size = _compute_paired_stats(run_id, path)

            record_evidence(
                hypothesis_id=hypothesis_id,
                run_id=run_id,
                trial_count=valid_trials,
                agent_brier=avg_agent_brier,
                market_brier=avg_market_brier,
                brier_diff=brier_diff,
                simulated_pnl=total_pnl,
                p_value=p_value,
                effect_size=effect_size,
                supports_hypothesis=supports,
                db_path=path,
            )
        except Exception as e:
            logger.warning("Failed to record hypothesis evidence: %s", e)

    return {
        "run_id": run_id,
        "market_count": len(markets),
        "valid_trials": valid_trials,
        "agent_brier": avg_agent_brier,
        "market_brier": avg_market_brier,
        "brier_diff": (avg_agent_brier - avg_market_brier)
        if avg_agent_brier is not None and avg_market_brier is not None
        else None,
        "simulated_pnl": total_pnl,
        "total_cost": actual_cost,
        "elapsed_seconds": time.time() - start_time,
    }


async def _run_trials_async(
    markets: list[dict],
    run_id: int,
    horizon: int,
    edge_threshold: float,
    bankroll: float,
    fee_rate: float,
    effective_model: str,
    estimator,
    db_path: Path,
    db_lock: threading.Lock,
    max_concurrency: int,
    total: int,
) -> list[dict]:
    """Run all trials concurrently bounded by a semaphore. Returns list of result dicts."""
    sem = asyncio.Semaphore(max_concurrency)
    completed = 0
    results = []
    results_lock = asyncio.Lock()

    async def run_one(market_dict: dict) -> dict:
        nonlocal completed
        async with sem:
            result = await asyncio.to_thread(
                _run_single_trial,
                market_dict,
                run_id,
                horizon,
                edge_threshold,
                bankroll,
                fee_rate,
                effective_model,
                estimator,
                db_path,
                db_lock,
            )
        async with results_lock:
            completed += 1
            results.append(result)
            if completed % 5 == 0 or completed <= 3 or completed == total:
                logger.info(
                    "Trial %d/%d completed (concurrency=%d)",
                    completed, total, max_concurrency,
                )
        return result

    await asyncio.gather(*[run_one(m) for m in markets])
    return results


def _compute_paired_stats(run_id: int, db_path: Path) -> tuple[float | None, float | None]:
    """Compute paired t-test p-value and Cohen's d from per-trial Brier scores."""
    with get_backtest_db(db_path) as conn:
        rows = conn.execute(
            """SELECT agent_brier, market_brier
            FROM bt_simulation_trials
            WHERE run_id = ? AND agent_brier IS NOT NULL AND market_brier IS NOT NULL""",
            (run_id,),
        ).fetchall()

    if len(rows) < 5:
        return None, None

    diffs = [r["agent_brier"] - r["market_brier"] for r in rows]
    n = len(diffs)
    mean_diff = sum(diffs) / n
    var_diff = sum((d - mean_diff) ** 2 for d in diffs) / (n - 1)
    sd_diff = math.sqrt(var_diff) if var_diff > 0 else 0.001

    # t-statistic
    t_stat = mean_diff / (sd_diff / math.sqrt(n))

    # Two-tailed p-value using normal approximation (accurate for n >= 30)
    z = abs(t_stat)
    # Approximation using math.erfc: p = erfc(z / sqrt(2))
    p_value = math.erfc(z / math.sqrt(2))

    # Cohen's d
    effect_size = mean_diff / sd_diff if sd_diff > 0 else 0.0

    return p_value, effect_size


def _dry_run(markets: list[dict], horizon: int, config: dict) -> dict:
    """Preview what would be simulated without calling LLM."""
    results = []
    skipped = 0

    for m in markets:
        built = build_market_at_horizon(m, horizon)
        if built is None:
            skipped += 1
            continue
        market_obj, _ = built
        results.append({
            "id": m["id"][:16],
            "question": m.get("question", "")[:60],
            "category": m.get("category") or "(null)",
            "volume": m.get("volume", 0),
            "price_at_horizon": market_obj.last_price_yes,
            "outcome": m.get("resolution_outcome"),
        })

    return {
        "dry_run": True,
        "config": config,
        "markets": results,
        "skipped": skipped,
        "total": len(results),
    }


# ---------------------------------------------------------------------------
# Stratified Market Selection
# ---------------------------------------------------------------------------


def select_markets_stratified(
    n_per_cell: int = 20,
    categories: list[str | None] | None = None,
    volume_tiers: dict[str, tuple[float, float | None]] | None = None,
    horizon: int = DEFAULT_HORIZON,
    db_path: Path | None = None,
) -> tuple[list[dict], dict]:
    """Select markets with stratified sampling across category x volume tier.

    Returns:
        (markets, cell_counts) where cell_counts is
        {(category, tier): {"requested": n, "available": m, "selected": k}}
    """
    tiers = volume_tiers or VOLUME_TIERS
    path = db_path or settings.backtest_db_path

    with get_backtest_db(path) as conn:
        # Auto-discover categories if not specified
        if categories is None:
            cat_rows = conn.execute(
                """SELECT DISTINCT m.category
                FROM bt_markets m
                WHERE m.has_history = 1
                  AND m.resolution_outcome IN ('YES', 'NO')
                  AND EXISTS (
                      SELECT 1 FROM bt_price_history p
                      WHERE p.market_id = m.id
                      AND p.timestamp <= CAST(strftime('%%s', m.end_date, '-%d days') AS INTEGER)
                  )
                ORDER BY m.category NULLS FIRST""" % horizon
            ).fetchall()
            categories = [row["category"] for row in cat_rows]

        markets = []
        cell_counts = {}

        for cat in categories:
            for tier_name, (vol_min, vol_max) in tiers.items():
                # Build query for this cell
                conditions = [
                    "m.has_history = 1",
                    "m.resolution_outcome IN ('YES', 'NO')",
                    """EXISTS (
                        SELECT 1 FROM bt_price_history p
                        WHERE p.market_id = m.id
                        AND p.timestamp <= CAST(strftime('%%s', m.end_date, '-%d days') AS INTEGER)
                    )""" % horizon,
                    "m.volume >= ?",
                ]
                params: list = [vol_min]

                if vol_max is not None:
                    conditions.append("m.volume < ?")
                    params.append(vol_max)

                if cat is None:
                    conditions.append("m.category IS NULL")
                else:
                    conditions.append("m.category = ?")
                    params.append(cat)

                where = " AND ".join(conditions)

                # Count available
                count_row = conn.execute(
                    f"SELECT COUNT(*) as c FROM bt_markets m WHERE {where}", params
                ).fetchone()
                available = count_row["c"]

                # Sample
                rows = conn.execute(
                    f"""SELECT m.id, m.question, m.description, m.category, m.end_date,
                            m.volume, m.liquidity, m.resolution_outcome, m.yes_token,
                            m.no_token, m.event_id
                    FROM bt_markets m
                    WHERE {where}
                    ORDER BY RANDOM()
                    LIMIT ?""",
                    params + [n_per_cell],
                ).fetchall()

                selected = len(rows)
                cell_key = (cat, tier_name)
                cell_counts[cell_key] = {
                    "requested": n_per_cell,
                    "available": available,
                    "selected": selected,
                }

                if selected < n_per_cell:
                    logger.warning(
                        "Cell (%s, %s): only %d/%d markets available",
                        cat or "(null)", tier_name, available, n_per_cell,
                    )

                # Load price history for selected markets
                for row in rows:
                    market = dict(row)
                    history = conn.execute(
                        """SELECT timestamp as t, price as p
                        FROM bt_price_history
                        WHERE market_id = ?
                        ORDER BY timestamp""",
                        (row["id"],),
                    ).fetchall()
                    market["price_history"] = [{"t": h["t"], "p": h["p"]} for h in history]
                    markets.append(market)

    logger.info(
        "Stratified selection: %d markets across %d cells (%d categories x %d tiers)",
        len(markets), len(cell_counts), len(categories), len(tiers),
    )
    return markets, cell_counts


# ---------------------------------------------------------------------------
# Multi-Model Evaluation
# ---------------------------------------------------------------------------


def run_multi_model_evaluation(
    markets: list[dict],
    models: list[str] | None = None,
    horizon: int = DEFAULT_HORIZON,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    bankroll: float = DEFAULT_BANKROLL,
    fee_rate: float = DEFAULT_FEE_RATE,
    budget: float | None = None,
    progressive: bool = True,
    progress_callback=None,
    db_path: Path | None = None,
    concurrency: int | None = None,
) -> dict:
    """Run evaluation across multiple models on the same market set.

    Args:
        models: Model IDs in execution order. Default: Haiku, Sonnet, Opus.
        budget: Maximum total LLM cost in USD. None = no limit.
        progressive: If True, call progress_callback after each model.
            Callback signature: (model, run_result, comparison_so_far) -> bool.
            Return False to stop.
        progress_callback: Callable for progressive mode.

    Returns:
        {"runs": {model: run_result}, "comparison": cross_model_comparison_dict}
    """
    from polymarket_agent.backtest.analysis import cross_model_comparison

    model_list = models or EVALUATION_MODELS
    runs = {}
    run_ids = []
    spent = 0.0

    for model_id in model_list:
        # Budget check
        estimated_cost = len(markets) * MODEL_COST_PER_TRIAL.get(model_id, 0.05)
        if budget is not None and spent + estimated_cost > budget:
            logger.warning(
                "Skipping %s: estimated $%.2f would exceed budget ($%.2f spent of $%.2f)",
                model_id, estimated_cost, spent, budget,
            )
            continue

        # Run simulation for this model
        result = run_simulation(
            markets=markets,
            horizon=horizon,
            edge_threshold=edge_threshold,
            bankroll=bankroll,
            fee_rate=fee_rate,
            db_path=db_path,
            model=model_id,
            concurrency=concurrency,
        )
        runs[model_id] = result
        run_ids.append(result["run_id"])
        spent += result.get("total_cost", 0.0)

        # Progressive callback
        if progressive and progress_callback:
            comparison_so_far = cross_model_comparison(run_ids, db_path=db_path) if len(run_ids) > 1 else None
            should_continue = progress_callback(model_id, result, comparison_so_far)
            if not should_continue:
                logger.info("Progressive mode: stopped after %s", model_id)
                break

    # Final comparison
    comparison = cross_model_comparison(run_ids, db_path=db_path) if len(run_ids) > 1 else {}

    return {
        "runs": runs,
        "run_ids": run_ids,
        "comparison": comparison,
        "total_spent": spent,
    }
