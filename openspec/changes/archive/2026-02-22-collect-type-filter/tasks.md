## 1. Collector — market_types filter

- [x] 1.1 Add `market_types: list[str] | None = None` parameter to `_collect_price_histories()` in `collector.py`; append `AND market_type IN (...)` to the candidate SQL query when provided, using parameterized placeholders
- [x] 1.2 Add `market_types: list[str] | None = None` parameter to `collect_histories_only()` and pass it through to `_collect_price_histories()`

## 2. CLI — --market-type on backtest collect

- [x] 2.1 Add `@click.option("--market-type", "market_types", multiple=True, help="Restrict history collection to market type (repeatable).")` to the `backtest collect` command in `main.py`
- [x] 2.2 Pass `market_types=list(market_types) if market_types else None` to `collect_histories_only()` at the CLI call site

## 3. Tests

- [x] 3.1 Add unit test: `collect_histories_only` with `market_types=['prediction']` generates SQL containing `market_type IN (?)` (can mock DB or inspect query string)
- [x] 3.2 Add unit test: `collect_histories_only` without `market_types` generates SQL without any `market_type` filter

## 4. Collection run

- [x] 4.1 Run `uv run polymarket backtest collect --histories-only --market-type prediction` in the background to backfill ~13K prediction markets in the sub-$100K tier
