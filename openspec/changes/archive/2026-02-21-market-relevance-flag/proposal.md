## Why

The backtest corpus contains 90K resolved markets but only a fraction are LLM-tractable
prediction markets — the rest are tick-crypto (83% of null-category), sports matchups,
and economic indicator buckets. Every query that selects markets for simulation,
evaluation, or hypothesis testing currently either ignores this problem (drawing biased
samples) or embeds fragile ad-hoc keyword logic. A persistent `market_type` column
computed once from deterministic rules eliminates duplication, makes filtering
consistent across all consumers, and enables stratified analysis by market type.

## What Changes

- Add `market_type TEXT` column to `bt_markets` with values:
  `prediction` | `tick` | `sports` | `economic-range` | `unknown`
- Implement `classify_market_type(question, category)` function using keyword +
  category rules (no LLM calls)
- One-time migration backfills `market_type` for all existing 90K markets
- Collection pipeline classifies new markets at insert time
- `backtest simulate` defaults to `market_type = 'prediction'` (overridable)
- `select_markets_stratified()` defaults to `market_type = 'prediction'` (overridable)
- `backtest evaluate` inherits the filter via `select_markets_stratified()`

## Capabilities

### New Capabilities
- `market-type-classification`: Deterministic rule-based classifier that assigns
  `market_type` to each market in `bt_markets`. Includes schema migration, backfill
  command, and reusable classify function called at collection time.

### Modified Capabilities
- `historical-data`: Schema gains `market_type` column; `backtest collect` calls
  classifier and stores result at insert time.
- `simulation-runner`: `select_markets()` gains `market_types` parameter defaulting
  to `['prediction']`; existing `--category` filter still applies as a secondary filter.
- `stratified-market-selection`: `select_markets_stratified()` gains `market_types`
  parameter defaulting to `['prediction']`.
- `backtest-cli`: `simulate` and `evaluate` subcommands expose `--market-type`
  option (repeatable) to override the default filter.

## Impact

- `src/polymarket_agent/backtest/database.py` — schema migration adding `market_type`
  column + index
- New module or function in `backtest/` — `classifier.py` with `classify_market_type()`
  and `backfill_market_types()`
- `src/polymarket_agent/backtest/simulator.py` — `select_markets()` and
  `select_markets_stratified()` updated with `market_types` parameter
- `src/polymarket_agent/cli/commands/` — `backtest simulate` and `backtest evaluate`
  gain `--market-type` option
- `backtest.db` — one-time column backfill (~90K rows, pure SQL, no API calls)
- No breaking changes to existing CLI options; new filter is additive with safe default
