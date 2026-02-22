## ADDED Requirements

### Requirement: --market-type option on collect subcommand
The `backtest collect` command MUST accept a repeatable `--market-type` option (Click `multiple=True`). When provided, the supplied types are passed as `market_types` to `collect_histories_only()`. When omitted, no filter is applied (all market types are collected), preserving existing behavior. The option MUST only affect the histories collection phase, not the market metadata collection phase.

#### Scenario: --market-type filters histories collection
- **WHEN** `polymarket backtest collect --histories-only --market-type prediction` is invoked
- **THEN** `collect_histories_only(market_types=['prediction'])` is called, skipping sports, tick, and economic-range markets

#### Scenario: --market-type repeatable for multiple types
- **WHEN** `polymarket backtest collect --histories-only --market-type prediction --market-type economic-range` is invoked
- **THEN** `collect_histories_only(market_types=['prediction', 'economic-range'])` is called

#### Scenario: omitting --market-type collects all types
- **WHEN** `polymarket backtest collect --histories-only` is invoked without `--market-type`
- **THEN** `collect_histories_only(market_types=None)` is called, and all market types with `has_history=0` are eligible

#### Scenario: --market-type is discoverable in help
- **WHEN** `polymarket backtest collect --help` is invoked
- **THEN** `--market-type` appears in the option list with a description such as "Restrict history collection to market type (repeatable)"
