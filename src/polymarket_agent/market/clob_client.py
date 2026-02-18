"""CLOB API client for prices, order books, and price history."""

import logging

import httpx

from polymarket_agent.config import settings

logger = logging.getLogger(__name__)


class ClobClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.clob_api_url
        self._client = httpx.Client(base_url=self.base_url, timeout=30.0)

    def close(self):
        self._client.close()

    def get_price(self, token_id: str) -> float | None:
        """Get current price for a token."""
        try:
            resp = self._client.get("/price", params={"token_id": token_id})
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("price", 0))
        except (httpx.HTTPError, ValueError, KeyError) as e:
            logger.error("CLOB price error for %s: %s", token_id, e)
            return None

    def get_midpoint(self, token_id: str) -> float | None:
        """Get midpoint price for a token."""
        try:
            resp = self._client.get("/midpoint", params={"token_id": token_id})
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("mid", 0))
        except (httpx.HTTPError, ValueError, KeyError) as e:
            logger.error("CLOB midpoint error for %s: %s", token_id, e)
            return None

    def get_order_book(self, token_id: str) -> dict | None:
        """Get order book for a token. Returns {bids: [...], asks: [...]}."""
        try:
            resp = self._client.get("/book", params={"token_id": token_id})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error("CLOB book error for %s: %s", token_id, e)
            return None

    def get_prices_history(
        self,
        token_id: str,
        interval: str = "max",
        fidelity: int = 60,
    ) -> list[dict] | None:
        """Get price history for a token.

        Args:
            token_id: The token to query.
            interval: Time range - "1d", "1w", "1m", "max".
            fidelity: Granularity in minutes.
        """
        params = {
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        }
        try:
            resp = self._client.get("/prices-history", params=params)
            resp.raise_for_status()
            return resp.json().get("history", [])
        except httpx.HTTPError as e:
            logger.error("CLOB history error for %s: %s", token_id, e)
            return None

    def get_order_book_depth(self, token_id: str, price: float, side: str = "buy") -> float:
        """Calculate available liquidity at a given price level.

        Returns the total size available at or better than the given price.
        """
        book = self.get_order_book(token_id)
        if not book:
            return 0.0

        total = 0.0
        if side == "buy":
            # We're buying, so we hit asks
            for ask in book.get("asks", []):
                ask_price = float(ask.get("price", 0))
                if ask_price <= price:
                    total += float(ask.get("size", 0))
        else:
            # We're selling, so we hit bids
            for bid in book.get("bids", []):
                bid_price = float(bid.get("price", 0))
                if bid_price >= price:
                    total += float(bid.get("size", 0))
        return total
