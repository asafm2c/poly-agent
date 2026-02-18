"""Haiku screening prompt: quick assessment of mispricing potential."""

SCREENING_SYSTEM = """You are a prediction market analyst. Your job is to quickly assess whether a market might be mispriced — meaning the current price does not reflect the true probability of the outcome.

You must respond with valid JSON only. No explanation outside the JSON."""

SCREENING_PROMPT = """Assess this Polymarket market for potential mispricing:

**Question:** {question}
**Category:** {category}
**Current YES price:** {price_yes} (implies {implied_prob}% probability)
**Resolution date:** {end_date}
**Volume:** ${volume:,.0f}
**Description:** {description}

Consider:
1. Does the current price seem reasonable given what you know?
2. Is there likely publicly available information that could shift this probability?
3. Is this a domain where research could reveal an informational edge?

Respond with JSON:
{{
    "worth_analyzing": true/false,
    "reasoning": "Brief 1-2 sentence explanation",
    "initial_direction": "higher" | "lower" | "fair",
    "confidence": "low" | "medium" | "high"
}}"""
