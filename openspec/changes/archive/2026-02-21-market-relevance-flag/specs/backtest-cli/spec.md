## ADDED Requirements

### Requirement: backtest backfill subcommand
The CLI MUST register a `backtest backfill` command under the existing `backtest`
group. It MUST apply `classify_market_type()` to all rows in `bt_markets`, write
results to `market_type`, and print a summary of counts per type.

#### Scenario: backfill is discoverable
- **WHEN** `polymarket backtest --help` is invoked
- **THEN** `backfill` appears in the list of subcommands

#### Scenario: backfill completes with summary
- **WHEN** `polymarket backtest backfill` is run
- **THEN** all rows have `market_type` set and a Rich table showing count per type
  is printed to stdout

#### Scenario: --stats flag shows without re-classifying
- **WHEN** `polymarket backtest backfill --stats` is run
- **THEN** current `market_type` distribution is printed without modifying any rows

### Requirement: --market-type option on simulate subcommand
The `backtest simulate` command MUST accept a repeatable `--market-type` option
(Click `multiple=True`). When provided, the selected types are passed to
`select_markets()`. When omitted, the default `['prediction']` is used.

#### Scenario: --market-type option filters simulate
- **WHEN** `polymarket backtest simulate --market-type prediction --market-type economic-range` is invoked
- **THEN** `select_markets(market_types=['prediction', 'economic-range'])` is called

#### Scenario: simulate default uses prediction only
- **WHEN** `polymarket backtest simulate` is invoked without `--market-type`
- **THEN** `select_markets(market_types=['prediction'])` is called

### Requirement: --market-type option on evaluate subcommand
The `backtest evaluate` command MUST accept the same repeatable `--market-type`
option. When omitted, the default `['prediction']` is passed to
`select_markets_stratified()`.

#### Scenario: evaluate default uses prediction only
- **WHEN** `polymarket backtest evaluate` is invoked without `--market-type`
- **THEN** `select_markets_stratified(market_types=['prediction'])` is called
