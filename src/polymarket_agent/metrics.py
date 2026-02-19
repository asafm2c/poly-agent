"""Lightweight operational metrics recorder.

Persists individual metric events to the metric_events table.
All writes are fire-and-forget — errors are logged but never propagate.
"""

import json
import logging
from datetime import datetime, timedelta

from polymarket_agent.storage.database import get_db

logger = logging.getLogger(__name__)


def record(event_type: str, **data) -> None:
    """Record a single metric event. Never raises."""
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO metric_events (timestamp, event_type, data) VALUES (?, ?, ?)",
                (datetime.utcnow().isoformat(), event_type, json.dumps(data)),
            )
    except Exception:
        logger.debug("Failed to record metric event %s", event_type, exc_info=True)


def cleanup_old_metrics(retention_days: int = 30) -> int:
    """Delete metric events older than retention window. Returns count deleted."""
    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
    try:
        with get_db() as conn:
            cursor = conn.execute(
                "DELETE FROM metric_events WHERE timestamp < ?", (cutoff,)
            )
            deleted = cursor.rowcount
            if deleted:
                logger.info("Cleaned up %d old metric events", deleted)
            return deleted
    except Exception:
        logger.debug("Failed to clean up metric events", exc_info=True)
        return 0
