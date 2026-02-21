## Why

Backtest simulations run trials serially — each market is estimated one at a time with 4 sequential LLM calls. With 50+ trials this is slow (estimated 15+ min for a 50-trial Sonnet run), and the markets are fully independent of each other, making trial-level parallelism a straightforward win.

## What Changes

- Simulation trials execute concurrently using `asyncio` + a bounded semaphore, rather than a serial for-loop
- LLMClient gains retry logic with exponential backoff for rate-limit errors (HTTP 429 / `overloaded_error`)
- Concurrency limit is configurable (default: 5 concurrent trials) to respect Anthropic rate limits
- The 4-pass pipeline within each trial remains serial (passes chain output to input)
- `run_simulation()` becomes async-capable; CLI caller uses `asyncio.run()`
- Progress reporting adapts to show concurrent completion rather than sequential index
- `ProbabilityEstimator` gains `estimate_async()` for use within the async trial loop; sync `estimate()` unchanged for non-backtest callers
- CLI `backtest simulate` and `backtest evaluate` expose `--concurrency` flag
- Default analysis model for simulation is Sonnet (Haiku is used only for the separate screening pass)

## Capabilities

### New Capabilities
- `llm-retry`: Retry with exponential backoff on transient LLM errors (429, overloaded). Configurable max retries and base delay.
- `parallel-simulation`: Concurrent trial execution in backtest simulation runs. Configurable concurrency limit.

### Modified Capabilities
- `analysis-library`: `run_simulation()` signature changes to support async execution; internal loop replaced with `asyncio.gather` over bounded semaphore.

## Impact

- `src/polymarket_agent/analyst/llm_client.py` — add retry/backoff wrapper around `complete_json` and `complete`
- `src/polymarket_agent/backtest/simulator.py` — `run_simulation()` refactored to use `asyncio`, trial loop parallelized
- `src/polymarket_agent/config.py` — new settings: `simulation_concurrency` (default 5), `llm_max_retries` (default 3), `llm_retry_base_delay` (default 1.0s)
- `tests/test_backtest.py` — update simulator tests for async; add retry tests
- No CLI interface changes; no breaking API changes to public function signatures beyond async
