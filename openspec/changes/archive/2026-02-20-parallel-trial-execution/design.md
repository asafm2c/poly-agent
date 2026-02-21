## Context

The backtest simulator runs trials as a serial for-loop (simulator.py:467). Each trial is independent — it reads from the DB, calls `ProbabilityEstimator.estimate()` (4 serial LLM passes), and writes a result row. With Sonnet at ~18s/trial, a 50-trial run takes ~15 minutes and a 200-trial evaluation takes an hour.

The `LLMClient` already has basic retry logic (`retries=2`, fixed backoff `2^(attempt+1)`). The SDK imports `RateLimitError` and `APIError` from `anthropic`. The client is synchronous (uses `Anthropic`, not `AsyncAnthropic`).

Constraint: the Anthropic Python SDK's sync client uses blocking I/O. Running it in a thread pool (`asyncio.to_thread`) is the correct way to achieve concurrent LLM calls without rewriting every call site to async.

## Goals / Non-Goals

**Goals:**
- Parallelize trials across markets using `asyncio` + `ThreadPoolExecutor` (bounded concurrency)
- Configurable concurrency limit via `settings.simulation_concurrency` (default: 5)
- Improve retry/backoff in `LLMClient`: jitter, configurable max retries, configurable base delay
- Progress display works correctly under concurrency (Rich progress bar, not per-trial print)
- Thread-safe cost/token accumulation in `LLMClient`
- DB writes serialized (SQLite WAL handles reads, but inserts should be serialized)

**Non-Goals:**
- Making `LLMClient` itself async (too invasive, touches all call sites)
- Parallelizing the 4 passes within a trial (they chain output to input — not possible)
- Parallelizing across multiple models simultaneously (models run sequentially by design)
- Changing the public CLI interface

## Decisions

### D1: asyncio + ThreadPoolExecutor, not multiprocessing
Each trial's bottleneck is I/O (LLM network calls), not CPU. `asyncio.to_thread` dispatches blocking sync calls to a thread pool with no code changes to `LLMClient.complete()`. Multiprocessing would add serialization overhead and complicate shared state (cost counters, DB connections).

**Alternative considered**: Full async rewrite of `LLMClient` using `AsyncAnthropic`. Rejected — touches 20+ call sites across the codebase, high risk, low additional gain since trials are the bottleneck.

### D2: Semaphore-based concurrency limit, not a fixed thread pool size
`asyncio.Semaphore(settings.simulation_concurrency)` wraps each trial coroutine. This decouples concurrency (active simultaneous trials) from thread pool size and makes the limit obvious and configurable.

Default of 5 concurrent Sonnet trials means ~5 requests in-flight at once — well within Anthropic's rate limits (typically 50 req/min for Sonnet tier 1, higher for higher tiers).

### D3: Improved retry with jitter in LLMClient
Current retry: `wait = 2^(attempt+1)`, no jitter. Under parallelism, all retrying threads would wake simultaneously — a thundering herd against the rate limit. Fix: `wait = base_delay * 2^attempt + random.uniform(0, 1)`.

New configurable settings:
- `llm_max_retries`: default 3 (up from 2)
- `llm_retry_base_delay`: default 1.0s
- `llm_retry_on_overloaded`: default True (retry `overloaded_error` in addition to 429)

### D4: Thread-safe LLMClient token/cost counters
Currently `total_input_tokens`, `total_output_tokens`, `total_cost`, `call_count` are plain ints/floats. Under parallel threads mutating the same `LLMClient` instance, these can race. Fix: use `threading.Lock` around all counter increments.

**Alternative**: Give each trial its own `LLMClient` instance and aggregate at the end. Rejected — loses the unified cost tracking that the CLI relies on (`llm.get_usage_summary()`).

### D5: Serialized DB writes
Trial result inserts in `run_simulation()` will be wrapped in a single `threading.Lock` per simulation run. SQLite WAL allows concurrent readers, but concurrent writers can deadlock. The lock is held only for the insert, not for estimation.

### D6: run_simulation() stays synchronous at the public signature
The function internally creates an event loop with `asyncio.run(...)` around the parallel core. CLI callers (`main.py`) require no changes.

## Risks / Trade-offs

- **Rate limit bursts on startup** → Semaphore limits burst; jitter spreads retries. First batch of N concurrent trials will all start simultaneously — may hit token-per-minute limits before request-per-minute limits. Mitigation: configurable `simulation_concurrency` default of 5; user can lower if needed.

- **Harder to debug** → Parallel exceptions are collected and re-raised; per-trial errors are logged with market ID and do not abort the run (same behavior as today). Progress bar shows completions as they arrive.

- **Thread pool exhaustion** → `asyncio.to_thread` uses Python's default executor (128 threads max). With `simulation_concurrency=5` and 4 passes/trial, peak thread usage is 5 threads — well within limits.

- **Cost tracking race** → Mitigated by threading.Lock on counters (D4). The per-trial cost delta approach (`cumulative_cost - prev_cumulative_cost`) is fragile under concurrency — replace with per-call cost accumulation tracked in trial return value.

## Migration Plan

1. Add `simulation_concurrency`, `llm_max_retries`, `llm_retry_base_delay`, `llm_retry_on_overloaded` to `config.py`
2. Update `LLMClient`: add lock, improve retry/backoff, expose per-call cost in return
3. Refactor `run_simulation()`: extract `_run_single_trial()` helper, wrap in `asyncio.to_thread`, coordinate with semaphore + lock
4. Update progress reporting (Rich progress bar replaces per-trial console prints)
5. Update tests: mock async paths, test retry logic, test concurrency limit

Rollback: `simulation_concurrency=1` effectively restores serial behavior with no code revert needed.

## Open Questions

- None — retry and concurrency approach are well-defined.
