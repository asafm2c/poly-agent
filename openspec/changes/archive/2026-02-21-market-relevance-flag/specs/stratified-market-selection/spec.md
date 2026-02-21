## ADDED Requirements

### Requirement: market_types filter on select_markets_stratified()
`select_markets_stratified()` in `simulator.py` MUST accept a new optional parameter
`market_types: list[str] | None = None`. When not None, the eligibility query for
each (category, volume_tier) cell MUST include `WHERE market_type IN (...)`. When
None, no `market_type` filter is applied. The default at the CLI call site MUST be
`['prediction']`.

#### Scenario: Default stratified selection uses prediction filter
- **WHEN** `polymarket backtest evaluate` is invoked without `--market-type`
- **THEN** `select_markets_stratified()` is called with `market_types=['prediction']`
  and only `market_type = 'prediction'` rows are eligible for any cell

#### Scenario: market_types None disables filter
- **WHEN** `select_markets_stratified(market_types=None)` is called
- **THEN** the eligibility query has no `market_type` clause; all types are eligible

#### Scenario: market_types filter applies per cell
- **GIVEN** `select_markets_stratified(market_types=['prediction'])` is called
- **WHEN** building the candidate pool for the cell (category=None, tier="10K-100K")
- **THEN** only rows with `market_type = 'prediction'` are included in that cell's
  candidate pool, regardless of how many tick or sports markets exist in the same
  category/tier combination

#### Scenario: Backward compatibility — existing callers
- **WHEN** existing code calls `select_markets_stratified()` without `market_types`
- **THEN** behavior is identical to `market_types=None` (no market_type filter)
