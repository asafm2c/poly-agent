"""Claude API wrapper with cost tracking and error handling."""

import json
import logging
import time

from anthropic import Anthropic, APIError, RateLimitError

from polymarket_agent.config import settings

logger = logging.getLogger(__name__)

# Approximate costs per million tokens (as of 2025)
MODEL_COSTS = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}


class LLMClient:
    def __init__(self, api_key: str | None = None):
        key = api_key or settings.anthropic_api_key
        if not key:
            raise ValueError("Anthropic API key not configured")
        self._client = Anthropic(api_key=key)
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.call_count = 0

    def complete(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        retries: int = 2,
    ) -> str:
        """Send a prompt to Claude and return the response text."""
        model = model or settings.analysis_model
        messages = [{"role": "user", "content": prompt}]

        for attempt in range(retries + 1):
            try:
                kwargs = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": messages,
                    "temperature": temperature,
                }
                if system:
                    kwargs["system"] = system

                response = self._client.messages.create(**kwargs)

                # Track usage
                usage = response.usage
                self.total_input_tokens += usage.input_tokens
                self.total_output_tokens += usage.output_tokens
                self.call_count += 1

                cost = self._estimate_cost(model, usage.input_tokens, usage.output_tokens)
                self.total_cost += cost

                text = response.content[0].text
                logger.debug(
                    "LLM call (%s): %d in / %d out tokens, ~$%.4f",
                    model,
                    usage.input_tokens,
                    usage.output_tokens,
                    cost,
                )
                return text

            except RateLimitError:
                if attempt < retries:
                    wait = 2 ** (attempt + 1)
                    logger.warning("Rate limited, waiting %ds before retry", wait)
                    time.sleep(wait)
                else:
                    raise
            except APIError as e:
                if attempt < retries and e.status_code and e.status_code >= 500:
                    wait = 2 ** (attempt + 1)
                    logger.warning("API error %s, retrying in %ds", e.status_code, wait)
                    time.sleep(wait)
                else:
                    raise

    def complete_json(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> dict:
        """Send a prompt and parse the response as JSON."""
        text = self.complete(
            prompt=prompt,
            model=model,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        # Extract JSON from response (handle markdown code blocks)
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.strip() == "```" and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        return json.loads(text)

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        costs = MODEL_COSTS.get(model, {"input": 3.0, "output": 15.0})
        return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

    def get_usage_summary(self) -> dict:
        return {
            "calls": self.call_count,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "estimated_cost": round(self.total_cost, 4),
        }
