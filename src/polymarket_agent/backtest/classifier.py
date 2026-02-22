"""Market classifiers for backtest data.

Rule-based market_type classifier (deterministic):
  Priority order (first match wins):
  1. tick          — question contains "Up or Down"
  2. sports        — category in SPORTS_CATEGORIES or starts with SPORTS_CATEGORY_PREFIXES
                     OR question contains " vs."
  3. economic-range — category matches ^\\d[\\d,.\\- ]*$ (numeric bucket)
  4. prediction    — everything else
  5. unknown       — defensive fallback (should not occur with rules above)

LLM-based domain_type classifier (Haiku):
  Classifies prediction questions by information source:
  - actuarial     — historical base rates / statistical frequency drive the outcome
  - current_event — requires specific post-training knowledge
  - mixed         — both apply
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polymarket_agent.analyst.llm_client import LLMClient

logger = logging.getLogger(__name__)

# Exact-match sports categories
SPORTS_CATEGORIES: frozenset[str] = frozenset(
    {
        "Match Winner",
        "Game 1 Winner",
        "Game 2 Winner",
        "Game 3 Winner",
        "Map 1 Winner",
        "Map 2 Winner",
        "Map 3 Winner",
        "Both Teams to Score",
    }
)

# Prefix-match sports categories (e.g. "Spread -3.5", "O/U 47.5")
SPORTS_CATEGORY_PREFIXES: tuple[str, ...] = ("Spread", "O/U")

# Regex for economic-range categories: starts with digit, only digits/commas/periods/hyphens/spaces
_ECONOMIC_RANGE_RE = re.compile(r"^\d[\d,.\- ]*$")


def classify_market_type(question: str, category: str | None) -> str:
    """Classify a market into one of: tick, sports, economic-range, prediction, unknown.

    Args:
        question: The market question text.
        category: The market category tag, or None.

    Returns:
        One of 'tick', 'sports', 'economic-range', 'prediction', 'unknown'.
    """
    # 1. Tick markets — "Up or Down" in question (case-sensitive per spec)
    if "Up or Down" in question:
        return "tick"

    # 2. Sports — by category (exact or prefix match)
    if category is not None:
        if category in SPORTS_CATEGORIES:
            return "sports"
        if category.startswith(SPORTS_CATEGORY_PREFIXES):
            return "sports"

    # 2b. Sports — by "vs" pattern in question (catches null-category sports)
    # Match both "Alice vs. Bob" (with period) and "Alice vs Bob" (no period)
    if " vs." in question or " vs " in question:
        return "sports"

    # 3. Economic-range — category is a numeric bucket (e.g. "88,000-90,000")
    if category is not None and _ECONOMIC_RANGE_RE.match(category):
        return "economic-range"

    # 4. Prediction — default for everything else
    return "prediction"


# ---------------------------------------------------------------------------
# LLM-based domain type classifier
# ---------------------------------------------------------------------------

VALID_DOMAIN_TYPES = frozenset({"actuarial", "current_event", "mixed"})

_DOMAIN_SYSTEM = """\
You classify prediction market questions for a trading research system.

Three domain types:
- actuarial: outcome mainly driven by historical base rates / statistical frequency.
  Examples: earthquake probability, recession likelihood, recurring natural events,
  annual event rates, base-rate-driven forecasts.
- current_event: outcome requires specific post-training-cutoff knowledge —
  specific legislation passed, a person's decision, a company action, news outcomes.
- mixed: both historical patterns AND recent-event knowledge materially influence the outcome.

Respond with JSON only: {"domain_type": "actuarial"|"current_event"|"mixed"}"""


def classify_domain_type(question: str, llm: LLMClient) -> str:
    """Classify a prediction market question by its primary information source.

    Args:
        question: The market question text.
        llm: An LLMClient instance (will use Haiku via settings.screening_model).

    Returns:
        One of 'actuarial', 'current_event', 'mixed'. Falls back to 'mixed' on error.
    """
    from polymarket_agent.config import settings

    try:
        result = llm.complete_json(
            prompt=f"Classify: {question}",
            system=_DOMAIN_SYSTEM,
            model=settings.screening_model,
            max_tokens=64,
            temperature=0.0,
        )
        domain = result.get("domain_type", "mixed")
        if domain not in VALID_DOMAIN_TYPES:
            logger.warning("Unexpected domain_type %r for %r, defaulting to mixed", domain, question[:60])
            return "mixed"
        return domain
    except Exception as e:
        logger.warning("classify_domain_type failed for %r: %s", question[:60], e)
        return "mixed"
