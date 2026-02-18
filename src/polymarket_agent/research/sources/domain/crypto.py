"""Crypto domain source (stub for future on-chain/governance data integration)."""

import logging

from polymarket_agent.research.sources.domain.base import DomainSource

logger = logging.getLogger(__name__)


class CryptoSource(DomainSource):
    @property
    def category(self) -> str:
        return "crypto"

    def gather(self, question: str, description: str | None = None) -> dict | None:
        # Stub: Future integration with on-chain data, governance forums, etc.
        logger.debug("Crypto domain source not yet implemented for: %s", question[:50])
        return None
