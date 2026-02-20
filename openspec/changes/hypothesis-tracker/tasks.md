## 1. Data Model

- [x] 1.1 Add `bt_hypotheses` CREATE TABLE to `database.py` SCHEMA_SQL
  - File: `src/polymarket_agent/backtest/database.py`

- [x] 1.2 Add `bt_hypothesis_evidence` CREATE TABLE to SCHEMA_SQL
  - File: `src/polymarket_agent/backtest/database.py`

- [x] 1.3 Add `bt_hypothesis_actions` CREATE TABLE to SCHEMA_SQL
  - File: `src/polymarket_agent/backtest/database.py`

- [x] 1.4 Add indexes for all three hypothesis tables
  - File: `src/polymarket_agent/backtest/database.py`

- [x] 1.5 Implement `seed_hypotheses()` with 4 initial hypotheses
  - File: `src/polymarket_agent/backtest/hypothesis.py`

- [x] 1.6 Call `seed_hypotheses()` from `init_backtest_db()`
  - File: `src/polymarket_agent/backtest/database.py`

## 2. Hypothesis CRUD & Core Engine

- [x] 2.1 Create `hypothesis.py` module with threshold constants
- [x] 2.2 Implement `propose()`
- [x] 2.3 Implement `record_evidence()`
- [x] 2.4 Implement `evaluate()` with confirmation/rejection/demotion logic
- [x] 2.5 Implement `_compute_weighted_confidence()`
- [x] 2.6 Implement `_compute_weighted_brier_diff()`

## 3. Iterability & Decay

- [x] 3.1 Implement `test()`
- [x] 3.2 Implement `retest()`
- [x] 3.3 Implement `decay_check()`
- [x] 3.4 Implement demotion logic within `evaluate()`

## 4. Action System

- [x] 4.1 Action activation on confirmation
- [x] 4.2 Action deactivation on invalidation/rejection/decay
- [x] 4.3 Implement `load_active_hypothesis_actions()`
- [x] 4.4 Implement `load_confirmed_hypotheses()`
- [x] 4.5 Implement `get_confirmed_hypotheses_summary()`

## 5. Integration — Strategy & Edge

- [x] 5.1 Modify `load_strategy_config()` to merge hypothesis actions
- [x] 5.2 Implement `_merge_hypothesis_actions()` helper
- [x] 5.3 Add `weight_adjustment` to `build_recommendation()` in edge.py

## 6. Integration — Simulator, Calibration & Scheduler

- [x] 6.1 Add `hypothesis_id` parameter to `run_simulation()`
- [x] 6.2 Implement `_compute_paired_stats()` for p-value and Cohen's d
- [x] 6.3 Auto-record hypothesis evidence with p_value and effect_size
- [x] 6.4 Modify `export_calibration_for_llm()` to append hypothesis summaries
- [x] 6.5 Modify `_check_strategy_drift()` to cross-reference hypotheses

## 7. CLI Commands

- [x] 7.1 Add `hypothesis` Click group
- [x] 7.2 Implement `hypothesis list`
- [x] 7.3 Implement `hypothesis propose`
- [x] 7.4 Implement `hypothesis test`
- [x] 7.5 Implement `hypothesis evaluate`
- [x] 7.6 Implement `hypothesis retest`
- [x] 7.7 Implement `hypothesis actions`
- [x] 7.8 Implement `hypothesis decay-check`

## 8. Tests

- [ ] 8.1 Test hypothesis CRUD
- [ ] 8.2 Test status transitions
- [ ] 8.3 Test confidence decay formula
- [ ] 8.4 Test evidence recording
- [ ] 8.5 Test `_compute_weighted_confidence()`
- [ ] 8.6 Test `_compute_weighted_brier_diff()`
- [ ] 8.7 Test action lifecycle
- [ ] 8.8 Test `load_active_hypothesis_actions()`
- [ ] 8.9 Test `_merge_hypothesis_actions()`
- [ ] 8.10 Test `build_recommendation()` with weight_adjustment
- [ ] 8.11 Test `export_calibration_for_llm()` with hypotheses
- [ ] 8.12 Test `seed_hypotheses()` idempotency
- [ ] 8.13 CLI smoke tests
