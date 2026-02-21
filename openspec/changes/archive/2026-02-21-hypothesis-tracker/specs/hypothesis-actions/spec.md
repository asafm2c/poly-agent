## Purpose

Translate confirmed hypotheses into conservative, typed parameter adjustments that influence the live trading pipeline. Actions have strength proportional to their parent hypothesis's confidence score -- as confidence decays, action strength decays proportionally. Actions are automatically activated on hypothesis confirmation, automatically deactivated on hypothesis demotion or invalidation, and queryable at startup by strategy config and edge computation. The system ensures that stale or invalidated hypotheses cannot permanently bias the pipeline.

## Requirements

1. The `load_active_hypothesis_actions()` function SHALL query all actions where `active=1` and the parent hypothesis has `status='confirmed'`, joining `bt_hypothesis_actions` with `bt_hypotheses`. Results SHALL be ordered by `confidence_score` descending.

2. Each action returned by `load_active_hypothesis_actions()` SHALL include: `hypothesis_id`, `hypothesis_name`, `action_type`, `config` (parsed from JSON to dict), `base_strength`, `effective_strength` (computed as `base_strength * confidence_score`), and `hypothesis_confidence`.

3. The `edge_override` action type SHALL store a JSON config with keys `base_threshold` (float) and `applies_to` (string identifying the scope, e.g., category name or volume tier label). The effective threshold SHALL be computed as: `base_threshold * (1.0 + (1.0 - confidence * base_strength) * 0.5)`. At full confidence and strength (1.0), the threshold equals `base_threshold`. As confidence decays, the threshold creeps toward 1.5x `base_threshold`.

4. The `category_target` action type SHALL store a JSON config with keys `category` (string or null) and `reason` (string). This action SHALL be binary -- active when the hypothesis is confirmed, inactive otherwise. No strength scaling SHALL apply.

5. The `category_avoid` action type SHALL store a JSON config with keys `category` (string) and `reason` (string). This action SHALL be binary -- active when the hypothesis is confirmed, inactive otherwise. No strength scaling SHALL apply.

6. The `model_preference` action type SHALL store a JSON config with keys `model` (string, model identifier) and `reason` (string). This action SHALL be advisory only -- logged but not enforced until model-switching is implemented.

7. The `weight_adjustment` action type SHALL store a JSON config with keys `kelly_multiplier` (float) and `reason` (string). The effective multiplier SHALL be computed as: `1.0 + (kelly_multiplier - 1.0) * confidence * base_strength`. At full confidence, the full multiplier applies. At zero confidence, the multiplier is 1.0 (neutral).

8. Actions SHALL be activated when `evaluate()` confirms a hypothesis: `active` set to 1, `activated_at` set to the current UTC timestamp.

9. Actions SHALL be deactivated when a hypothesis is demoted to `invalidated` or when `decay_check()` drops confidence below the critical 0.25 threshold: `active` set to 0, `deactivated_at` set to the current UTC timestamp.

10. Actions SHALL NOT be activated for hypotheses in any status other than `confirmed`. A hypothesis transitioning from `confirmed` to `invalidated` MUST deactivate all its actions.

11. When `decay_check()` updates a hypothesis's confidence score, the effective strength of all active actions for that hypothesis SHALL reflect the new (lower) confidence through the `effective_strength = base_strength * confidence_score` computation. No separate update to the action rows is needed -- `load_active_hypothesis_actions()` computes effective strength at query time.

12. Action configs SHALL be validated on creation: `edge_override` MUST have `base_threshold`, `category_target` and `category_avoid` MUST have `category`, `weight_adjustment` MUST have `kelly_multiplier`. Missing required config keys SHOULD raise a validation error.

## Scenarios

#### Scenario: Load active actions for confirmed hypothesis
- **GIVEN** a confirmed hypothesis "mid-volume-sweet-spot" with `confidence_score=0.75` and two active actions: an `edge_override` with `base_strength=1.0` and a `weight_adjustment` with `base_strength=0.8`
- **WHEN** `load_active_hypothesis_actions()` is called
- **THEN** two action dicts are returned: the `edge_override` with `effective_strength=0.75` (1.0 * 0.75), and the `weight_adjustment` with `effective_strength=0.60` (0.8 * 0.75)

#### Scenario: No active actions when no hypotheses are confirmed
- **GIVEN** all hypotheses are in `proposed` or `testing` status
- **WHEN** `load_active_hypothesis_actions()` is called
- **THEN** an empty list is returned

#### Scenario: Invalidated hypothesis actions not returned
- **GIVEN** a hypothesis that was confirmed and had active actions, then was demoted to `invalidated` with actions set to `active=0`
- **WHEN** `load_active_hypothesis_actions()` is called
- **THEN** none of that hypothesis's actions appear in the results

#### Scenario: Edge override effective threshold at full confidence
- **GIVEN** an `edge_override` action with `base_threshold=0.08`, `base_strength=1.0`, and `hypothesis_confidence=1.0`
- **WHEN** the effective threshold is computed
- **THEN** the result is `0.08 * (1.0 + (1.0 - 1.0 * 1.0) * 0.5) = 0.08`

#### Scenario: Edge override effective threshold at decayed confidence
- **GIVEN** an `edge_override` action with `base_threshold=0.08`, `base_strength=1.0`, and `hypothesis_confidence=0.50`
- **WHEN** the effective threshold is computed
- **THEN** the result is `0.08 * (1.0 + (1.0 - 0.50) * 0.5) = 0.08 * 1.25 = 0.10`, requiring more edge as confidence decays

#### Scenario: Weight adjustment effective multiplier at full confidence
- **GIVEN** a `weight_adjustment` action with `kelly_multiplier=1.2`, `base_strength=1.0`, and `hypothesis_confidence=1.0`
- **WHEN** the effective multiplier is computed
- **THEN** the result is `1.0 + (1.2 - 1.0) * 1.0 * 1.0 = 1.2`

#### Scenario: Weight adjustment effective multiplier at decayed confidence
- **GIVEN** a `weight_adjustment` action with `kelly_multiplier=1.2`, `base_strength=0.8`, and `hypothesis_confidence=0.50`
- **WHEN** the effective multiplier is computed
- **THEN** the result is `1.0 + (1.2 - 1.0) * 0.50 * 0.8 = 1.08`, applying only a fraction of the adjustment

#### Scenario: Actions activated on hypothesis confirmation
- **GIVEN** a hypothesis with `status='testing'` and two inactive actions
- **WHEN** `evaluate()` confirms the hypothesis (meets all confirmation thresholds)
- **THEN** both actions have `active=1` and `activated_at` set to the current UTC timestamp

#### Scenario: Actions deactivated on hypothesis demotion
- **GIVEN** a confirmed hypothesis with two active actions, and its last 2 evidence records both have `supports_hypothesis=0`
- **WHEN** `evaluate()` demotes the hypothesis to `invalidated`
- **THEN** both actions have `active=0` and `deactivated_at` set to the current UTC timestamp

#### Scenario: Actions deactivated on severe confidence decay
- **GIVEN** a confirmed hypothesis with `confidence_score=0.30` and active actions, whose most recent evidence is 120 days old with `decay_half_life_days=90`
- **WHEN** `decay_check()` runs and decayed confidence falls to `0.30 * (0.5 ^ (120/90)) = 0.119`, below the 0.25 critical threshold
- **THEN** the hypothesis transitions to `invalidated` and all actions are deactivated

#### Scenario: Action strength proportionally weakens with confidence decay
- **GIVEN** a confirmed hypothesis originally at `confidence_score=0.80` with an `edge_override` action (`base_strength=1.0`)
- **WHEN** `decay_check()` updates the confidence to 0.40 (after 90 days with 90-day half-life)
- **THEN** the next call to `load_active_hypothesis_actions()` returns `effective_strength=0.40` for that action, and the edge override effective threshold is `0.08 * (1.0 + (1.0 - 0.40) * 0.5) = 0.104`

#### Scenario: Category target action is binary
- **GIVEN** a `category_target` action for the confirmed hypothesis "probable-no-alpha" with `category=null`
- **WHEN** the hypothesis is confirmed
- **THEN** the action is active (included in strategy config's target categories) regardless of `confidence_score` or `base_strength` values

#### Scenario: Category avoid action deactivated on invalidation
- **GIVEN** a `category_avoid` action for "sports-no-alpha" with `category="Match Winner"`
- **WHEN** the hypothesis is invalidated
- **THEN** the action is deactivated and "Match Winner" is no longer on the strategy avoid list
