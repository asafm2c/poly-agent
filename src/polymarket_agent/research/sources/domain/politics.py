"""Politics domain source (stub for future polling/election data integration)."""

import logging

from polymarket_agent.research.sources.domain.base import DomainSource

logger = logging.getLogger(__name__)


class PoliticsSource(DomainSource):
    @property
    def category(self) -> str:
        return "politics"

    def gather(self, question: str, description: str | None = None) -> dict | None:
        # Stub: Future integration with polling APIs, FiveThirtyEight, etc.
        logger.debug("Politics domain source not yet implemented for: %s", question[:50])
        return None
