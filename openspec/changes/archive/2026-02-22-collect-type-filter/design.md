## Context

The `backtest collect --histories-only` command fetches CLOB price candles for all markets with `has_history=0`. Currently there is no way to restrict by `market_type`, so running a sub-$100K backfill would spend ~35K API calls on sports and tick markets we will never simulate.

The `market_type` column was added to `bt_markets` in the `market-relevance-flag` change and is populated for all 90K+ existing rows. The collector already has job tracking, exponential backoff, and a graceful SIGTERM handler. This change is a narrow filter extension.

## Goals / Non-Goals

**Goals:**
- Add optional `market_types` filter to the SQL candidate query in `_collect_price_histories()`, skipping markets with non-matching types
- Expose this as `--market-type` (repeatable) on `backtest collect` CLI, consistent with existing UX on `simulate` and `evaluate`
- No filter = current behavior (collect all types)

**Non-Goals:**
- Adding a `--max-volume` cap to the collect command (out of scope; all prediction markets above $100K already have history so it would have no practical effect)
- Changing the Gamma market metadata collection path
- Changing job type values or schema

## Decisions

**D1: No filter = collect all types (preserve existing behavior)**
The default when `--market-type` is omitted is `None` at the collector level, which omits the `AND market_type IN (...)` clause entirely. This means existing scripts and scheduled collection runs are unaffected. The `simulate`/`evaluate` commands default to `['prediction']` — but the collector should remain opt-in to avoid silently excluding types from future collection.

**D2: Filter applied in SQL, not Python**
The `market_type` value is already in `bt_markets`. Filtering at the SQL level avoids loading token IDs for markets we intend to skip, reducing memory and eliminating spurious CLOB calls.

**D3: Parameterized `IN` clause (no string interpolation)**
Use `",".join("?" * len(market_types))` with bound parameters, matching the pattern already used in `select_markets()` and `select_markets_stratified()`.

## Risks / Trade-offs

- [Risk] Operator runs `--histories-only --market-type prediction` and thinks all predictions are covered, but omits the volume lower bound → no practical problem since `has_history=0` already guards re-collection.
- [Risk] `market_type` is NULL for any rows (e.g., collected before the `market-relevance-flag` migration) → those rows would be excluded by the IN filter. Mitigation: the migration sets `market_type` for all existing rows; new inserts always classify. Log a warning if any NULL `market_type` rows exist at job start.

## Open Questions

_(none)_
