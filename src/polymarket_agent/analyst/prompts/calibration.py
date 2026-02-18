"""Pass 3: Calibration adjustment based on historical accuracy."""

CALIBRATION_SYSTEM = """You are a metacognitive analyst reviewing a probability estimate for potential calibration bias. You have data on how well your previous estimates have matched reality.

Your job is to adjust the estimate if the calibration data suggests systematic bias (e.g., overconfidence, underconfidence in certain ranges or categories).

You must respond with valid JSON only."""

CALIBRATION_PROMPT = """Review and optionally adjust this probability estimate based on calibration data.

**Question:** {question}
**Category:** {category}
**Current estimate (from Pass 2):** {estimate}
**Confidence band:** [{confidence_low}, {confidence_high}]

## Historical Calibration Data

{calibration_text}

---

Instructions:
1. Review the calibration data for any systematic biases.
2. Pay special attention to biases in:
   - This probability range (e.g., are you overconfident when saying 70-80%?)
   - This category (e.g., are you worse at political predictions?)
3. Adjust the estimate if warranted. If no adjustment needed, return the same estimate.
4. Explain your reasoning.

Respond with JSON:
{{
    "final_estimate": 0.XX,
    "adjusted": true/false,
    "adjustment_reasoning": "Why you did or didn't adjust",
    "confidence_low": 0.XX,
    "confidence_high": 0.XX
}}"""

NO_CALIBRATION_TEXT = """Insufficient calibration data available (fewer than 20 resolved predictions).
No calibration adjustment can be made at this time. Return the estimate unchanged."""
