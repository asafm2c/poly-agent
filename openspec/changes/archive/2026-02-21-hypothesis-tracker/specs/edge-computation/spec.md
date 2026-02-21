## Purpose

Extend the edge computation and trade recommendation logic to incorporate hypothesis-driven actions. Confirmed hypotheses with `edge_override` actions influence per-category and per-tier edge thresholds, and `weight_adjustment` actions scale Kelly position sizing. These adjustments flow through the existing strategy config mechanism -- hypothesis actions are merged into the config by `load_strategy_config()`, so `compute_required_edge()` applies them via the existing `category_overrides` lookup without signature changes.

## MODIFIED Requirements

### Requirement: Hypothesis edge overrides applied via strategy config
The `compute_required_edge()` function SHALL apply hypothesis-driven edge threshold overrides that are merged into `strategy_config` by the strategy config loader. When a market's category matches an `edge_override` action's `applies_to` key in `edge_thresholds.category_overrides`, the override value SHALL be used as the base threshold. The effective override value incorporates confidence decay: at full confidence it equals `base_threshold`, and as confidence decays the threshold increases (requiring more edge).

#### Scenario: Confirmed hypothesis lowers edge threshold for matching category
- **GIVEN** a confirmed hypothesis "mid-volume-sweet-spot" with an `edge_override` action (`base_threshold=0.08`, `applies_to="100K-1M"`) at `confidence=1.0` merged into strategy_config
- **WHEN** `compute_required_edge()` is called for a market matching that category override
- **THEN** the base threshold is 0.08 instead of the default computed value

#### Scenario: Decayed confidence increases effective edge threshold
- **GIVEN** a confirmed hypothesis with `edge_override` (`base_threshold=0.08`) at `confidence=0.50` merged into strategy_config with effective threshold `0.08 * (1.0 + (1.0 - 0.50) * 0.5) = 0.10`
- **WHEN** `compute_required_edge()` is called for a matching market
- **THEN** the base threshold is 0.10, requiring more edge than at full confidence

#### Scenario: User strategy config overrides win over hypothesis actions
- **GIVEN** `strategy.yaml` explicitly sets `edge_thresholds.category_overrides.crypto: 0.15` AND a hypothesis action also targets the `crypto` category override
- **WHEN** strategy config is loaded
- **THEN** the user's explicit value (0.15) takes precedence; the hypothesis action does not overwrite it

#### Scenario: No hypothesis actions, no change to edge computation
- **GIVEN** no confirmed hypotheses exist
- **WHEN** `compute_required_edge()` is called
- **THEN** the function behaves identically to the current implementation with no hypothesis influence

### Requirement: Hypothesis weight adjustments applied to Kelly sizing
The `build_recommendation()` function SHALL check `strategy_config.hypothesis_actions` for `weight_adjustment` actions and apply the effective Kelly multiplier to the computed position size. The effective multiplier is `1.0 + (kelly_multiplier - 1.0) * effective_strength`.

#### Scenario: Weight adjustment increases position size
- **GIVEN** a confirmed hypothesis with a `weight_adjustment` action (`kelly_multiplier=1.2`, `effective_strength=1.0`)
- **WHEN** `build_recommendation()` computes a base position size of $100
- **THEN** the final position size is $120 (100 * 1.2)

#### Scenario: Decayed weight adjustment partially increases position size
- **GIVEN** a confirmed hypothesis with a `weight_adjustment` action (`kelly_multiplier=1.2`, `effective_strength=0.50`)
- **WHEN** `build_recommendation()` computes a base position size of $100
- **THEN** the effective multiplier is `1.0 + (1.2 - 1.0) * 0.50 = 1.10`, so the final position size is $110

#### Scenario: Conservative weight adjustment reduces position size
- **GIVEN** a confirmed hypothesis "high-volume-efficient" with a `weight_adjustment` action (`kelly_multiplier=0.8`, `effective_strength=1.0`)
- **WHEN** `build_recommendation()` computes a base position size of $100
- **THEN** the final position size is $80 (reduced for efficient markets)

#### Scenario: Multiple weight adjustments applied multiplicatively
- **GIVEN** two confirmed hypotheses each with `weight_adjustment` actions (multipliers 1.2 and 0.9)
- **WHEN** `build_recommendation()` processes both
- **THEN** the multipliers are applied sequentially: `$100 * 1.2 * 0.9 = $108`

### Requirement: Threshold bounds still enforced
All hypothesis-adjusted thresholds SHALL remain clamped between `min_edge_floor` and `max_edge_ceiling`. Hypothesis actions cannot push the required edge below the floor or above the ceiling.

#### Scenario: Hypothesis threshold clamped to floor
- **GIVEN** a hypothesis `edge_override` produces an effective threshold of 0.02, and `min_edge_floor` is 0.05
- **WHEN** `compute_required_edge()` applies bounds
- **THEN** the final threshold is 0.05 (clamped to floor)
