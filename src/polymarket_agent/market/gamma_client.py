"""Gamma API client for market discovery and metadata."""

import logging
import time
from datetime import datetime

import httpx

from polymarket_agent import metrics
from polymarket_agent.config import settings
from polymarket_agent.models import Market

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
MAX_PAGES = 20


class GammaClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.gamma_api_url
        self._client = httpx.Client(base_url=self.base_url, timeout=60.0)

    def close(self):
        self._client.close()

    def fetch_markets(
        self,
        limit: int = BATCH_SIZE,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
        min_volume: float | None = None,
        min_liquidity: float | None = None,
        order: str = "volume",
        ascending: bool = False,
    ) -> list[Market]:
        """Fetch markets from Gamma API with pagination and server-side filtering."""
        params: dict = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "order": order,
            "ascending": str(ascending).lower(),
        }
        if min_volume is not None:
            params["volume_num_min"] = min_volume
        if min_liquidity is not None:
            params["liquidity_num_min"] = min_liquidity

        try:
            t0 = time.monotonic()
            resp = self._client.get("/markets", params=params)
            resp.raise_for_status()
            metrics.record("api_call", service="gamma", endpoint="/markets", status=resp.status_code, latency_ms=int((time.monotonic() - t0) * 1000))
            data = resp.json()
        except httpx.HTTPError as e:
            metrics.record("api_call", service="gamma", endpoint="/markets", status="error")
            metrics.record("api_error", service="gamma", endpoint="/markets", error=str(e))
            logger.error("Gamma API error fetching markets: %s", e)
            return []

        markets = []
        for item in data:
            market = _parse_market(item)
            if market:
                markets.append(market)
        return markets

    def fetch_all_active_markets(
        self,
        min_volume: float | None = None,
        min_liquidity: float | None = None,
    ) -> list[Market]:
        """Fetch active markets with server-side volume/liquidity filtering.

        Defaults to configured minimum volume to avoid fetching 29K+ dead markets.
        """
        vol_filter = min_volume if min_volume is not None else settings.min_volume
        liq_filter = min_liquidity if min_liquidity is not None else settings.min_liquidity

        all_markets: list[Market] = []
        offset = 0
        for _ in range(MAX_PAGES):
            batch = self.fetch_markets(
                limit=BATCH_SIZE,
                offset=offset,
                active=True,
                min_volume=vol_filter,
                min_liquidity=liq_filter,
            )
            if not batch:
                break
            all_markets.extend(batch)
            logger.info("Fetched batch: %d markets (total: %d)", len(batch), len(all_markets))
            if len(batch) < BATCH_SIZE:
                break
            offset += BATCH_SIZE

        logger.info(
            "Fetched %d active markets (vol>=$%.0f, liq>=$%.0f)",
            len(all_markets), vol_filter, liq_filter,
        )
        return all_markets

    def fetch_market_by_id(self, market_id: str) -> Market | None:
        """Fetch a single market by its ID."""
        try:
            t0 = time.monotonic()
            resp = self._client.get(f"/markets/{market_id}")
            resp.raise_for_status()
            metrics.record("api_call", service="gamma", endpoint="/markets/{id}", status=resp.status_code, latency_ms=int((time.monotonic() - t0) * 1000))
            return _parse_market(resp.json())
        except httpx.HTTPError as e:
            metrics.record("api_call", service="gamma", endpoint="/markets/{id}", status="error")
            metrics.record("api_error", service="gamma", endpoint="/markets/{id}", error=str(e))
            logger.error("Gamma API error fetching market %s: %s", market_id, e)
            return None

    def fetch_events(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Fetch events (groups of related markets)."""
        params = {"limit": limit, "offset": offset, "active": "true"}
        try:
            t0 = time.monotonic()
            resp = self._client.get("/events", params=params)
            resp.raise_for_status()
            metrics.record("api_call", service="gamma", endpoint="/events", status=resp.status_code, latency_ms=int((time.monotonic() - t0) * 1000))
            return resp.json()
        except httpx.HTTPError as e:
            metrics.record("api_call", service="gamma", endpoint="/events", status="error")
            metrics.record("api_error", service="gamma", endpoint="/events", error=str(e))
            logger.error("Gamma API error fetching events: %s", e)
            return []

    def fetch_comments(self, market_id: str, limit: int = 20) -> list[dict]:
        """Fetch comments for a market."""
        params = {
            "parent_entity_id": market_id,
            "parent_entity_type": "market",
            "limit": limit,
            "order": "created_at",
            "ascending": "false",
        }
        try:
            t0 = time.monotonic()
            resp = self._client.get("/comments", params=params)
            resp.raise_for_status()
            metrics.record("api_call", service="gamma", endpoint="/comments", status=resp.status_code, latency_ms=int((time.monotonic() - t0) * 1000))
            return resp.json()
        except httpx.HTTPError as e:
            metrics.record("api_call", service="gamma", endpoint="/comments", status="error")
            metrics.record("api_error", service="gamma", endpoint="/comments", error=str(e))
            logger.debug("Comments unavailable for %s: %s", market_id, e)
            return []


def _parse_market(data: dict) -> Market | None:
    """Parse Gamma API market response into Market model."""
    try:
        # Extract token IDs and prices from Gamma API format
        # Gamma returns: clobTokenIds=["token0", "token1"],
        #                outcomes=["Yes", "No"], outcomePrices=["0.55", "0.45"]
        outcomes = data.get("outcomes") or []
        clob_token_ids = data.get("clobTokenIds") or []
        outcome_prices = data.get("outcomePrices") or []

        # Parse as JSON strings if needed (Gamma sometimes returns JSON-encoded arrays)
        import json as _json

        if isinstance(outcomes, str):
            try:
                outcomes = _json.loads(outcomes)
            except (ValueError, TypeError):
                outcomes = []
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = _json.loads(clob_token_ids)
            except (ValueError, TypeError):
                clob_token_ids = []
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = _json.loads(outcome_prices)
            except (ValueError, TypeError):
                outcome_prices = []

        yes_token = None
        no_token = None
        yes_price = None
        no_price = None

        for i, outcome_name in enumerate(outcomes):
            name = str(outcome_name).upper()
            token_id = clob_token_ids[i] if i < len(clob_token_ids) else None
            price_str = outcome_prices[i] if i < len(outcome_prices) else None

            if name == "YES":
                yes_token = token_id
                if price_str is not None:
                    try:
                        yes_price = float(price_str)
                    except (ValueError, TypeError):
                        pass
            elif name == "NO":
                no_token = token_id
                if price_str is not None:
                    try:
                        no_price = float(price_str)
                    except (ValueError, TypeError):
                        pass

        # Fallback: if outcomes aren't Yes/No (e.g. team names), use index 0=Yes, 1=No
        if yes_price is None and len(outcome_prices) >= 2 and not any(
            str(o).upper() in ("YES", "NO") for o in outcomes
        ):
            try:
                yes_price = float(outcome_prices[0])
                no_price = float(outcome_prices[1])
            except (ValueError, TypeError, IndexError):
                pass
            if len(clob_token_ids) >= 2:
                yes_token = yes_token or clob_token_ids[0]
                no_token = no_token or clob_token_ids[1]

        # Parse end date
        end_date = None
        end_date_str = data.get("endDate") or data.get("end_date_iso")
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Determine category from tags or groupItemTitle
        category = None
        tags = data.get("tags", [])
        if tags:
            tag = tags[0]
            category = tag.get("label") if isinstance(tag, dict) else str(tag)
        if not category:
            category = data.get("groupItemTitle") or data.get("category")

        return Market(
            id=str(data.get("id", data.get("condition_id", ""))),
            condition_id=data.get("condition_id") or data.get("conditionId"),
            question=data.get("question", ""),
            description=data.get("description"),
            category=category,
            end_date=end_date,
            outcome_yes_token=yes_token,
            outcome_no_token=no_token,
            volume=float(data.get("volumeNum") or data.get("volume", 0) or 0),
            liquidity=float(data.get("liquidity", 0) or 0),
            last_price_yes=yes_price,
            last_price_no=no_price,
            active=data.get("active", True),
            resolved=data.get("closed", False),
            resolution_outcome=data.get("resolutionSource"),
            first_seen_at=datetime.utcnow(),
            last_updated_at=datetime.utcnow(),
            event_id=data.get("events", [{}])[0].get("id") if data.get("events") else None,
            event_title=data.get("events", [{}])[0].get("title") if data.get("events") else None,
            maker_base_fee=float(data.get("maker_base_fee") or data.get("makerBaseFee") or 0),
            taker_base_fee=float(data.get("taker_base_fee") or data.get("takerBaseFee") or 0),
        )
    except Exception as e:
        logger.warning("Failed to parse market: %s - %s", data.get("id", "unknown"), e)
        return None
