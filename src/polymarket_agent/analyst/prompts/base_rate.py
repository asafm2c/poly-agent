"""Pass 1: Base rate estimation via reference class forecasting."""

BASE_RATE_SYSTEM = """You are a superforecaster specializing in reference class forecasting. Your task is to establish a base rate probability BEFORE considering any specific evidence about this particular market.

Think about what reference class this event belongs to and what historical base rates exist for similar events.

You must respond with valid JSON only."""

BASE_RATE_PROMPT = """Establish a base rate probability for this prediction market:

**Question:** {question}
**Category:** {category}
**Resolution date:** {end_date}

Step 1: Identify the reference class. What type of event is this? What broader category does it fall into?
Step 2: Estimate the historical base rate. For events of this type, how often does the YES outcome occur?
Step 3: If no clear reference class exists, default to 0.50 and explain why.

Respond with JSON:
{{
    "reference_class": "Description of the reference class used",
    "base_rate": 0.XX,
    "reasoning": "2-3 sentences explaining the base rate derivation",
    "confidence_in_base_rate": "low" | "medium" | "high"
}}"""
