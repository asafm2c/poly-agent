## ADDED Requirements

### Requirement: market_types filter on select_markets()
`select_markets()` in `simulator.py` MUST accept a new optional parameter
`market_types: list[str] | None = None`. When `market_types` is not None, the SQL
query MUST include a `WHERE market_type IN (...)` clause using the provided values.
When `market_types` is None, no `market_type` filter is applied (all types returned).
The default value in the public-facing CLI path MUST be `['prediction']`, set at the
call site in the CLI command (not hardcoded in the function signature, to preserve
testability with no filter).

#### Scenario: Default CLI path filters to prediction
- **WHEN** `polymarket backtest simulate` is invoked without `--market-type`
- **THEN** `select_markets()` is called with `market_types=['prediction']` and only
  `market_type = 'prediction'` rows are eligible for selection

#### Scenario: Explicit market-type override
- **WHEN** `polymarket backtest simulate --market-type sports --market-type tick` is invoked
- **THEN** `select_markets()` is called with `market_types=['sports', 'tick']`

#### Scenario: No filter when market_types is None
- **WHEN** `select_markets(market_types=None)` is called directly (e.g., from tests)
- **THEN** the query has no `market_type` WHERE clause and all market types are eligible

#### Scenario: Backward compatibility — existing callers
- **WHEN** existing code calls `select_markets()` without the `market_types` parameter
- **THEN** behavior is identical to passing `market_types=None` (no filter applied)
