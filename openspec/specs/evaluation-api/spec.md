## Purpose

Route module (`routes/evaluation.py`) serving simulation results from `backtest.db` as JSON API endpoints under `/api/evaluation/`. Reimplements `analysis.py` aggregation queries in async SQL to keep the dashboard decoupled from the agent package. All endpoints guard on `backtest_db is None` and return empty-state responses when the backtest database is unavailable.

## Requirements

### Requirement 1: Simulation runs listing endpoint
The dashboard SHALL expose `GET /api/evaluation/runs` returning a JSON object with an `available` boolean and a `runs` array. Each run object SHALL include: `id`, `started_at`, `completed_at`, `config`, `market_count`, `trial_count`, `valid_trials`, `agent_brier`, `market_brier`, `brier_diff`, `simulated_pnl`, `trade_count`, `win_rate`, and `total_cost`. Runs SHALL be ordered by `id` descending (most recent first).

#### Scenario: Backtest DB exists with simulation runs
- **GIVEN** `backtest.db` exists and contains 3 simulation runs
- **WHEN** a client requests `GET /api/evaluation/runs`
- **THEN** the response has `available: true` and `runs` contains 3 objects ordered by `id` descending, each with `brier_diff` computed as `AVG(agent_brier) - AVG(market_brier)` from joined trials

#### Scenario: Backtest DB does not exist
- **GIVEN** `backtest.db` does not exist and `app.state.backtest_db` is `None`
- **WHEN** a client requests `GET /api/evaluation/runs`
- **THEN** the response is `{"runs": [], "available": false}`

#### Scenario: Backtest DB exists but no runs
- **GIVEN** `backtest.db` exists but `bt_simulation_runs` is empty
- **WHEN** a client requests `GET /api/evaluation/runs`
- **THEN** the response is `{"runs": [], "available": true}`

#### Scenario: Run with zero trades
- **GIVEN** a simulation run exists where no trials triggered a trade (`simulated_trade` is `null` for all trials)
- **WHEN** a client requests `GET /api/evaluation/runs`
- **THEN** the run object has `trade_count: 0` and `win_rate: null`

### Requirement 2: Per-trial detail endpoint
The dashboard SHALL expose `GET /api/evaluation/trials/{run_id}` returning a JSON object with `run_id`, `count`, and a `trials` array. Each trial SHALL include: `trial_id`, `market_id`, `question`, `category`, `volume`, `volume_tier`, `end_date`, `horizon_days`, `market_price`, `agent_estimate`, `confidence_low`, `confidence_high`, `outcome`, `agent_brier`, `market_brier`, `brier_diff`, `edge`, `simulated_trade`, `reasoning`, `llm_cost`, and `duration_ms`. The endpoint SHALL accept `sort_by` (default `"market_id"`, allowed: `"brier_diff"`, `"agent_brier"`, `"volume"`, `"category"`, `"market_id"`) and `sort_dir` (default `"asc"`, allowed: `"asc"`, `"desc"`) query parameters.

#### Scenario: Valid run with trials
- **GIVEN** run_id 3 exists with 20 trials
- **WHEN** a client requests `GET /api/evaluation/trials/3`
- **THEN** the response has `run_id: 3`, `count: 20`, and `trials` contains 20 objects with `volume_tier` computed via SQL CASE expression matching the `10K-100K`, `100K-1M`, `1M-10M`, `>10M` boundaries

#### Scenario: Sort by Brier difference descending
- **GIVEN** run_id 3 exists with trials having varying Brier differences
- **WHEN** a client requests `GET /api/evaluation/trials/3?sort_by=brier_diff&sort_dir=desc`
- **THEN** the trials array is ordered by `brier_diff` descending (market-better trials first)

#### Scenario: Invalid run_id
- **GIVEN** no simulation run with id 999 exists
- **WHEN** a client requests `GET /api/evaluation/trials/999`
- **THEN** the response has `run_id: 999`, `count: 0`, and `trials: []`

#### Scenario: Invalid sort_by parameter
- **GIVEN** a valid run exists
- **WHEN** a client requests `GET /api/evaluation/trials/3?sort_by=DROP_TABLE`
- **THEN** the `sort_by` value is rejected and the server falls back to the default `"market_id"` sort, preventing SQL injection

#### Scenario: Backtest DB unavailable
- **GIVEN** `app.state.backtest_db` is `None`
- **WHEN** a client requests `GET /api/evaluation/trials/3`
- **THEN** the response has `run_id: 3`, `count: 0`, and `trials: []`

### Requirement 3: Category breakdown endpoint
The dashboard SHALL expose `GET /api/evaluation/by-category/{run_id}` returning a JSON object with `run_id` and a `categories` array. Each category object SHALL include: `category` (with SQL NULL coalesced to `"(null)"`), `trial_count`, `agent_brier`, `market_brier`, `brier_diff`, and `simulated_pnl`. Categories SHALL be ordered by `trial_count` descending.

#### Scenario: Run with mixed categories
- **GIVEN** run_id 3 has 18 trials with `category = NULL` and 2 trials with `category = "Match Winner"`
- **WHEN** a client requests `GET /api/evaluation/by-category/3`
- **THEN** the response contains 2 category objects: `"(null)"` with `trial_count: 18` first, then `"Match Winner"` with `trial_count: 2`

#### Scenario: Invalid run_id
- **GIVEN** no run with id 999 exists
- **WHEN** a client requests `GET /api/evaluation/by-category/999`
- **THEN** the response has `run_id: 999` and `categories: []`

### Requirement 4: Volume tier breakdown endpoint
The dashboard SHALL expose `GET /api/evaluation/by-volume-tier/{run_id}` returning a JSON object with `run_id` and a `tiers` array. Each tier object SHALL include: `volume_tier`, `trial_count`, `agent_brier`, `market_brier`, `brier_diff`, and `simulated_pnl`. Volume tiers SHALL use the boundaries: `<100K` = `"10K-100K"`, `100K-1M`, `1M-10M`, `>=10M` = `">10M"`. Tiers SHALL be ordered from smallest to largest.

#### Scenario: Run with multiple volume tiers
- **GIVEN** run_id 3 has 18 trials in the `1M-10M` tier and 2 in the `>10M` tier
- **WHEN** a client requests `GET /api/evaluation/by-volume-tier/3`
- **THEN** the response contains 2 tier objects ordered `["1M-10M", ">10M"]` with correct aggregate Brier scores

#### Scenario: Volume tier SQL CASE consistency
- **GIVEN** a market with volume = 1,000,000
- **WHEN** the tier is computed
- **THEN** it is classified as `"1M-10M"` (boundary is `>= 1000000`)

### Requirement 5: Temporal analysis endpoint
The dashboard SHALL expose `GET /api/evaluation/temporal/{run_id}` returning a JSON object with `run_id`, a `trials` array ordered by `end_date` ascending, and a `regimes` array. Each trial SHALL include: `trial_id`, `market_id`, `question`, `end_date`, `category`, `volume`, `agent_brier`, `market_brier`, `brier_diff`, and `rolling_brier_diff`. The `rolling_brier_diff` SHALL be computed server-side as a cumulative moving average (mean of `brier_diff[0..i]` for trial `i`). Each regime SHALL include: `name`, `start_date`, and `end_date`. Only trials with non-null `agent_brier` SHALL be included.

#### Scenario: Temporal ordering with rolling average
- **GIVEN** run_id 3 has 3 trials with `brier_diff` values `[-0.03, 0.01, -0.05]` ordered by `end_date`
- **WHEN** a client requests `GET /api/evaluation/temporal/3`
- **THEN** `rolling_brier_diff` values are `[-0.03, -0.01, -0.0233...]`

#### Scenario: Regime boundaries included
- **GIVEN** `bt_regimes` contains 6 regime records
- **WHEN** a client requests `GET /api/evaluation/temporal/3`
- **THEN** the `regimes` array contains all 6 records with `name`, `start_date`, and `end_date` (last regime has `end_date: null`)

#### Scenario: bt_regimes table does not exist
- **GIVEN** `backtest.db` exists but `bt_regimes` table has not been created
- **WHEN** a client requests `GET /api/evaluation/temporal/3`
- **THEN** the `regimes` array is empty and `trials` are still returned normally

### Requirement 6: Cross-run comparison endpoint
The dashboard SHALL expose `GET /api/evaluation/compare` returning a JSON object with a `runs` array. Each run object SHALL include: `run_id`, `started_at`, `model` (extracted via `json_extract(config, '$.model')`), `horizon` (extracted via `json_extract(config, '$.horizon')`), `trial_count`, `agent_brier`, `market_brier`, and `brier_diff`. Runs SHALL be ordered by `run_id` ascending. The endpoint SHALL accept optional `category` and `volume_tier` query parameters to filter the underlying trials before aggregation.

#### Scenario: Compare all runs unfiltered
- **GIVEN** 3 simulation runs exist
- **WHEN** a client requests `GET /api/evaluation/compare`
- **THEN** the response contains 3 run objects ordered by `run_id` ascending with aggregate Brier scores across all trials per run

#### Scenario: Filter by category
- **GIVEN** runs contain trials in categories `NULL` and `"Match Winner"`
- **WHEN** a client requests `GET /api/evaluation/compare?category=(null)`
- **THEN** only trials with `NULL` category are included in the per-run aggregates

#### Scenario: Filter by volume tier
- **GIVEN** runs contain trials across multiple volume tiers
- **WHEN** a client requests `GET /api/evaluation/compare?volume_tier=1M-10M`
- **THEN** only trials in the `1M-10M` volume tier (volume >= 1,000,000 AND volume < 10,000,000) are included in the per-run aggregates

#### Scenario: Filter produces no matching trials for a run
- **GIVEN** run_id 1 has no trials in the `>10M` tier
- **WHEN** a client requests `GET /api/evaluation/compare?volume_tier=>10M`
- **THEN** run_id 1 is omitted from the response (no entry with zero trials)

### Requirement 7: SQL injection prevention
All evaluation endpoints SHALL validate sort parameters against a server-side allowlist. Dynamic SQL construction SHALL only use allowlisted column references and parameterized queries for all user-supplied values.

#### Scenario: Malicious sort parameter
- **GIVEN** a valid run exists
- **WHEN** a client requests `GET /api/evaluation/trials/3?sort_by=1;DROP+TABLE+bt_simulation_trials`
- **THEN** the sort parameter is ignored and the default sort is applied; no SQL injection occurs

## Scenarios

### Scenario: End-to-end evaluation data flow
- **GIVEN** `backtest.db` contains run_id 3 with 20 trials joined to `bt_markets`
- **WHEN** the frontend fetches `/runs`, `/trials/3`, `/by-category/3`, `/by-volume-tier/3`, `/temporal/3`, and `/compare` in parallel
- **THEN** all 6 endpoints return consistent data derived from the same underlying trial records, with `brier_diff` values matching across summary and detail views

### Scenario: Concurrent read access
- **GIVEN** the agent's simulator is writing new trials to `backtest.db` via WAL mode
- **WHEN** the dashboard queries evaluation endpoints
- **THEN** the read-only connections succeed without blocking or errors due to WAL mode concurrent reader support
