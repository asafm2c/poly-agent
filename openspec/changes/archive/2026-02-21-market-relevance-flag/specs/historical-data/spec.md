## ADDED Requirements

### Requirement: market_type populated at collection time
When `backtest collect` inserts or upserts a market row into `bt_markets`, it MUST
call `classify_market_type(question, category)` and include the result in the INSERT
or UPDATE statement. Existing rows that already have `market_type` set MUST NOT have
their classification overwritten on a mere metadata refresh unless the question or
category field changed.

#### Scenario: New market inserted with market_type
- **WHEN** `backtest collect` fetches a resolved market not yet in the database
- **THEN** the row is inserted with `market_type` set to the output of `classify_market_type()`

#### Scenario: Existing market upserted — market_type preserved
- **WHEN** `backtest collect` encounters a market already in `bt_markets` with `market_type = 'prediction'`
- **THEN** the upsert updates volume, liquidity, and resolution_outcome but does NOT overwrite `market_type`
