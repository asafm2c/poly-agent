## Context

Two bugs found during code review after simulation harness implementation:

1. `cli/main.py` line 141: `rec = build_recommendation(...)` assigns the full 3-tuple to `rec`. The `if rec:` check on line 143 always evaluates to `True` because a non-empty tuple is truthy — even when the first element is `None` (no trade recommended).

2. `backtest/simulator.py` line 478-479: `llm.get_usage_summary()["estimated_cost"]` returns cumulative cost since the `LLMClient` was instantiated, not the cost of the current trial. Each trial's `llm_cost` in the DB is the running total, making per-trial cost analysis meaningless.

## Goals / Non-Goals

**Goals:**
- Fix `analyze` CLI to correctly display "no trade recommended" when edge is below threshold
- Fix simulation per-trial cost to record the delta (cost of that trial only)

**Non-Goals:**
- Backfilling incorrect cost data from prior simulation runs
- Refactoring `LLMClient` cost tracking interface
- Fixing other identified gaps (order fill polling, live sell, Telegram)

## Decisions

### 1. Unpack tuple at call site

Unpack `build_recommendation()` return value into `(rec, adj_edge, req_threshold)`. The `if rec:` check then correctly tests `None` vs `TradeRecommendation`. Display `adj_edge` and `req_threshold` in the output for transparency.

**Alternative**: Change `build_recommendation()` to return just the recommendation. Rejected — the 3-tuple interface is used elsewhere and the extra info is valuable.

### 2. Track cumulative cost before each trial and compute delta

Before calling the estimator, snapshot `prev_cost = llm.get_usage_summary()["estimated_cost"]`. After the call, `trial_cost = current_cost - prev_cost`. This is the simplest fix with no changes to `LLMClient`.

**Alternative**: Add a `reset_usage()` or per-call cost tracking to `LLMClient`. Rejected — more invasive for a backtest-only fix.

## Risks / Trade-offs

- [Floating point drift] The cost delta could accumulate rounding errors over many trials → Acceptable for cost tracking precision ($0.001 level).
- [Existing data is wrong] Prior `bt_simulation_trials.llm_cost` values are cumulative, not per-trial → No backfill; old runs are test data. Document in commit message.
