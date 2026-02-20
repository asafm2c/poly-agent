"""Simulation harness: run estimation pipeline against historical markets."""

import json
import logging
import math
import random
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

    if category is not None:
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


def run_simulation(
    markets: list[dict],
    horizon: int = DEFAULT_HORIZON,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    bankroll: float = DEFAULT_BANKROLL,
    fee_rate: float = DEFAULT_FEE_RATE,
    dry_run: bool = False,
    db_path: Path | None = None,
) -> dict:
    """Run a simulation across selected markets.

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

    # Set up estimator with historical gatherer
    gatherer = HistoricalResearchGatherer(db_path=path)
    llm = LLMClient()
    estimator = ProbabilityEstimator(llm_client=llm, research_gatherer=gatherer)

    # Run trials
    total_agent_brier = 0.0
    total_market_brier = 0.0
    total_pnl = 0.0
    total_cost = 0.0
    valid_trials = 0
    start_time = time.time()

    prev_cumulative_cost = 0.0

    for i, market_dict in enumerate(markets):
        trial_start = time.time()

        # Build market at horizon
        result = build_market_at_horizon(market_dict, horizon)
        if result is None:
            logger.warning("Skipping %s: no price data at horizon", market_dict["id"][:16])
            continue

        market_obj, truncated_history = result
        market_price = market_obj.last_price_yes

        # Attach price history for the gatherer
        market_obj._price_history_for_dossier = truncated_history

        # Parse outcome
        outcome = 1.0 if market_dict["resolution_outcome"] == "YES" else 0.0

        # Run estimation
        agent_estimate = None
        confidence_low = None
        confidence_high = None
        reasoning = None
        try:
            estimate = estimator.estimate(market_obj)
            agent_estimate = estimate.final_estimate
            confidence_low = estimate.confidence_low
            confidence_high = estimate.confidence_high
            reasoning = estimate.thesis
        except Exception as e:
            logger.error("Estimation failed for %s: %s", market_dict["id"][:16], e)

        # Compute Brier scores
        agent_brier = (agent_estimate - outcome) ** 2 if agent_estimate is not None else None
        market_brier = (market_price - outcome) ** 2

        # Compute edge and simulated trade
        edge = (agent_estimate - market_price) if agent_estimate is not None else None
        trade = None
        if agent_estimate is not None:
            trade = compute_simulated_trade(
                agent_estimate, market_price, outcome,
                edge_threshold=edge_threshold, bankroll=bankroll, fee_rate=fee_rate,
            )

        # LLM cost (delta from previous cumulative)
        usage = llm.get_usage_summary()
        cumulative_cost = usage.get("estimated_cost", 0.0)
        trial_cost = cumulative_cost - prev_cumulative_cost
        prev_cumulative_cost = cumulative_cost

        trial_duration = int((time.time() - trial_start) * 1000)

        # Persist trial
        with get_backtest_db(path) as conn:
            conn.execute(
                """INSERT INTO bt_simulation_trials
                (run_id, market_id, horizon_days, market_price_at_horizon,
                 agent_estimate, confidence_low, confidence_high, outcome,
                 agent_brier, market_brier, edge, simulated_trade,
                 reasoning, llm_cost, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, market_dict["id"], horizon, market_price,
                    agent_estimate, confidence_low, confidence_high, outcome,
                    agent_brier, market_brier, edge,
                    json.dumps(trade) if trade else None,
                    reasoning, trial_cost, trial_duration,
                ),
            )

        # Accumulate
        if agent_brier is not None:
            total_agent_brier += agent_brier
            valid_trials += 1
        total_market_brier += market_brier
        if trade:
            total_pnl += trade["net_pnl"]
        total_cost += trial_cost

        # Progress logging
        processed = i + 1
        if processed % 5 == 0 or processed <= 3:
            elapsed = time.time() - start_time
            avg_agent = total_agent_brier / valid_trials if valid_trials > 0 else None
            avg_market = total_market_brier / processed if processed > 0 else None
            logger.info(
                "Trial %d/%d | Agent Brier: %s | Market Brier: %.4f | "
                "P&L: $%.2f | Elapsed: %.0fs",
                processed, len(markets),
                f"{avg_agent:.4f}" if avg_agent is not None else "N/A",
                avg_market, total_pnl, elapsed,
            )

    # Finalize run
    completed_at = datetime.now(timezone.utc).isoformat()
    total_processed = valid_trials  # Only count trials with valid estimates
    avg_agent_brier = total_agent_brier / valid_trials if valid_trials > 0 else None
    avg_market_brier = total_market_brier / len(markets) if markets else None

    with get_backtest_db(path) as conn:
        conn.execute(
            """UPDATE bt_simulation_runs
            SET completed_at = ?, agent_brier = ?, market_brier = ?,
                simulated_pnl = ?, total_cost = ?
            WHERE id = ?""",
            (completed_at, avg_agent_brier, avg_market_brier, total_pnl, total_cost, run_id),
        )

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
        "total_cost": total_cost,
        "elapsed_seconds": time.time() - start_time,
    }


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
