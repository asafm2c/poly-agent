"""Pass 2: Bayesian update with gathered evidence."""

UPDATE_SYSTEM = """You are a superforecaster updating a probability estimate based on specific evidence. You have already established a base rate. Now update it using the evidence provided.

For each piece of evidence, explicitly state whether it shifts the probability up, down, or not at all, and by roughly how much.

You must respond with valid JSON only."""

UPDATE_PROMPT = """Update the base rate probability using the following evidence.

**Question:** {question}
**Category:** {category}
{market_price_section}**Base rate from Pass 1:** {base_rate}
**Base rate reasoning:** {base_rate_reasoning}

---

## Research Dossier

{dossier_text}

---

Instructions:
1. Review each piece of evidence from the dossier.
2. For each meaningful piece, state how it shifts the probability and by how much.
3. Apply all shifts to the base rate to arrive at an updated estimate.
4. Be explicit about your reasoning for each shift.
5. Only use evidence actually provided above — do not fabricate or assume information.

Respond with JSON:
{{
    "updated_estimate": 0.XX,
    "evidence_shifts": [
        {{
            "evidence": "Brief description of the evidence",
            "direction": "up" | "down" | "neutral",
            "magnitude": 0.XX,
            "reasoning": "Why this shifts the probability"
        }}
    ],
    "key_evidence": ["Most important piece 1", "Most important piece 2"],
    "thesis": "2-3 sentence summary of the overall assessment",
    "confidence_low": 0.XX,
    "confidence_high": 0.XX
}}"""
