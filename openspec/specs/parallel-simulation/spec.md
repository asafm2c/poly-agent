## ADDED Requirements

### Requirement: Concurrent trial execution with bounded semaphore
The backtest simulator SHALL execute trials concurrently using `asyncio` with a semaphore that limits active simultaneous trials to `settings.simulation_concurrency` (default: 5). Trials SHALL be dispatched as `asyncio.to_thread` tasks wrapping the synchronous `_run_single_trial()` helper.

#### Scenario: Trials run concurrently up to concurrency limit
- **WHEN** `run_simulation()` is called with 20 markets and `concurrency=5`
- **THEN** at most 5 trials are executing simultaneously at any point in time

#### Scenario: All trials complete regardless of individual errors
- **WHEN** one trial raises an exception during LLM estimation
- **THEN** the exception is logged, the trial is recorded as failed, and all remaining trials continue to completion

#### Scenario: Concurrency=1 reproduces serial behavior
- **WHEN** `run_simulation()` is called with `concurrency=1`
- **THEN** trials execute one at a time, identical in behavior to the original serial loop

### Requirement: Configurable concurrency via settings and CLI
The simulation concurrency limit SHALL be configurable via `settings.simulation_concurrency` (from env var `SIMULATION_CONCURRENCY`, default 5). The CLI `backtest simulate` and `backtest evaluate` commands SHALL expose a `--concurrency` option that overrides the setting for that run.

#### Scenario: Concurrency set via CLI flag
- **WHEN** `backtest simulate --count 50 --concurrency 10` is run
- **THEN** the simulation uses a semaphore of size 10 for that run

#### Scenario: Concurrency defaults to settings value
- **WHEN** `--concurrency` is not passed on the CLI
- **THEN** `settings.simulation_concurrency` (default 5) is used

### Requirement: Thread-safe cost and token accumulation
The shared `LLMClient` instance used across concurrent trials SHALL accumulate token counts and cost totals correctly without race conditions. All writes to `total_input_tokens`, `total_output_tokens`, `total_cost`, and `call_count` SHALL be protected by a `threading.Lock`.

#### Scenario: Costs accurately tallied under concurrency
- **WHEN** 5 concurrent trials each make 4 LLM calls
- **THEN** `llm.get_usage_summary()` after the run reflects exactly 20 calls with the correct total cost

### Requirement: Serialized DB writes during concurrent simulation
Trial result INSERT statements SHALL be serialized via a per-run lock to prevent SQLite write contention. Read operations (market loading, price history) do not require serialization.

#### Scenario: Concurrent inserts do not corrupt the DB
- **WHEN** multiple trials complete simultaneously and attempt to INSERT into `bt_simulation_trials`
- **THEN** all rows are inserted correctly with no lost writes or database errors

### Requirement: Live progress display under concurrency
The progress display SHALL show completions in real-time as trials finish (not in submission order). The display SHALL show completed count, total count, and a running Brier score estimate.

#### Scenario: Progress updates as trials complete out of order
- **WHEN** trials complete in a non-sequential order due to varying LLM latency
- **THEN** the progress bar increments on each completion and shows the current count (e.g. "12/50 completed")
