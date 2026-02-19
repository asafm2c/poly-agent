"""Historical data collector: fetches resolved markets and price histories."""

import json
import logging
import time
from datetime import datetime, timezone

import httpx

from polymarket_agent.backtest.database import get_backtest_db, init_backtest_db
from polymarket_agent.config import settings

logger = logging.getLogger(__name__)

GAMMA_BATCH_SIZE = 500
MAX_BACKOFF = 60


class BacktestCollector:
    """Collects resolved markets and daily price histories into the backtest DB."""

    def __init__(self, db_path=None):
        self.db_path = db_path or settings.backtest_db_path
        self._gamma = httpx.Client(base_url=settings.gamma_api_url, timeout=60.0)
        self._clob = httpx.Client(base_url=settings.clob_api_url, timeout=30.0)
        init_backtest_db(self.db_path)

    def close(self):
        self._gamma.close()
        self._clob.close()

    def collect(self) -> dict:
        """Run full collection: markets then price histories.

        Returns summary dict with counts.
        """
        markets_collected = self._collect_markets()
        history_collected, history_skipped = self._collect_price_histories()
        return {
            "markets_collected": markets_collected,
            "history_collected": history_collected,
            "history_skipped": history_skipped,
        }

    def collect_histories_only(self, min_volume: float | None = None) -> tuple[int, int]:
        """Run only price history collection, optionally filtered by volume.

        Returns (collected, skipped) counts.
        """
        return self._collect_price_histories(min_volume=min_volume)

    def _collect_markets(self) -> int:
        """Paginate Gamma API for all resolved markets, upsert into bt_markets."""
        offset = 0
        total = 0

        while True:
            params = {
                "limit": GAMMA_BATCH_SIZE,
                "offset": offset,
                "closed": "true",
                "order": "volumeNum",
                "ascending": "false",
                "volume_num_min": 10000,
            }

            data = self._gamma_request("/markets", params)
            if not data:
                break

            batch_count = 0
            with get_backtest_db(self.db_path) as conn:
                for item in data:
                    if self._upsert_market(conn, item):
                        batch_count += 1

            total += batch_count
            offset += GAMMA_BATCH_SIZE

            if total % 500 == 0 or len(data) < GAMMA_BATCH_SIZE:
                logger.info("Markets collected: %d (offset=%d)", total, offset)

            if len(data) < GAMMA_BATCH_SIZE:
                break

        logger.info("Market collection complete: %d markets", total)
        return total

    def _upsert_market(self, conn, item: dict) -> bool:
        """Parse and upsert a single market. Returns True on success."""
        market_id = str(item.get("id", item.get("condition_id", "")))
        if not market_id:
            return False

        # Parse token IDs
        clob_token_ids = item.get("clobTokenIds") or []
        outcomes = item.get("outcomes") or []
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except (ValueError, TypeError):
                clob_token_ids = []
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except (ValueError, TypeError):
                outcomes = []

        yes_token = None
        no_token = None
        for i, outcome_name in enumerate(outcomes):
            token_id = clob_token_ids[i] if i < len(clob_token_ids) else None
            name = str(outcome_name).upper()
            if name == "YES":
                yes_token = token_id
            elif name == "NO":
                no_token = token_id

        # Fallback: if no YES/NO labels, use positional
        if yes_token is None and len(clob_token_ids) >= 1:
            yes_token = clob_token_ids[0]
        if no_token is None and len(clob_token_ids) >= 2:
            no_token = clob_token_ids[1]

        # Parse category
        category = None
        tags = item.get("tags", [])
        if tags:
            tag = tags[0]
            category = tag.get("label") if isinstance(tag, dict) else str(tag)
        if not category:
            category = item.get("groupItemTitle") or item.get("category")

        # Parse event_id
        events = item.get("events") or []
        event_id = events[0].get("id") if events and isinstance(events[0], dict) else None

        # Resolution outcome: derive from outcomePrices (["1", "0"] = YES, ["0", "1"] = NO)
        resolution = ""
        outcome_prices = item.get("outcomePrices") or []
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except (ValueError, TypeError):
                outcome_prices = []
        if outcome_prices:
            try:
                yes_price = float(outcome_prices[0]) if outcome_prices else None
                if yes_price is not None:
                    if yes_price >= 0.99:
                        resolution = "YES"
                    elif yes_price <= 0.01:
                        resolution = "NO"
            except (ValueError, TypeError, IndexError):
                pass

        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """INSERT INTO bt_markets (id, question, description, category, end_date,
                volume, liquidity, resolution_outcome, yes_token, no_token,
                has_history, collected_at, event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                question = excluded.question,
                description = excluded.description,
                category = excluded.category,
                end_date = excluded.end_date,
                volume = excluded.volume,
                liquidity = excluded.liquidity,
                resolution_outcome = excluded.resolution_outcome,
                yes_token = excluded.yes_token,
                no_token = excluded.no_token,
                event_id = excluded.event_id""",
            (
                market_id,
                item.get("question", ""),
                item.get("description"),
                category,
                item.get("endDate") or item.get("end_date_iso"),
                float(item.get("volumeNum") or item.get("volume", 0) or 0),
                float(item.get("liquidity", 0) or 0),
                resolution,
                yes_token,
                no_token,
                now,
                event_id,
            ),
        )
        return True

    def _collect_price_histories(self, min_volume: float | None = None) -> tuple[int, int]:
        """Fetch daily price histories for markets missing them.

        Returns (collected, skipped) counts.
        """
        query = """SELECT id, yes_token FROM bt_markets
                WHERE has_history = 0 AND yes_token IS NOT NULL"""
        params: list = []
        if min_volume is not None:
            query += " AND volume >= ?"
            params.append(min_volume)
        query += " ORDER BY volume DESC"

        with get_backtest_db(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        total = len(rows)
        collected = 0
        skipped = 0
        no_token_count = 0

        for i, row in enumerate(rows):
            market_id = row["id"]
            token_id = row["yes_token"]

            if not token_id:
                no_token_count += 1
                with get_backtest_db(self.db_path) as conn:
                    conn.execute(
                        "UPDATE bt_markets SET has_history = -1 WHERE id = ?",
                        (market_id,),
                    )
                skipped += 1
                continue

            history = self._fetch_price_history(token_id)

            if history is None:
                # API error — skip but don't flag, try again later
                skipped += 1
                continue

            if not history:
                # Empty response — flag as no history available
                with get_backtest_db(self.db_path) as conn:
                    conn.execute(
                        "UPDATE bt_markets SET has_history = -1 WHERE id = ?",
                        (market_id,),
                    )
                skipped += 1
                continue

            # Insert price history
            with get_backtest_db(self.db_path) as conn:
                conn.executemany(
                    """INSERT OR IGNORE INTO bt_price_history (market_id, timestamp, price)
                    VALUES (?, ?, ?)""",
                    [(market_id, int(h["t"]), float(h["p"])) for h in history],
                )
                conn.execute(
                    "UPDATE bt_markets SET has_history = 1 WHERE id = ?",
                    (market_id,),
                )
            collected += 1

            processed = collected + skipped
            if processed % 100 == 0 or processed <= 10:
                logger.info(
                    "Price history: %d collected, %d skipped, %d/%d processed",
                    collected, skipped, processed, total,
                )

        logger.info(
            "Price history collection complete: %d collected, %d skipped, %d no tokens",
            collected, skipped, no_token_count,
        )
        return collected, skipped

    def _fetch_price_history(self, token_id: str) -> list[dict] | None:
        """Fetch daily price history from CLOB API with backoff on 429."""
        params = {
            "market": token_id,
            "interval": "max",
            "fidelity": 1440,
        }

        backoff = 1.0
        while True:
            try:
                resp = self._clob.get("/prices-history", params=params)
                if resp.status_code == 429:
                    logger.warning("Rate limited, backing off %.1fs", backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                    continue
                resp.raise_for_status()
                return resp.json().get("history", [])
            except httpx.HTTPError as e:
                logger.error("CLOB history error for %s: %s", token_id[:16], e)
                return None

    def _gamma_request(self, endpoint: str, params: dict) -> list | None:
        """Make a Gamma API request with backoff on 429."""
        backoff = 1.0
        while True:
            try:
                resp = self._gamma.get(endpoint, params=params)
                if resp.status_code == 429:
                    logger.warning("Gamma rate limited, backing off %.1fs", backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                logger.error("Gamma API error: %s", e)
                return None
