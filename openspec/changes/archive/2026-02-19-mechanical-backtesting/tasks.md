## 1. Backtest Database & Schema

- [x] 1.1 Create `src/polymarket_agent/backtest/` package with `__init__.py`
- [x] 1.2 Create `backtest/database.py` with backtest DB schema: `bt_markets` (id, question, description, category, end_date, volume, liquidity, resolution_outcome, yes_token, no_token, has_history, collected_at), `bt_price_history` (market_id, timestamp, price), `bt_regimes` (name, start_date, end_date). WAL mode, foreign keys.
- [x] 1.3 Seed `bt_regimes` table on init with model release boundaries: pre-GPT4, GPT4-era, Claude3-era, GPT4o-era, o1-era, post-Claude4
- [x] 1.4 Add `backtest_db_path` and `strategy_config_path` settings to `config.py`

## 2. Historical Data Collector

- [x] 2.1 Create `backtest/collector.py` with `BacktestCollector` class that paginates Gamma API for all resolved markets (`closed=true`, batches of 500)
- [x] 2.2 Parse Gamma responses into `bt_markets` rows with upsert logic (ON CONFLICT UPDATE metadata, preserve `collected_at`)
- [x] 2.3 Implement CLOB price history fetching per market (`interval=max`, `fidelity=1440`) into `bt_price_history`
- [x] 2.4 Add rate limiting with exponential backoff on HTTP 429 (start 1s, max 60s)
- [x] 2.5 Add progress tracking: skip markets with existing price history, log every 100 markets
- [x] 2.6 Handle edge cases: no CLOB tokens (flag `has_history=false`), empty history responses, API errors

## 3. Analysis Library — Core Functions

- [x] 3.1 Create `backtest/analysis.py` with `load_markets()` — query backtest DB with optional filters (category, regime, volume range, date range), return list of dicts with metadata + price history
- [x] 3.2 Implement `get_regime()` helper — given a resolution date, return the regime name from `bt_regimes`
- [x] 3.3 Implement `get_price_at_horizon()` helper — given a market's price history and a horizon (days before resolution), return the price at that point (or None if insufficient data)
- [x] 3.4 Implement `market_baseline_brier(markets, horizon)` — Brier score of market price at horizon vs actual outcome

## 4. Analysis Library — Signal Functions

- [x] 4.1 Implement `efficiency_index(markets, horizons=[30, 7, 1])` — mean |price_at_horizon - outcome| per horizon, returns dict of horizon → efficiency score
- [x] 4.2 Implement `category_calibration(markets)` — per-category avg price vs avg outcome, returns dict of category → {avg_price, avg_outcome, bias, count}
- [x] 4.3 Implement `price_momentum(markets, lookback_days=7, horizon=7)` — price change over lookback window at measurement point, returns per-market momentum scores
- [x] 4.4 Implement `cross_market_arbitrage(markets)` — group by event_id, compute sum of YES prices, flag events deviating from 1.0. Returns list of {event_id, market_count, price_sum, deviation}
- [x] 4.5 Implement `regime_comparison(analysis_fn, **kwargs)` — run any analysis function across all regimes, return regime → result dict

## 5. Strategy Configuration

- [x] 5.1 Define `strategy.yaml` schema: version, updated_at, updated_by, market_selection (target_categories, avoid_categories, volume_range, days_to_resolution), edge_thresholds (category_overrides, default, floor, ceiling), regime_awareness (current_regime, efficiency_trend, agent_confidence), insights (list of {date, finding, confidence, source, implication})
- [x] 5.2 Create `backtest/strategy.py` with `load_strategy_config()` — load and validate YAML, return structured dict. If file missing, return defaults.
- [x] 5.3 Implement `create_default_strategy_config()` — write a default `strategy.yaml` with conservative values
- [x] 5.4 Implement `update_strategy_config(path, **changes)` — merge changes into existing YAML, increment version, update timestamp, append insight if provided
- [x] 5.5 Add `pyyaml` dependency to project

## 6. Tactical Layer Integration

- [x] 6.1 In `AgentScheduler.__init__()`, load `strategy.yaml` via `load_strategy_config()` and log active strategy (categories, thresholds, regime)
- [x] 6.2 In `_scan_job()` or `_analysis_job()`, apply `target_categories` and `avoid_categories` filters to candidate markets before screening
- [x] 6.3 In `compute_required_edge()`, accept optional `strategy_config` parameter; if category has an override in `edge_thresholds.category_overrides`, use it as base threshold
- [x] 6.4 In `_daily_report_job()`, add strategy drift monitoring: compare per-category Brier scores against strategy expectations, log warnings when divergence exceeds 0.05

## 7. CLI Integration

- [x] 7.1 Add `backtest` command group to `cli/main.py` using Click
- [x] 7.2 Implement `backtest collect` subcommand — runs collector, shows progress, reports final counts
- [x] 7.3 Implement `backtest analyze` subcommand with `--category`, `--regime`, `--horizon` options — runs selected analyses, prints results to stdout
- [x] 7.4 Implement `backtest strategy` subcommand — prints current `strategy.yaml` contents and last update info

## 8. Testing

- [x] 8.1 Test backtest DB initialization: schema created, regimes seeded correctly
- [x] 8.2 Test collector: mock Gamma/CLOB responses, verify upsert behavior, progress tracking, edge case handling
- [x] 8.3 Test `load_markets()` filtering: by category, regime, volume range
- [x] 8.4 Test `efficiency_index()` with synthetic price histories: known prices at known horizons, verify correct deviation computation
- [x] 8.5 Test `category_calibration()` with synthetic markets: known bias should be detected
- [x] 8.6 Test `price_momentum()` with known price trajectories
- [x] 8.7 Test `cross_market_arbitrage()` with multi-market events: overpriced events flagged
- [x] 8.8 Test `regime_comparison()`: verify it runs analysis fn per regime correctly
- [x] 8.9 Test `market_baseline_brier()` against hand-computed Brier scores
- [x] 8.10 Test strategy config: load, update, defaults, version increment
- [x] 8.11 Test tactical integration: scheduler applies category filters and edge overrides from strategy config
- [x] 8.12 Test strategy drift monitoring: flag when Brier diverges from expectations
