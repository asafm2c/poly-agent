"""Edge computation and Kelly position sizing."""

import logging

from polymarket_agent.config import settings
from polymarket_agent.models import (
    Market,
    ProbabilityEstimate,
    Side,
    TradeRecommendation,
)

logger = logging.getLogger(__name__)


def compute_edge(estimate: ProbabilityEstimate, market: Market) -> tuple[float, float, Side]:
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
) -> TradeRecommendation | None:
    """Build a trade recommendation if edge exceeds threshold."""
    raw_edge, adjusted_edge, side = compute_edge(estimate, market)

    if adjusted_edge < settings.min_edge_threshold:
        logger.info(
            "Market %s: edge %.3f below threshold %.3f, skipping",
            market.id[:8],
            adjusted_edge,
            settings.min_edge_threshold,
        )
        return None

    # Determine the price we're trading at
    if side == Side.YES:
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
        return None

    return TradeRecommendation(
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
