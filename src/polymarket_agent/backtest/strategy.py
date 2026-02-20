"""Strategy configuration: load, create, and update strategy.yaml."""

import logging
from datetime import date
from pathlib import Path

import yaml

from polymarket_agent.config import settings

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "version": 1,
    "updated_at": date.today().isoformat(),
    "updated_by": "system (default)",
    "market_selection": {
        "target_categories": [],
        "avoid_categories": [],
        "volume_range": {"min": 5000, "max": None},
        "days_to_resolution": {"min": 1, "max": 60},
    },
    "edge_thresholds": {
        "category_overrides": {},
        "default": 0.10,
        "floor": 0.05,
        "ceiling": 0.25,
    },
    "regime_awareness": {
        "current_regime": "unvalidated",
        "efficiency_trend": "unknown",
        "agent_confidence": "low",
    },
    "insights": [],
}


def load_strategy_config(path: Path | None = None) -> dict:
    """Load strategy.yaml and return as dict. If missing, return defaults."""
    config_path = path or settings.strategy_config_path

    if not config_path.exists():
        logger.info("No strategy config at %s, using defaults", config_path)
        return dict(DEFAULT_CONFIG)

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            logger.warning("Invalid strategy config format, using defaults")
            return dict(DEFAULT_CONFIG)
    except Exception as e:
        logger.error("Failed to load strategy config: %s", e)
        return dict(DEFAULT_CONFIG)

    # Merge hypothesis-driven actions
    try:
        from polymarket_agent.backtest.hypothesis import load_active_hypothesis_actions
        actions = load_active_hypothesis_actions()
        if actions:
            config = _merge_hypothesis_actions(config, actions)
    except Exception as e:
        logger.debug("Hypothesis action merge skipped: %s", e)

    return config


def _merge_hypothesis_actions(config: dict, actions: list[dict]) -> dict:
    """Merge active hypothesis actions into strategy config.

    Does not override user-set values.
    """
    ms = config.setdefault("market_selection", {})
    et = config.setdefault("edge_thresholds", {})
    ha = config.setdefault("hypothesis_actions", [])

    for action in actions:
        atype = action["action_type"]
        cfg = action["config"]
        strength = action["effective_strength"]

        if atype == "category_target":
            targets = ms.setdefault("target_categories", [])
            cat = cfg.get("category")
            if cat and cat not in targets:
                targets.append(cat)

        elif atype == "category_avoid":
            avoids = ms.setdefault("avoid_categories", [])
            cat = cfg.get("category")
            if cat and cat not in avoids:
                avoids.append(cat)

        elif atype == "edge_override":
            overrides = et.setdefault("category_overrides", {})
            applies_to = cfg.get("applies_to", "default")
            base_thresh = cfg.get("base_threshold", 0.10)
            if strength > 0.1:  # Minimum strength to apply
                effective = base_thresh * (1.0 + (1.0 - strength) * 0.5)
                if applies_to not in overrides:  # Don't override user-set values
                    overrides[applies_to] = round(effective, 4)

        # Store all actions for downstream consumers
        ha.append(action)

    return config


def create_default_strategy_config(path: Path | None = None) -> Path:
    """Write a default strategy.yaml with conservative values."""
    config_path = path or settings.strategy_config_path
    config = dict(DEFAULT_CONFIG)
    config["updated_at"] = date.today().isoformat()

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    logger.info("Created default strategy config at %s", config_path)
    return config_path


def update_strategy_config(
    path: Path | None = None,
    *,
    target_categories: list[str] | None = None,
    avoid_categories: list[str] | None = None,
    category_overrides: dict[str, float] | None = None,
    current_regime: str | None = None,
    efficiency_trend: str | None = None,
    agent_confidence: str | None = None,
    insight: str | None = None,
    insight_confidence: str | None = None,
    insight_source: str | None = None,
    insight_implication: str | None = None,
) -> dict:
    """Merge changes into existing strategy.yaml.

    Increments version, updates timestamp, appends insight if provided.
    Returns the updated config dict.
    """
    config_path = path or settings.strategy_config_path
    config = load_strategy_config(config_path)

    # Increment version
    config["version"] = config.get("version", 0) + 1
    config["updated_at"] = date.today().isoformat()
    config["updated_by"] = insight_source or "programmatic update"

    # Market selection updates
    ms = config.setdefault("market_selection", {})
    if target_categories is not None:
        ms["target_categories"] = target_categories
    if avoid_categories is not None:
        ms["avoid_categories"] = avoid_categories

    # Edge threshold updates
    et = config.setdefault("edge_thresholds", {})
    if category_overrides is not None:
        existing = et.get("category_overrides", {})
        existing.update(category_overrides)
        et["category_overrides"] = existing

    # Regime awareness updates
    ra = config.setdefault("regime_awareness", {})
    if current_regime is not None:
        ra["current_regime"] = current_regime
    if efficiency_trend is not None:
        ra["efficiency_trend"] = efficiency_trend
    if agent_confidence is not None:
        ra["agent_confidence"] = agent_confidence

    # Append insight
    if insight:
        insights = config.setdefault("insights", [])
        insights.append({
            "date": date.today().isoformat(),
            "finding": insight,
            "confidence": insight_confidence or "medium",
            "source": insight_source or "unknown",
            "implication": insight_implication or "",
        })

    # Write back
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    logger.info("Updated strategy config v%d at %s", config["version"], config_path)
    return config
