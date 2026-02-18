"""Research dossier builder: aggregates all sources into a structured dossier."""

import logging
from datetime import datetime, timedelta

from polymarket_agent.market.gamma_client import GammaClient
from polymarket_agent.models import Market, ResearchDossier
from polymarket_agent.research.sources.domain.base import DomainSource
from polymarket_agent.research.sources.domain.crypto import CryptoSource
from polymarket_agent.research.sources.domain.politics import PoliticsSource
from polymarket_agent.research.sources.polymarket import PolymarketResearch
from polymarket_agent.research.sources.web_search import WebSearcher

logger = logging.getLogger(__name__)


class ResearchGatherer:
    def __init__(
        self,
        web_searcher: WebSearcher | None = None,
        polymarket_research: PolymarketResearch | None = None,
        gamma_client: GammaClient | None = None,
        cache_max_age_minutes: int = 60,
    ):
        self.web = web_searcher or WebSearcher()
        self._gamma = gamma_client or GammaClient()
        self.poly = polymarket_research or PolymarketResearch(self._gamma)
        self.cache_max_age = timedelta(minutes=cache_max_age_minutes)
        self._cache: dict[str, ResearchDossier] = {}
        self._domain_sources: dict[str, DomainSource] = {}
        self._register_default_domain_sources()

    def _register_default_domain_sources(self):
        for source in [PoliticsSource(), CryptoSource()]:
            self._domain_sources[source.category.lower()] = source

    def register_domain_source(self, source: DomainSource):
        self._domain_sources[source.category.lower()] = source

    def gather(self, market: Market) -> ResearchDossier:
        """Build a research dossier for a market, using cache if available."""
        # Check cache
        cached = self._cache.get(market.id)
        if cached and (datetime.utcnow() - cached.created_at) < self.cache_max_age:
            logger.info("Using cached dossier for market %s", market.id)
            cached.cached = True
            return cached

        logger.info("Gathering research for: %s", market.question[:60])

        # Web search
        query = self.web.build_query(market.question, market.category)
        search_results = self.web.search(query)

        # Polymarket comments
        comments = self.poly.fetch_comments(market.id)
        sentiment = self.poly.summarize_sentiment(comments)

        # Related markets
        related = self.poly.find_related_markets(market.event_id, market.id)

        # Domain-specific data
        domain_data = None
        if market.category:
            source = self._domain_sources.get(market.category.lower())
            if source:
                domain_data = source.gather(market.question, market.description)

        dossier = ResearchDossier(
            market_id=market.id,
            market_question=market.question,
            market_description=market.description,
            market_category=market.category,
            market_end_date=market.end_date,
            current_price_yes=market.last_price_yes,
            current_price_no=market.last_price_no,
            web_search_results=search_results,
            polymarket_comments=comments[:10],  # Limit to most recent
            comment_sentiment_summary=sentiment,
            related_markets=related,
            domain_data=domain_data,
            created_at=datetime.utcnow(),
            cached=False,
        )

        # Cache it
        self._cache[market.id] = dossier
        return dossier

    def format_dossier_for_llm(self, dossier: ResearchDossier) -> str:
        """Format a dossier as text for LLM consumption."""
        parts = [
            f"# Market Research: {dossier.market_question}",
            "",
        ]

        if dossier.market_description:
            parts.append(f"**Description:** {dossier.market_description}")
            parts.append("")

        if dossier.market_category:
            parts.append(f"**Category:** {dossier.market_category}")

        if dossier.market_end_date:
            parts.append(f"**Resolution date:** {dossier.market_end_date.strftime('%Y-%m-%d')}")

        if dossier.current_price_yes is not None:
            parts.append(
                f"**Current market price:** YES={dossier.current_price_yes:.2f}, "
                f"NO={dossier.current_price_no:.2f}"
                if dossier.current_price_no is not None
                else f"**Current market price:** YES={dossier.current_price_yes:.2f}"
            )
        parts.append("")

        # Web search results
        if dossier.web_search_results:
            parts.append("## Web Search Results")
            parts.append("")
            for i, result in enumerate(dossier.web_search_results, 1):
                parts.append(f"### {i}. {result.title}")
                parts.append(f"Source: {result.url}")
                parts.append(result.content[:500])
                parts.append("")

        # Comments
        if dossier.polymarket_comments:
            parts.append("## Polymarket Community Comments")
            if dossier.comment_sentiment_summary:
                parts.append(f"**Sentiment:** {dossier.comment_sentiment_summary}")
            parts.append("")
            for comment in dossier.polymarket_comments[:5]:
                parts.append(f"- {comment[:200]}")
            parts.append("")

        # Related markets
        if dossier.related_markets:
            parts.append("## Related Markets")
            for rm in dossier.related_markets:
                price_str = f" (YES={rm['price_yes']:.2f})" if rm.get("price_yes") else ""
                parts.append(f"- {rm['question']}{price_str}")
            parts.append("")

        # Domain data
        if dossier.domain_data:
            parts.append("## Domain-Specific Data")
            for key, value in dossier.domain_data.items():
                parts.append(f"- **{key}:** {value}")
            parts.append("")

        return "\n".join(parts)
