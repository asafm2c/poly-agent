## 1. Schema & Database

- [x] 1.1 Add `bt_simulation_runs` and `bt_simulation_trials` tables to `backtest/database.py` SCHEMA_SQL
- [x] 1.2 Add indexes on `bt_simulation_trials(run_id)` and `bt_simulation_trials(market_id)`

## 2. Historical Context Builder

- [x] 2.1 Create `backtest/simulator.py` with `HistoricalResearchGatherer` class that implements the same interface as `ResearchGatherer` but returns a dossier built from backtest DB data only (price history summary, market metadata, no web search)
- [x] 2.2 Implement `_build_price_summary()` that truncates price history to horizon timestamp and computes: open, current (at horizon), high, low, 7d change, 30d change
- [x] 2.3 Implement `_build_historical_dossier()` that formats the price summary and market metadata into a `ResearchDossier`-compatible text string for the LLM

## 3. Simulation Runner Core

- [x] 3.1 Implement `select_markets()` function: query backtest DB with configurable filters (category, volume range, regime), random sample up to limit, return list of market dicts
- [x] 3.2 Implement `run_simulation()` function: create run record, iterate markets, construct context at horizon, invoke estimator with `HistoricalResearchGatherer`, compute Brier scores and edge, persist each trial
- [x] 3.3 Implement simulated P&L computation: Kelly sizing with $1000 bankroll, 2% round-trip fee deduction, trade only when edge > adaptive threshold
- [x] 3.4 Implement run completion: update `bt_simulation_runs` with aggregate metrics (agent Brier, market Brier, total P&L, total cost)
- [x] 3.5 Implement progress logging every 5 trials with running Brier scores and elapsed time
- [x] 3.6 Implement dry-run mode that selects markets and prints what would be simulated without calling LLM

## 4. Results & Reporting

- [x] 4.1 Add `simulation_summary()` to `backtest/analysis.py`: load run + trials, compute aggregate agent Brier, market Brier, brier diff, P&L, trade count, win rate, cost
- [x] 4.2 Add `simulation_by_category()` to `backtest/analysis.py`: group trials by market category, compute per-category metrics
- [x] 4.3 Add `simulation_by_volume_tier()` to `backtest/analysis.py`: group trials by volume tier (>10M, 1M-10M, 100K-1M, 10K-100K), compute per-tier metrics

## 5. CLI Commands

- [x] 5.1 Add `backtest simulate` command with options: `--horizon` (default 7), `--count` (default 50), `--category`, `--min-volume` (default 100000), `--max-volume`, `--regime`, `--dry-run`
- [x] 5.2 Add `backtest results` command with options: `--run-id` (default latest), shows Brier comparison, P&L summary, category breakdown, volume tier breakdown
- [x] 5.3 Wire simulate command to show Rich progress: trial N/total, running Brier, elapsed time, and summary table on completion

## 6. Testing

- [x] 6.1 Test `HistoricalResearchGatherer`: given a market dict and price history, produces a dossier with correct price summary truncated to horizon
- [x] 6.2 Test `select_markets()`: respects category, volume, and limit filters; returns random subset
- [x] 6.3 Test simulated P&L computation: correct Kelly sizing, fee deduction, and trade-side logic for YES and NO outcomes
- [x] 6.4 Test `simulation_summary()`: correct Brier aggregation and P&L totals from trial records
- [x] 6.5 Test `simulation_by_category()` and `simulation_by_volume_tier()`: correct grouping and metric computation
- [x] 6.6 Test schema: `bt_simulation_runs` and `bt_simulation_trials` tables created correctly with foreign keys
- [x] 6.7 Test dry-run mode: no LLM calls made, no DB records written, market list printed
- [x] 6.8 Test estimation error handling: trial recorded with NULL estimate, simulation continues
