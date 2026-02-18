"""Market scanner: orchestrates discovery, filtering, and event detection."""

import logging

from polymarket_agent.market.clob_client import ClobClient
from polymarket_agent.market.events import EventDetector
from polymarket_agent.market.filter import MarketFilter
from polymarket_agent.market.gamma_client import GammaClient
from polymarket_agent.market.storage import get_all_active_markets, upsert_markets
from polymarket_agent.models import Market, MarketEvent

logger = logging.getLogger(__name__)


class MarketScanner:
    def __init__(
        self,
        gamma_client: GammaClient | None = None,
        clob_client: ClobClient | None = None,
        market_filter: MarketFilter | None = None,
        event_detector: EventDetector | None = None,
    ):
        self.gamma = gamma_client or GammaClient()
        self.clob = clob_client or ClobClient()
        self.filter = market_filter or MarketFilter()
        self.events = event_detector or EventDetector()

    def scan(self) -> tuple[list[Market], list[MarketEvent]]:
        """Run a full scan cycle: fetch, store, filter, detect events.

        Returns:
            Tuple of (filtered candidate markets, detected events)
        """
        # Get previous state for event detection
        previous = {m.id: m for m in get_all_active_markets()}

        # Fetch fresh market data
        logger.info("Fetching markets from Gamma API...")
        all_markets = self.gamma.fetch_all_active_markets()

        if not all_markets:
            logger.warning("No markets returned from Gamma API")
            return [], []

        # Store in database
        upsert_markets(all_markets)

        # Detect events
        events = self.events.detect_events(all_markets, previous)

        # Apply filters
        candidates = self.filter.apply(all_markets)

        logger.info(
            "Scan complete: %d total, %d candidates, %d events",
            len(all_markets),
            len(candidates),
            len(events),
        )
        return candidates, events

    def close(self):
        self.gamma.close()
        self.clob.close()
