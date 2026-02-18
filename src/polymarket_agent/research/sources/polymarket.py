"""Polymarket-specific research: comments and related markets."""

import logging

from polymarket_agent.market.gamma_client import GammaClient

logger = logging.getLogger(__name__)


class PolymarketResearch:
    def __init__(self, gamma_client: GammaClient | None = None):
        self.gamma = gamma_client or GammaClient()

    def fetch_comments(self, market_id: str, limit: int = 20) -> list[str]:
        """Fetch comment text for a market."""
        raw = self.gamma.fetch_comments(market_id, limit=limit)
        comments = []
        for item in raw:
            text = item.get("content") or item.get("body") or item.get("text")
            if text:
                comments.append(text.strip())
        return comments

    def summarize_sentiment(self, comments: list[str]) -> str | None:
        """Basic sentiment summary from comments (simple heuristic)."""
        if not comments:
            return None

        bullish_words = {"yes", "likely", "bullish", "confident", "win", "pass", "approve", "up"}
        bearish_words = {"no", "unlikely", "bearish", "doubt", "lose", "fail", "reject", "down"}

        bullish = 0
        bearish = 0
        for comment in comments:
            words = set(comment.lower().split())
            bullish += len(words & bullish_words)
            bearish += len(words & bearish_words)

        total = bullish + bearish
        if total == 0:
            return f"{len(comments)} comments, no clear directional lean"

        bull_pct = bullish / total * 100
        if bull_pct > 65:
            return f"{len(comments)} comments, leaning YES ({bull_pct:.0f}% bullish keywords)"
        elif bull_pct < 35:
            return f"{len(comments)} comments, leaning NO ({100-bull_pct:.0f}% bearish keywords)"
        else:
            return f"{len(comments)} comments, mixed sentiment ({bull_pct:.0f}% bullish)"

    def find_related_markets(
        self, event_id: str | None, current_market_id: str
    ) -> list[dict]:
        """Find related markets within the same event."""
        if not event_id:
            return []

        events = self.gamma.fetch_events(limit=100)
        for event in events:
            if str(event.get("id")) == str(event_id):
                related = []
                for market in event.get("markets", []):
                    mid = str(market.get("id", ""))
                    if mid != current_market_id:
                        # Extract YES price
                        price = None
                        for token in market.get("tokens", []):
                            if token.get("outcome", "").upper() == "YES":
                                price = token.get("price")
                        related.append(
                            {
                                "id": mid,
                                "question": market.get("question", ""),
                                "price_yes": float(price) if price else None,
                            }
                        )
                return related
        return []
