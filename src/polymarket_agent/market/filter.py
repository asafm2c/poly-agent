"""Market filter: configurable criteria for selecting tradeable markets."""

import logging
from datetime import datetime, timezone

from polymarket_agent.config import settings
from polymarket_agent.models import Market

logger = logging.getLogger(__name__)


class MarketFilter:
    def __init__(
        self,
        min_volume: float | None = None,
        min_liquidity: float | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        min_days_to_resolution: int | None = None,
        max_days_to_resolution: int | None = None,
        categories: list[str] | None = None,
    ):
        self.min_volume = min_volume if min_volume is not None else settings.min_volume
        self.min_liquidity = min_liquidity if min_liquidity is not None else settings.min_liquidity
        self.min_price = min_price if min_price is not None else settings.min_price
        self.max_price = max_price if max_price is not None else settings.max_price
        self.min_days = (
            min_days_to_resolution
            if min_days_to_resolution is not None
            else settings.min_days_to_resolution
        )
        self.max_days = (
            max_days_to_resolution
            if max_days_to_resolution is not None
            else settings.max_days_to_resolution
        )
        self.categories = categories

    def apply(self, markets: list[Market]) -> list[Market]:
        """Filter markets based on configured criteria."""
        filtered = []
        for market in markets:
            if self._passes(market):
                filtered.append(market)
        logger.info("Filtered %d → %d markets", len(markets), len(filtered))
        return filtered

    def _passes(self, market: Market) -> bool:
        if not market.active or market.resolved:
            return False

        if market.volume < self.min_volume:
            return False

        if market.liquidity < self.min_liquidity:
            return False

        # Price check (YES side)
        price = market.last_price_yes
        if price is not None:
            if price < self.min_price or price > self.max_price:
                return False

        # Time to resolution
        if market.end_date:
            now = datetime.now(timezone.utc)
            end = market.end_date
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            days_to_resolution = (end - now).days
            if days_to_resolution < self.min_days:
                return False
            if days_to_resolution > self.max_days:
                return False

        # Category filter
        if self.categories and market.category:
            if market.category.lower() not in [c.lower() for c in self.categories]:
                return False

        return True
