"""Opportunity scoring: rank candidate markets by likelihood of mispricing."""

import logging
import math
from datetime import datetime, timezone

from polymarket_agent.config import settings
from polymarket_agent.models import Market, MarketEvent
from polymarket_agent.trading.calibration import compute_calibration

logger = logging.getLogger(__name__)


def price_score(price_yes: float | None) -> float:
    """Score peaks at 0.50 (most room for edge), linear falloff toward extremes."""
    if price_yes is None:
        return 0.5
    return max(0.0, 1.0 - 2.0 * abs(price_yes - 0.5))


def volume_score(volume: float, max_volume: float) -> float:
    """Lower volume scores higher (less efficient market). Inverse log scale."""
    if volume <= 0 or max_volume <= 0:
        return 0.5
    if volume >= max_volume:
        return 0.0
    log_vol = math.log10(max(volume, 1.0))
    log_max = math.log10(max(max_volume, 1.0))
    if log_max <= 0:
        return 0.5
    score = 1.0 - log_vol / log_max
    return max(0.0, min(1.0, score))


def event_score(market_id: str, events: list[MarketEvent]) -> float:
    """1.0 if any event was detected for this market, else 0.0."""
    for e in events:
        if e.market_id == market_id:
            return 1.0
    return 0.0


def screening_score(direction: str, confidence: str) -> float:
    """Score based on screening LLM's directional signal."""
    if direction == "fair":
        return 0.0
    # Directional signal exists
    confidence_multiplier = {"low": 0.5, "medium": 0.75, "high": 1.0}.get(confidence, 0.5)
    return confidence_multiplier


def time_score(days_to_resolution: int | None) -> float:
    """Linear from 0.0 at 60 days to 1.0 at 1 day. Nearer = higher score."""
    if days_to_resolution is None:
        return 0.5
    days = max(1, min(60, days_to_resolution))
    return (60 - days) / 59.0


def category_score(category: str | None) -> float:
    """Score based on calibration performance in this category.

    Lower Brier score = better calibration = higher score.
    Returns 0.5 (neutral) when insufficient data.
    """
    if not category:
        return 0.5
    try:
        cal = compute_calibration(category=category)
        if cal.brier_score is not None and cal.resolved_predictions >= 20:
            # Brier score ranges 0 (perfect) to 1 (worst).
            # Map to score: Brier 0.0 → 1.0, Brier 0.25 → 0.5, Brier 0.5+ → 0.0
            return max(0.0, min(1.0, 1.0 - 2.0 * cal.brier_score))
    except Exception:
        pass
    return 0.5


def compute_opportunity_score(
    market: Market,
    events: list[MarketEvent],
    screen_result: dict | None = None,
    max_volume: float = 1_000_000.0,
) -> float:
    """Compute composite opportunity score for a market."""
    # Compute days to resolution
    days_remaining = None
    if market.end_date:
        now = datetime.now(timezone.utc)
        end = market.end_date
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        days_remaining = (end - now).days

    # Get screening signal
    direction = "fair"
    confidence = "low"
    if screen_result:
        direction = screen_result.get("initial_direction", "fair")
        confidence = screen_result.get("confidence", "low")

    # Compute individual scores
    p_score = price_score(market.last_price_yes)
    v_score = volume_score(market.volume, max_volume)
    e_score = event_score(market.id, events)
    s_score = screening_score(direction, confidence)
    t_score = time_score(days_remaining)
    c_score = category_score(market.category)

    # Weighted composite
    score = (
        settings.opportunity_weight_price * p_score
        + settings.opportunity_weight_volume * v_score
        + settings.opportunity_weight_event * e_score
        + settings.opportunity_weight_screen * s_score
        + settings.opportunity_weight_time * t_score
        + settings.opportunity_weight_calibration * c_score
    )

    return score


def score_candidates(
    markets: list[Market],
    events: list[MarketEvent],
    screening_results: dict[str, dict],
) -> list[tuple[Market, float]]:
    """Score and sort candidate markets by opportunity.

    Args:
        markets: Filtered candidate markets
        events: Detected events from the most recent scan
        screening_results: Dict mapping market_id to screening result dict

    Returns:
        List of (market, score) tuples sorted by descending score
    """
    if not markets:
        return []

    max_volume = max(m.volume for m in markets) if markets else 1_000_000.0

    scored = []
    for market in markets:
        screen_result = screening_results.get(market.id)
        score = compute_opportunity_score(market, events, screen_result, max_volume)
        scored.append((market, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
