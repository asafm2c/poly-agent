## 1. Config

- [x] 1.1 Add `simulation_concurrency: int = 5` to `config.py` (env: `SIMULATION_CONCURRENCY`)
- [x] 1.2 Add `llm_max_retries: int = 3` to `config.py` (env: `LLM_MAX_RETRIES`)
- [x] 1.3 Add `llm_retry_base_delay: float = 1.0` to `config.py` (env: `LLM_RETRY_BASE_DELAY`)
- [x] 1.4 Add `llm_retry_on_overloaded: bool = True` to `config.py` (env: `LLM_RETRY_ON_OVERLOADED`)

## 2. LLMClient — Retry & Thread Safety

- [x] 2.1 Add `threading.Lock` to `LLMClient.__init__` for protecting counter increments
- [x] 2.2 Wrap all writes to `total_input_tokens`, `total_output_tokens`, `total_cost`, `call_count` in the lock
- [x] 2.3 Replace hardcoded `retries=2` in `complete()` with `settings.llm_max_retries`
- [x] 2.4 Replace fixed `wait = 2^(attempt+1)` backoff with jitter formula: `min(60, base * 2**attempt) * uniform(0.5, 1.5)` using `settings.llm_retry_base_delay`
- [x] 2.5 Add retry on `overloaded_error` APIError when `settings.llm_retry_on_overloaded` is True

## 3. Simulator — Parallel Trial Execution

- [x] 3.1 Extract the per-trial body in `run_simulation()` into a standalone `_run_single_trial(market_dict, ...) -> dict` helper function (pure, no shared mutable state except DB writes)
- [x] 3.2 Add a `threading.Lock` parameter to `_run_single_trial` for serializing DB INSERT
- [x] 3.3 Refactor `run_simulation()` to use `asyncio`: replace the for-loop with `asyncio.gather` over `asyncio.to_thread(_run_single_trial, ...)` calls, gated by `asyncio.Semaphore(concurrency)`
- [x] 3.4 Add `concurrency: int | None = None` parameter to `run_simulation()` (falls back to `settings.simulation_concurrency`)
- [x] 3.5 Wrap `asyncio.gather` in `asyncio.run()` so `run_simulation()` public signature stays synchronous
- [x] 3.6 Replace per-trial `console.print` progress with a Rich `Progress` bar updated via callback as each trial coroutine completes
- [x] 3.7 Update per-trial cost tracking: remove the `cumulative_cost - prev_cumulative_cost` delta pattern; have `_run_single_trial` return its cost from a per-call accumulation

## 4. Multi-Model Evaluation

- [x] 4.1 Propagate `concurrency` parameter from `run_multi_model_evaluation()` down to each `run_simulation()` call

## 5. CLI

- [x] 5.1 Add `--concurrency` option (type int, default None) to `backtest simulate` Click command
- [x] 5.2 Pass `concurrency` to `run_simulation()` call in `simulate_backtest()`
- [x] 5.3 Add `--concurrency` option (type int, default None) to `backtest evaluate` Click command
- [x] 5.4 Pass `concurrency` to `run_multi_model_evaluation()` call in `evaluate_backtest()`

## 6. Tests

- [x] 6.1 Update existing `run_simulation()` tests to mock `asyncio.to_thread` / patch LLM calls; verify results are equivalent to serial
- [x] 6.2 Add test: `concurrency=1` produces same trial count and run record as before
- [x] 6.3 Add test: semaphore limits concurrent trials (mock with a counter + event)
- [x] 6.4 Add test: `LLMClient` retry triggers on `RateLimitError` with correct attempt count
- [x] 6.5 Add test: `LLMClient` retry triggers on `overloaded_error` when `llm_retry_on_overloaded=True`
- [x] 6.6 Add test: non-retryable 400 error raises immediately
- [x] 6.7 Add test: thread-safe counter accumulation under concurrent calls (two threads, verify no double-count)
- [x] 6.8 Add test: failed trial does not abort the run; other trials complete
