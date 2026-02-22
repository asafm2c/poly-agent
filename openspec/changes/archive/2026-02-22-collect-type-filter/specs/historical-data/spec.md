## ADDED Requirements

### Requirement: market_type filter on price history collection
The system SHALL support an optional `market_types` parameter on `collect_histories_only()` and `_collect_price_histories()`. When provided, ONLY markets whose `market_type` value is in the supplied list SHALL be candidates for price history collection. When omitted, all market types are eligible (preserving existing behavior).

#### Scenario: Filter to prediction markets only
- **WHEN** `collect_histories_only(market_types=['prediction'])` is called
- **THEN** only markets with `market_type = 'prediction'` AND `has_history = 0` are selected for CLOB calls; sports, tick, and economic-range markets are skipped

#### Scenario: No filter preserves existing behavior
- **WHEN** `collect_histories_only()` is called without a `market_types` argument
- **THEN** all markets with `has_history = 0` and a valid yes_token are candidates, regardless of market_type

#### Scenario: NULL market_type rows excluded by filter
- **WHEN** `market_types=['prediction']` is specified and some `bt_markets` rows have `market_type IS NULL`
- **THEN** those NULL rows are excluded from the candidate set (SQL `IN` filter does not match NULL)
