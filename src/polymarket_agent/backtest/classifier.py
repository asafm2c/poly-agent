"""Deterministic rule-based classifier for backtest market types.

Priority order (first match wins):
  1. tick          — question contains "Up or Down"
  2. sports        — category in SPORTS_CATEGORIES or starts with SPORTS_CATEGORY_PREFIXES
                     OR question contains " vs."
  3. economic-range — category matches ^\\d[\\d,.\\- ]*$ (numeric bucket)
  4. prediction    — everything else
  5. unknown       — defensive fallback (should not occur with rules above)
"""

import re

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
