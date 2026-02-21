"""Claude API wrapper with cost tracking and error handling."""

import json
import logging
import random
import threading
import time

from anthropic import Anthropic, APIError, RateLimitError

from polymarket_agent import metrics
from polymarket_agent.config import settings

logger = logging.getLogger(__name__)

# Approximate costs per million tokens (as of 2025)
MODEL_COSTS = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}


class LLMClient:
    def __init__(self, api_key: str | None = None):
        key = api_key or settings.anthropic_api_key
        if not key:
            raise ValueError("Anthropic API key not configured")
        self._client = Anthropic(api_key=key)
        self._lock = threading.Lock()
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
        retries: int | None = None,
    ) -> str:
        """Send a prompt to Claude and return the response text."""
        model = model or settings.analysis_model
        max_retries = retries if retries is not None else settings.llm_max_retries
        messages = [{"role": "user", "content": prompt}]

        for attempt in range(max_retries + 1):
            try:
                kwargs = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": messages,
                    "temperature": temperature,
                }
                if system:
                    kwargs["system"] = system

                t0 = time.monotonic()
                response = self._client.messages.create(**kwargs)
                latency_ms = int((time.monotonic() - t0) * 1000)

                # Track usage (thread-safe)
                usage = response.usage
                cost = self._estimate_cost(model, usage.input_tokens, usage.output_tokens)
                with self._lock:
                    self.total_input_tokens += usage.input_tokens
                    self.total_output_tokens += usage.output_tokens
                    self.call_count += 1
                    self.total_cost += cost

                text = response.content[0].text
                logger.debug(
                    "LLM call (%s): %d in / %d out tokens, ~$%.4f",
                    model,
                    usage.input_tokens,
                    usage.output_tokens,
                    cost,
                )
                metrics.record(
                    "llm_call", model=model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cost=round(cost, 6), latency_ms=latency_ms,
                )
                return text

            except RateLimitError:
                metrics.record("api_error", service="anthropic", error="rate_limit", model=model)
                if attempt < max_retries:
                    wait = self._backoff_wait(attempt)
                    logger.warning("Rate limited, waiting %.1fs before retry (attempt %d/%d)", wait, attempt + 1, max_retries)
                    time.sleep(wait)
                else:
                    raise
            except APIError as e:
                metrics.record("api_error", service="anthropic", error=str(e.status_code), model=model)
                is_overloaded = hasattr(e, "type") and e.type == "overloaded_error"
                is_server_error = e.status_code is not None and e.status_code >= 500
                should_retry = is_server_error or (is_overloaded and settings.llm_retry_on_overloaded)
                if attempt < max_retries and should_retry:
                    wait = self._backoff_wait(attempt)
                    logger.warning("API error %s, retrying in %.1fs (attempt %d/%d)", e.status_code, wait, attempt + 1, max_retries)
                    time.sleep(wait)
                else:
                    raise

    @staticmethod
    def _backoff_wait(attempt: int) -> float:
        """Exponential backoff with full jitter: min(60, base * 2^attempt) * uniform(0.5, 1.5)."""
        base = settings.llm_retry_base_delay
        cap = 60.0
        wait = min(cap, base * (2 ** attempt)) * random.uniform(0.5, 1.5)
        return wait

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

        result = self._extract_json(text)
        if result is not None:
            return result

        # Retry once with explicit JSON instruction
        logger.warning("JSON parse failed, retrying with explicit instruction")
        retry_text = self.complete(
            prompt=prompt + "\n\nIMPORTANT: Respond with ONLY a valid JSON object. No other text.",
            model=model,
            system=system,
            max_tokens=max_tokens,
            temperature=0.0,
        )

        result = self._extract_json(retry_text)
        if result is not None:
            return result

        raise json.JSONDecodeError(
            "Failed to extract JSON after retry",
            retry_text[:200], 0,
        )

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Extract a JSON object from text, handling code fences and surrounding prose."""
        text = text.strip()

        # Strip markdown code fences
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.strip() == "```" and in_block:
                    in_block = False
                    continue
                elif in_block:
                    json_lines.append(line)
            if json_lines:
                text = "\n".join(json_lines)

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Find first { and last } to extract embedded JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        return None

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        costs = MODEL_COSTS.get(model, {"input": 3.0, "output": 15.0})
        return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

    def get_usage_summary(self) -> dict:
        with self._lock:
            return {
                "calls": self.call_count,
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
                "estimated_cost": round(self.total_cost, 4),
            }
