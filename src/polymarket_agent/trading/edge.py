"""Edge computation and Kelly position sizing."""

import logging
import math

from polymarket_agent.config import settings
from polymarket_agent.models import (
    Market,
    ProbabilityEstimate,
    Side,
    TradeRecommendation,
)

logger = logging.getLogger(__name__)


def compute_required_edge(
    market: Market,
    confidence_width: float = 0.30,
    spread_width: float = 0.0,
    category_brier: float | None = None,
    strategy_config: dict | None = None,
) -> float:
    """Compute per-market edge threshold based on market efficiency.

    Scales by volume (higher volume = higher threshold), confidence width
    (wider band = higher threshold), and calibration quality (better Brier
    = lower threshold). Clamped to [min_edge_floor, max_edge_ceiling].

    If strategy_config is provided and contains a category override for this
    market's category, that override is used as the base threshold.
    """
    base = settings.min_edge_threshold  # 0.10 default

    # Strategy config category override takes precedence
    if strategy_config and market.category:
        overrides = (
            strategy_config.get("edge_thresholds", {}).get("category_overrides", {})
        )
        if market.category in overrides:
            base = float(overrides[market.category])

    # Volume factor: scale up for high-volume (efficient) markets
    vol = max(market.volume, 1.0)
    ref = settings.adaptive_edge_reference_volume
    if ref > 0 and vol > 0:
        volume_factor = 1.0 + 0.3 * math.log10(vol) / math.log10(max(ref, 10.0))
    else:
        volume_factor = 1.0

    # Confidence factor: wider band = more uncertain = need more edge
    confidence_factor = 1.0 + confidence_width

    # Calibration factor: good Brier score reduces threshold
    cal_factor = 1.0
    if category_brier is not None:
        if category_brier < 0.25:
            # Better than coin-flip: reduce threshold (down to 0.8x)
            cal_factor = 0.8 + 0.8 * category_brier
        elif category_brier > 0.25:
            # Worse than coin-flip: increase threshold (up to 1.2x)
            cal_factor = 1.0 + 0.4 * (category_brier - 0.25)

    threshold = base * volume_factor * confidence_factor * cal_factor

    # Clamp
    return max(settings.min_edge_floor, min(settings.max_edge_ceiling, threshold))


def compute_taker_fee(price: float, fee_rate: float, exponent: float = 1.0) -> float:
    """Compute Polymarket taker fee per share.

    Formula: price * fee_rate * (price * (1 - price))^exponent
    Returns 0.0 if fee_rate is 0 or price is at extremes.
    """
    if fee_rate <= 0 or price <= 0 or price >= 1:
        return 0.0
    return price * fee_rate * (price * (1.0 - price)) ** exponent


def compute_edge(
    estimate: ProbabilityEstimate,
    market: Market,
    fee_rate: float = 0.0,
    fee_exponent: float = 1.0,
) -> tuple[float, float, Side]:
    """Compute raw and adjusted edge.

    Returns (raw_edge, adjusted_edge, side).
    Positive edge means the agent thinks YES is underpriced.
    """
    market_price = market.last_price_yes or 0.5
    agent_prob = estimate.final_estimate

    # Determine direction
    raw_edge = agent_prob - market_price

    if raw_edge > 0:
        side = Side.YES
    else:
        side = Side.NO
        raw_edge = abs(raw_edge)
        market_price = 1.0 - market_price  # Use NO price
        agent_prob = 1.0 - agent_prob

    # Subtract round-trip fee impact from raw edge
    if fee_rate > 0:
        fee_per_share = compute_taker_fee(market_price, fee_rate, fee_exponent)
        # Round-trip: pay fee on entry and exit
        raw_edge -= 2 * fee_per_share

    # Adjusted edge: scale by confidence width
    confidence_width = estimate.confidence_high - estimate.confidence_low
    confidence_factor = max(0.3, 1.0 - confidence_width)  # Wider band = less confident
    adjusted_edge = raw_edge * confidence_factor

    return raw_edge, adjusted_edge, side


def kelly_position_size(
    edge: float,
    market_price: float,
    bankroll: float,
    kelly_fraction: float | None = None,
    max_per_market: float | None = None,
    max_portfolio: float | None = None,
    current_exposure: float = 0.0,
) -> float:
    """Compute position size using fractional Kelly criterion.

    Kelly formula for binary bets:
        f* = (p * (b + 1) - 1) / b
    where p = true probability, b = odds (payout / stake)
    """
    frac = kelly_fraction or settings.kelly_fraction
    max_market = max_per_market or settings.max_position_per_market
    max_port = max_portfolio or settings.max_portfolio_exposure

    if market_price <= 0 or market_price >= 1 or edge <= 0:
        return 0.0

    # Odds: if we buy YES at price p, we win (1-p)/p per dollar risked
    odds = (1.0 - market_price) / market_price
    true_prob = market_price + edge

    # Kelly fraction
    full_kelly = (true_prob * (odds + 1) - 1) / odds
    if full_kelly <= 0:
        return 0.0

    # Apply fractional Kelly
    size = full_kelly * frac * bankroll

    # Apply caps
    size = min(size, max_market)
    size = min(size, max_port - current_exposure)
    size = max(size, 0.0)

    return round(size, 2)


def build_recommendation(
    market: Market,
    estimate: ProbabilityEstimate,
    bankroll: float,
    current_exposure: float = 0.0,
    clob_midpoint: float | None = None,
    fee_rate: float = 0.0,
    fee_exponent: float = 1.0,
    spread_width: float = 0.0,
    category_brier: float | None = None,
    strategy_config: dict | None = None,
) -> tuple[TradeRecommendation | None, float, float]:
    """Build a trade recommendation if edge exceeds adaptive threshold.

    Returns (recommendation_or_none, adjusted_edge, required_threshold).
    """
    raw_edge, adjusted_edge, side = compute_edge(
        estimate, market, fee_rate=fee_rate, fee_exponent=fee_exponent,
    )

    confidence_width = estimate.confidence_high - estimate.confidence_low
    required_edge = compute_required_edge(
        market, confidence_width, spread_width, category_brier,
        strategy_config=strategy_config,
    )

    if adjusted_edge < required_edge:
        logger.info(
            "Market %s: edge %.3f below adaptive threshold %.3f, skipping",
            market.id[:8],
            adjusted_edge,
            required_edge,
        )
        return None, adjusted_edge, required_edge

    # Determine the price we're trading at — prefer CLOB midpoint over stale Gamma price
    if clob_midpoint is not None:
        if side == Side.YES:
            market_price = clob_midpoint
        else:
            market_price = 1.0 - clob_midpoint
    elif side == Side.YES:
        market_price = market.last_price_yes or 0.5
    else:
        market_price = market.last_price_no or 0.5
        if market.last_price_yes is not None:
            market_price = 1.0 - market.last_price_yes

    size = kelly_position_size(
        edge=adjusted_edge,
        market_price=market_price,
        bankroll=bankroll,
        current_exposure=current_exposure,
    )

    if size < 1.0:  # Minimum $1 trade
        return None, adjusted_edge, required_edge

    rec = TradeRecommendation(
        market_id=market.id,
        market_question=market.question,
        side=side,
        raw_edge=round(raw_edge, 4),
        adjusted_edge=round(adjusted_edge, 4),
        market_price=round(market_price, 4),
        agent_estimate=round(estimate.final_estimate, 4),
        recommended_size=size,
        limit_price=round(market_price, 4),
        reasoning=estimate.thesis,
        thesis=estimate.thesis,
        confidence_low=estimate.confidence_low,
        confidence_high=estimate.confidence_high,
    )
    return rec, adjusted_edge, required_edge
