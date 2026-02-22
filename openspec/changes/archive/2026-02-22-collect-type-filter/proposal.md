## Why

Price history collection currently has no `--market-type` filter: running `backtest collect --histories-only` on the sub-$100K tier would attempt CLOB calls for 23K sports and 29K tick markets, wasting API quota on data we will never simulate. We need to target prediction markets only when backfilling the $10K–$100K volume tier (~13K markets, 4–8 hours of collection).

## What Changes

- Add `market_types: list[str] | None` parameter to `_collect_price_histories()` and `collect_histories_only()` in `collector.py`, adding `AND market_type IN (...)` to the candidate SQL query
- Add `--market-type` repeatable CLI option to `backtest collect`, defaulting to no filter (collect all types) to preserve existing behavior
- Wire `--market-type` through to `collect_histories_only()` call site

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `historical-data`: Price history collection now supports an optional market_type filter at both the API level and CLI level
- `backtest-cli`: `backtest collect` gains a `--market-type` repeatable option (same UX as `simulate` and `evaluate`)

## Impact

- `src/polymarket_agent/backtest/collector.py` — `_collect_price_histories()`, `collect_histories_only()`
- `src/polymarket_agent/cli/main.py` — `backtest collect` command
- No schema changes, no new tables, no breaking changes
- Existing `collect` behavior unchanged when `--market-type` is omitted
