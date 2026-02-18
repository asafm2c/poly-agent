"""Base class for domain-specific research sources."""

from abc import ABC, abstractmethod


class DomainSource(ABC):
    """Base class for category-specific research data providers."""

    @property
    @abstractmethod
    def category(self) -> str:
        """The market category this source covers."""
        ...

    @abstractmethod
    def gather(self, question: str, description: str | None = None) -> dict | None:
        """Gather domain-specific data for a market.

        Returns a dict of domain data or None if no data available.
        """
        ...
