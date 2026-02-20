## Why

Two correctness bugs were found during code review: the `analyze` CLI command mishandles the `build_recommendation()` return value (always shows a trade recommendation even when edge is below threshold), and the simulation harness records cumulative LLM cost instead of per-trial cost. Both silently produce wrong results.

## What Changes

- **Fix `analyze` CLI tuple unpacking**: `build_recommendation()` returns `(rec_or_none, adj_edge, req_threshold)` but the CLI assigns the whole tuple to `rec` and checks `if rec:` — which is always truthy. Must unpack the 3-tuple so `None` returns correctly show "no trade recommended."
- **Fix simulation per-trial cost tracking**: `llm.get_usage_summary()["estimated_cost"]` returns the cumulative total since client instantiation. Must compute delta between calls to get the actual per-trial cost. The run-level `total_cost` is already correct (it takes the final cumulative value).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `analysis-library`: Fix per-trial LLM cost computation in simulation harness (delta instead of cumulative)

## Impact

- `src/polymarket_agent/cli/main.py`: Fix `analyze` command return value handling
- `src/polymarket_agent/backtest/simulator.py`: Fix per-trial cost tracking in `run_simulation()`
- Existing `bt_simulation_trials.llm_cost` data from prior runs is inaccurate (cumulative, not per-trial)
