"""Market event detection: price movements, volume spikes, new markets."""

import logging
from datetime import datetime

from polymarket_agent.config import settings
from polymarket_agent.models import Market, MarketEvent

logger = logging.getLogger(__name__)


class EventDetector:
    def __init__(self, price_change_threshold: float | None = None):
        self.price_threshold = price_change_threshold or settings.price_change_threshold

    def detect_events(
        self, current_markets: list[Market], previous_markets: dict[str, Market]
    ) -> list[MarketEvent]:
        """Compare current markets against previous state and detect events."""
        events: list[MarketEvent] = []

        for market in current_markets:
            prev = previous_markets.get(market.id)

            if prev is None:
                # New market
                events.append(
                    MarketEvent(
                        market_id=market.id,
                        event_type="new_market",
                        detected_at=datetime.utcnow(),
                    )
                )
                continue

            # Price change detection
            if market.last_price_yes is not None and prev.last_price_yes is not None:
                price_diff = market.last_price_yes - prev.last_price_yes
                if abs(price_diff) >= self.price_threshold:
                    events.append(
                        MarketEvent(
                            market_id=market.id,
                            event_type="price_change",
                            magnitude=abs(price_diff),
                            direction="up" if price_diff > 0 else "down",
                            detected_at=datetime.utcnow(),
                        )
                    )

            # Volume spike detection (>50% increase)
            if prev.volume > 0 and market.volume > prev.volume * 1.5:
                events.append(
                    MarketEvent(
                        market_id=market.id,
                        event_type="volume_spike",
                        magnitude=market.volume / prev.volume,
                        detected_at=datetime.utcnow(),
                    )
                )

        if events:
            logger.info("Detected %d market events", len(events))
        return events
