## Purpose

Implement the iterative hypothesis lifecycle engine in `backtest/hypothesis.py`. The engine manages hypotheses through a state machine (proposed -> testing -> confirmed/rejected, with demotion to invalidated). It provides functions to propose hypotheses with testable filters, run targeted simulations, evaluate evidence with statistical rigor, re-test with recency weighting, and scan for confidence decay. No hypothesis is ever permanently settled -- confirmed hypotheses decay over time and can be re-tested and demoted.

## Requirements

1. The `propose()` function SHALL create a new hypothesis with `status='proposed'`, `proposed_at` set to the current UTC timestamp, and `confidence_score=0.0`. It SHALL accept `name`, `description`, filter criteria (`category_filter`, `volume_min`, `volume_max`, `model_filter`, `temporal_filter`), decay parameters (`decay_half_life_days`, `retest_threshold`), and optional `actions` (list of dicts with `action_type`, `config`, `base_strength`). It SHALL return the new hypothesis ID.

2. The `propose()` function SHALL validate that the `name` is unique and raise an error if a hypothesis with that name already exists.

3. When `actions` are provided to `propose()`, the function SHALL insert them as inactive (`active=0`) rows in `bt_hypothesis_actions` linked to the new hypothesis.

4. The `test()` function SHALL accept a `hypothesis_id` and optional `count` (default 50) and `horizon` parameters. It SHALL load the hypothesis, extract its filter criteria, call `select_markets()` with those criteria, and call `run_simulation()` with the `hypothesis_id` parameter so evidence is auto-recorded.

5. The `test()` function SHALL transition a hypothesis from `proposed` to `testing` on first invocation, setting `first_tested_at` to the current UTC timestamp. Hypotheses already in `testing`, `confirmed`, or `invalidated` status SHALL remain in their current status. Hypotheses with status `rejected` SHALL NOT be testable.

6. The `test()` function SHALL extract filter criteria as follows: `category_filter=NULL` maps to `category=None` in `select_markets()`, `category_filter='*'` means no category filter, `volume_min`/`volume_max` pass through, and `temporal_filter.horizon_days` overrides the `horizon` argument when set.

7. The `evaluate()` function SHALL load all `bt_hypothesis_evidence` rows for a hypothesis, compute recency-weighted metrics, and transition the hypothesis status based on statistical thresholds.

8. The `evaluate()` function SHALL use the following confirmation thresholds (module-level constants): `CONFIRM_MIN_TRIALS = 30`, `CONFIRM_BRIER_DIFF = -0.02` (agent must be at least 0.02 Brier better), `CONFIRM_P_VALUE = 0.05`.

9. The `evaluate()` function SHALL use the following rejection thresholds: `REJECT_MIN_TRIALS = 30`, `REJECT_BRIER_DIFF = 0.02` (agent is 0.02 Brier worse), `REJECT_CONSECUTIVE_CONTRARY = 2`.

10. The confirmation path SHALL trigger when: weighted trial count >= `CONFIRM_MIN_TRIALS` AND weighted Brier diff <= `CONFIRM_BRIER_DIFF` AND the latest evidence p_value <= `CONFIRM_P_VALUE`. On confirmation, the function SHALL set `status='confirmed'`, `confirmed_at=now()`, compute and store the confidence score, and activate all associated actions (`active=1`, `activated_at=now()`).

11. The rejection path SHALL trigger when: weighted trial count >= `REJECT_MIN_TRIALS` AND weighted Brier diff >= `REJECT_BRIER_DIFF`. On rejection, the function SHALL set `status='rejected'`.

12. The demotion path SHALL trigger for currently confirmed hypotheses when the last `REJECT_CONSECUTIVE_CONTRARY` (2) evidence records all have `supports_hypothesis=0`. On demotion, the function SHALL set `status='invalidated'`, `invalidated_at=now()`, and deactivate all actions (`active=0`, `deactivated_at=now()`).

13. When none of the confirmation, rejection, or demotion criteria are met, the function SHALL leave the status unchanged, update `confidence_score` and `last_evaluated_at`, and return an inconclusive recommendation.

14. The `evaluate()` function SHALL return a dict containing: `status`, `confidence_score`, `evidence_count`, `weighted_brier_diff`, and `recommendation` (one of: `confirmed`, `rejected`, `invalidated`, `inconclusive`).

15. Recency weighting for evidence combination SHALL use the formula: `weight_i = 1.0 / (1.0 + age_days_i / 30.0)`, where `age_days_i` is the number of days between the evidence `recorded_at` and the current time.

16. The weighted confidence computation SHALL map each evidence record's `brier_diff` to a signal in [0.0, 1.0] via: clamp `brier_diff` to [-0.10, +0.10], then `signal = 0.5 - (clamped / 0.20)`. Evidence with `trial_count < 5` or `brier_diff=NULL` SHALL be excluded. Sample size weighting SHALL apply: `n_factor = min(2.0, 1.0 + trial_count / 100.0)`.

17. The `retest()` function SHALL call `test()` followed by `evaluate()`, returning the evaluation result. The new evidence receives higher recency weight due to its later `recorded_at` timestamp.

18. The `decay_check()` function SHALL scan all confirmed hypotheses, compute decayed confidence using the formula: `decayed_confidence = base_confidence * (0.5 ^ (days_elapsed / half_life_days))`, where `days_elapsed` is days since the most recent evidence record.

19. The `decay_check()` function SHALL update `confidence_score` on the hypothesis row with the decayed value. If decayed confidence falls below `retest_threshold`, the hypothesis SHALL be flagged with `recommendation='retest'`. If decayed confidence falls below 0.25 (critical threshold), the hypothesis SHALL be transitioned to `invalidated` and all actions deactivated.

20. The `record_evidence()` function SHALL insert a row into `bt_hypothesis_evidence` with the provided metrics. The `supports_hypothesis` field SHALL be set to: 1 if `brier_diff < 0`, 0 if `brier_diff > 0`, NULL if `brier_diff == 0` or `trial_count < 5`.

21. The `get_confirmed_hypotheses_summary()` function SHALL return a markdown-formatted text summary of all confirmed hypotheses (name, description, confidence) suitable for inclusion in LLM prompts, or None if no confirmed hypotheses exist.

22. The `load_confirmed_hypotheses()` function SHALL return a list of dicts for all hypotheses with `status='confirmed'`, containing: `id`, `name`, `description`, `confidence_score`, `category_filter`, `volume_min`, `volume_max`.

## Scenarios

#### Scenario: Propose a new hypothesis
- **GIVEN** no hypothesis named "test-alpha" exists
- **WHEN** `propose(name="test-alpha", description="Agent has alpha on test markets", volume_min=100000)` is called
- **THEN** a new row is inserted into `bt_hypotheses` with `status='proposed'`, `confidence_score=0.0`, `proposed_at` set to the current UTC time, and the function returns the new hypothesis ID

#### Scenario: Propose with actions creates inactive action rows
- **GIVEN** no hypothesis named "edge-test" exists
- **WHEN** `propose(name="edge-test", description="Test edge override", actions=[{"action_type": "edge_override", "config": {"base_threshold": 0.08}, "base_strength": 1.0}])` is called
- **THEN** a `bt_hypothesis_actions` row is created with `hypothesis_id` matching the new hypothesis, `action_type='edge_override'`, and `active=0`

#### Scenario: Propose with duplicate name raises error
- **GIVEN** a hypothesis named "probable-no-alpha" already exists
- **WHEN** `propose(name="probable-no-alpha", description="duplicate")` is called
- **THEN** an error is raised indicating the name is not unique

#### Scenario: Test transitions proposed to testing
- **GIVEN** a hypothesis with `status='proposed'` and ID 1
- **WHEN** `test(hypothesis_id=1, count=20)` is called
- **THEN** the hypothesis status transitions to `testing`, `first_tested_at` is set to the current UTC time, a simulation is run with the hypothesis filters, and the run summary is returned

#### Scenario: Test uses hypothesis filter criteria for market selection
- **GIVEN** a hypothesis with `category_filter=NULL`, `volume_min=100000`, `volume_max=1000000`, and `temporal_filter={"horizon_days": 7}`
- **WHEN** `test()` is called for this hypothesis
- **THEN** `select_markets()` is called with `category=None`, `volume_min=100000`, `volume_max=1000000`, and the simulation uses `horizon=7`

#### Scenario: Test rejected hypothesis is blocked
- **GIVEN** a hypothesis with `status='rejected'`
- **WHEN** `test()` is called for this hypothesis
- **THEN** an error is raised indicating rejected hypotheses cannot be tested

#### Scenario: Evaluate with sufficient supporting evidence confirms hypothesis
- **GIVEN** a hypothesis in `testing` status with evidence records totaling weighted trial count >= 30, weighted Brier diff <= -0.02, and latest p_value <= 0.05
- **WHEN** `evaluate()` is called
- **THEN** the hypothesis transitions to `confirmed`, `confirmed_at` is set, `confidence_score` is computed from weighted evidence, all associated actions are activated (`active=1`, `activated_at` set), and the return dict has `recommendation='confirmed'`

#### Scenario: Evaluate with sufficient contradicting evidence rejects hypothesis
- **GIVEN** a hypothesis in `testing` status with evidence records totaling weighted trial count >= 30 and weighted Brier diff >= 0.02
- **WHEN** `evaluate()` is called
- **THEN** the hypothesis transitions to `rejected` and the return dict has `recommendation='rejected'`

#### Scenario: Evaluate with insufficient evidence is inconclusive
- **GIVEN** a hypothesis in `testing` status with only 15 weighted trials
- **WHEN** `evaluate()` is called
- **THEN** the hypothesis remains in `testing`, `confidence_score` and `last_evaluated_at` are updated, and the return dict has `recommendation='inconclusive'`

#### Scenario: Confirmed hypothesis demoted on consecutive contrary evidence
- **GIVEN** a hypothesis with `status='confirmed'` and its last 2 evidence records both have `supports_hypothesis=0`
- **WHEN** `evaluate()` is called
- **THEN** the hypothesis transitions to `invalidated`, `invalidated_at` is set, all actions are deactivated (`active=0`, `deactivated_at` set), and the return dict has `recommendation='invalidated'`

#### Scenario: Retest runs simulation then evaluates
- **GIVEN** a confirmed hypothesis with ID 5
- **WHEN** `retest(hypothesis_id=5, count=30)` is called
- **THEN** a new simulation is run against the hypothesis filters, new evidence is recorded, and `evaluate()` is called with the new evidence receiving higher recency weight than older evidence

#### Scenario: Confidence decay over time
- **GIVEN** a confirmed hypothesis with `confidence_score=0.80`, `decay_half_life_days=90`, and the most recent evidence was recorded 90 days ago
- **WHEN** `decay_check()` is called
- **THEN** the decayed confidence is computed as `0.80 * (0.5 ^ (90/90)) = 0.40`, the hypothesis row is updated with `confidence_score=0.40`

#### Scenario: Decay triggers retest recommendation
- **GIVEN** a confirmed hypothesis with `retest_threshold=0.50` whose decayed confidence is 0.40
- **WHEN** `decay_check()` is called
- **THEN** the hypothesis appears in the returned list with `recommendation='retest'`

#### Scenario: Severe decay triggers invalidation
- **GIVEN** a confirmed hypothesis whose decayed confidence falls to 0.20 (below the 0.25 critical threshold)
- **WHEN** `decay_check()` is called
- **THEN** the hypothesis transitions to `invalidated`, all actions are deactivated, and the hypothesis appears in the returned list with `recommendation='invalidated'`

#### Scenario: Re-evaluation with new contradictory evidence demotes confirmed hypothesis
- **GIVEN** a confirmed hypothesis that was validated 60 days ago
- **WHEN** two new simulation runs both produce `brier_diff > 0` (agent worse), and `evaluate()` is called after each
- **THEN** after the second contradictory evidence record, the hypothesis transitions from `confirmed` to `invalidated` and all actions are deactivated

#### Scenario: Recency weighting favors newer evidence
- **GIVEN** a hypothesis with two evidence records: one from today with `brier_diff=-0.03` and one from 90 days ago with `brier_diff=+0.01`
- **WHEN** `evaluate()` computes weighted Brier diff
- **THEN** the today record has weight 1.0 and the 90-day record has weight 0.25, so the weighted Brier diff is dominated by the newer record

#### Scenario: Record evidence sets supports_hypothesis correctly
- **GIVEN** a simulation run completes with `brier_diff=-0.04` and `trial_count=25`
- **WHEN** `record_evidence()` is called
- **THEN** the evidence row has `supports_hypothesis=1` (brier_diff < 0 means agent better)

#### Scenario: Record evidence with inconclusive results
- **GIVEN** a simulation run completes with `trial_count=3`
- **WHEN** `record_evidence()` is called
- **THEN** the evidence row has `supports_hypothesis=NULL` (trial_count < 5 is inconclusive)
