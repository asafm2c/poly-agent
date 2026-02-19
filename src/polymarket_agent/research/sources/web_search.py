"""Tavily web search integration."""

import logging
import time

from tavily import TavilyClient

from polymarket_agent import metrics
from polymarket_agent.config import settings
from polymarket_agent.models import SearchResult

logger = logging.getLogger(__name__)


class WebSearcher:
    def __init__(self, api_key: str | None = None):
        key = api_key or settings.tavily_api_key
        if not key:
            logger.warning("No Tavily API key configured")
            self._client = None
        else:
            self._client = TavilyClient(api_key=key)

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search the web for information relevant to a market."""
        if not self._client:
            logger.warning("Tavily client not configured, skipping web search")
            return []

        try:
            t0 = time.monotonic()
            response = self._client.search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                include_answer=False,
            )
            metrics.record("api_call", service="tavily", endpoint="search", status=200, latency_ms=int((time.monotonic() - t0) * 1000))
            results = []
            for item in response.get("results", []):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        content=item.get("content", ""),
                        score=item.get("score"),
                    )
                )
            logger.info("Web search for '%s': %d results", query[:50], len(results))
            return results
        except Exception as e:
            metrics.record("api_call", service="tavily", endpoint="search", status="error")
            metrics.record("api_error", service="tavily", endpoint="search", error=str(e))
            logger.error("Tavily search error for '%s': %s", query[:50], e)
            return []

    def build_query(self, question: str, category: str | None = None) -> str:
        """Build a search query from a market question."""
        query = question
        if category:
            query = f"{category}: {question}"
        # Remove common prediction market phrasing
        for prefix in ["Will ", "Is ", "Does ", "Can ", "Has "]:
            if query.startswith(prefix):
                query = query[len(prefix) :]
                break
        return query
