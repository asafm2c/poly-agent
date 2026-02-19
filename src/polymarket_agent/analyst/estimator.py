"""Probability estimation pipeline: screening → 3-pass analysis."""

import logging
from datetime import datetime

from polymarket_agent.analyst.llm_client import LLMClient
from polymarket_agent.analyst.prompts.base_rate import BASE_RATE_PROMPT, BASE_RATE_SYSTEM
from polymarket_agent.analyst.prompts.calibration import (
    CALIBRATION_PROMPT,
    CALIBRATION_SYSTEM,
    NO_CALIBRATION_TEXT,
)
from polymarket_agent.analyst.prompts.screening import SCREENING_PROMPT, SCREENING_SYSTEM
from polymarket_agent.analyst.prompts.update import UPDATE_PROMPT, UPDATE_SYSTEM
from polymarket_agent.config import settings
from polymarket_agent.models import Market, ProbabilityEstimate, ResearchDossier
from polymarket_agent.research.gatherer import ResearchGatherer

logger = logging.getLogger(__name__)


class ProbabilityEstimator:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        research_gatherer: ResearchGatherer | None = None,
    ):
        self.llm = llm_client or LLMClient()
        self.research = research_gatherer or ResearchGatherer()

    def screen(self, market: Market) -> dict:
        """Quick screen with Haiku to determine if a market is worth deep analysis.

        Returns dict with keys: worth_analyzing, reasoning, initial_direction, confidence.
        """
        prompt = SCREENING_PROMPT.format(
            question=market.question,
            category=market.category or "Unknown",
            price_yes=f"{market.last_price_yes:.2f}" if market.last_price_yes else "N/A",
            implied_prob=f"{market.last_price_yes * 100:.0f}" if market.last_price_yes else "N/A",
            end_date=market.end_date.strftime("%Y-%m-%d") if market.end_date else "Unknown",
            volume=market.volume,
            description=(market.description or "")[:300],
        )

        try:
            result = self.llm.complete_json(
                prompt=prompt,
                system=SCREENING_SYSTEM,
                model=settings.screening_model,
                max_tokens=256,
            )
            worth = result.get("worth_analyzing", False)
            reasoning = result.get("reasoning", "")
            direction = result.get("initial_direction", "fair")
            confidence = result.get("confidence", "low")
            logger.info(
                "Screen %s: %s (%s/%s) - %s",
                market.id[:8],
                "PASS" if worth else "SKIP",
                direction,
                confidence,
                reasoning[:80],
            )
            return {
                "worth_analyzing": worth,
                "reasoning": reasoning,
                "initial_direction": direction,
                "confidence": confidence,
            }
        except Exception as e:
            logger.warning("Screening failed for %s: %s", market.id, e)
            return {
                "worth_analyzing": False,
                "reasoning": f"Screening failed: {e}",
                "initial_direction": "fair",
                "confidence": "low",
            }

    def estimate(
        self, market: Market, calibration_text: str | None = None
    ) -> ProbabilityEstimate:
        """Run full three-pass estimation on a market."""
        # Gather research
        dossier = self.research.gather(market)
        dossier_text = self.research.format_dossier_for_llm(dossier)

        # Pass 1: Base rate
        base_rate_result = self._pass1_base_rate(market)
        base_rate = base_rate_result.get("base_rate", 0.5)
        base_reasoning = base_rate_result.get("reasoning", "No reasoning provided")

        # Pass 2: Bayesian update
        update_result = self._pass2_update(market, base_rate, base_reasoning, dossier_text)
        updated_estimate = update_result.get("updated_estimate", base_rate)
        key_evidence = update_result.get("key_evidence", [])
        thesis = update_result.get("thesis", "")
        conf_low = update_result.get("confidence_low", max(0, updated_estimate - 0.15))
        conf_high = update_result.get("confidence_high", min(1, updated_estimate + 0.15))

        # Pass 3: Calibration adjustment
        cal_text = calibration_text or NO_CALIBRATION_TEXT
        cal_result = self._pass3_calibration(
            market, updated_estimate, conf_low, conf_high, cal_text
        )
        final_estimate = cal_result.get("final_estimate", updated_estimate)
        final_conf_low = cal_result.get("confidence_low", conf_low)
        final_conf_high = cal_result.get("confidence_high", conf_high)
        pass3_reasoning = cal_result.get("adjustment_reasoning")

        # Clamp to [0.01, 0.99]
        final_estimate = max(0.01, min(0.99, final_estimate))

        return ProbabilityEstimate(
            market_id=market.id,
            final_estimate=final_estimate,
            confidence_low=final_conf_low,
            confidence_high=final_conf_high,
            base_rate=base_rate,
            updated_estimate=updated_estimate,
            pass1_reasoning=base_reasoning,
            pass2_reasoning=update_result.get("thesis", ""),
            pass3_reasoning=pass3_reasoning,
            key_evidence=key_evidence,
            thesis=thesis,
            timestamp=datetime.utcnow(),
        )

    def _pass1_base_rate(self, market: Market) -> dict:
        prompt = BASE_RATE_PROMPT.format(
            question=market.question,
            category=market.category or "Unknown",
            end_date=market.end_date.strftime("%Y-%m-%d") if market.end_date else "Unknown",
        )
        try:
            return self.llm.complete_json(
                prompt=prompt, system=BASE_RATE_SYSTEM, max_tokens=512
            )
        except Exception as e:
            logger.error("Pass 1 failed for %s: %s", market.id, e)
            return {"base_rate": 0.5, "reasoning": f"Base rate estimation failed: {e}"}

    def _pass2_update(
        self, market: Market, base_rate: float, base_reasoning: str, dossier_text: str
    ) -> dict:
        prompt = UPDATE_PROMPT.format(
            question=market.question,
            category=market.category or "Unknown",
            market_price=f"{market.last_price_yes:.2f}" if market.last_price_yes else "N/A",
            base_rate=f"{base_rate:.2f}",
            base_rate_reasoning=base_reasoning,
            dossier_text=dossier_text,
        )
        try:
            return self.llm.complete_json(
                prompt=prompt, system=UPDATE_SYSTEM, max_tokens=1024
            )
        except Exception as e:
            logger.error("Pass 2 failed for %s: %s", market.id, e)
            return {
                "updated_estimate": base_rate,
                "thesis": f"Evidence update failed: {e}",
                "key_evidence": [],
            }

    def _pass3_calibration(
        self,
        market: Market,
        estimate: float,
        conf_low: float,
        conf_high: float,
        calibration_text: str,
    ) -> dict:
        prompt = CALIBRATION_PROMPT.format(
            question=market.question,
            category=market.category or "Unknown",
            estimate=f"{estimate:.2f}",
            confidence_low=f"{conf_low:.2f}",
            confidence_high=f"{conf_high:.2f}",
            calibration_text=calibration_text,
        )
        try:
            return self.llm.complete_json(
                prompt=prompt, system=CALIBRATION_SYSTEM, max_tokens=512
            )
        except Exception as e:
            logger.error("Pass 3 failed for %s: %s", market.id, e)
            return {
                "final_estimate": estimate,
                "adjusted": False,
                "adjustment_reasoning": f"Calibration failed: {e}",
                "confidence_low": conf_low,
                "confidence_high": conf_high,
            }
