## Purpose

Provides deterministic rule-based classification of backtest markets into types
(`prediction`, `tick`, `sports`, `economic-range`, `unknown`) stored as a persistent
`market_type` column on `bt_markets`. Eliminates ad-hoc per-query exclusion logic
and enables consistent filtering across simulation, evaluation, and hypothesis testing.

## Requirements

### Requirement: market_type column on bt_markets
The `bt_markets` table MUST have a `market_type TEXT` column. The column MUST be
nullable (to support rows inserted before classification). An index MUST exist on
`market_type` for efficient WHERE filtering.

#### Scenario: Schema after migration
- **WHEN** `backtest.db` is opened after the migration runs
- **THEN** `bt_markets` has a `market_type` column and `idx_bt_markets_market_type` index exists

#### Scenario: Pre-migration rows are nullable
- **WHEN** a row exists in `bt_markets` before `backtest backfill` is run
- **THEN** `market_type` IS NULL for that row

### Requirement: classify_market_type() function
A function `classify_market_type(question: str, category: str | None) -> str` MUST
exist in `src/polymarket_agent/backtest/classifier.py`. It MUST apply rules in the
following priority order and return the first match:

1. **tick** — `question` contains the substring `"Up or Down"` (case-sensitive)
2. **sports** — `category` is one of the known sports categories OR `question` contains `" vs."`:
   - Known sports categories: `"Match Winner"`, `"Game 1 Winner"`, `"Game 2 Winner"`,
     `"Map 1 Winner"`, `"Map 2 Winner"`, `"Both Teams to Score"`, or any value
     starting with `"Spread"` or `"O/U"`
3. **economic-range** — `category` is not None and matches regex `^\d[\d,.\- ]*$`
   (starts with a digit, followed by only digits, commas, periods, hyphens, spaces)
4. **prediction** — all remaining markets (default)
5. **unknown** — defensive fallback if no rule matches (should not occur)

#### Scenario: Tick market classified correctly
- **WHEN** `classify_market_type("Bitcoin Up or Down - 3:15PM ET", None)` is called
- **THEN** returns `"tick"`

#### Scenario: Sports by category
- **WHEN** `classify_market_type("Chelsea vs Arsenal", "Match Winner")` is called
- **THEN** returns `"sports"`

#### Scenario: Sports by question pattern (null category)
- **WHEN** `classify_market_type("Birrell vs. Bhamidipaty", None)` is called
- **THEN** returns `"sports"`

#### Scenario: Spread category is sports
- **WHEN** `classify_market_type("Cowboys -3.5", "Spread -3.5")` is called
- **THEN** returns `"sports"`

#### Scenario: Economic range by category
- **WHEN** `classify_market_type("NFP report", "88,000-90,000")` is called
- **THEN** returns `"economic-range"`

#### Scenario: Legitimate prediction market
- **WHEN** `classify_market_type("Will Trump sign the tariff bill by March?", None)` is called
- **THEN** returns `"prediction"`

#### Scenario: Priority: tick beats sports
- **WHEN** `classify_market_type("BTC Up or Down vs ETH", "Match Winner")` is called
- **THEN** returns `"tick"` (tick rule checked first)

### Requirement: backtest backfill subcommand
The CLI MUST register a `backtest backfill` command that applies `classify_market_type()`
to all rows in `bt_markets` and writes the result to `market_type`. The command MUST
be idempotent (re-running overwrites existing classifications). It MUST print a summary
of counts per `market_type` after completing.

#### Scenario: Backfill runs successfully
- **WHEN** `polymarket backtest backfill` is run
- **THEN** all rows in `bt_markets` have `market_type` set (no NULLs remain), and a
  summary table is printed showing count per type

#### Scenario: Backfill is idempotent
- **WHEN** `polymarket backtest backfill` is run a second time
- **THEN** the results are identical to the first run; no errors occur

#### Scenario: Stats flag shows distribution
- **WHEN** `polymarket backtest backfill --stats` is run (with or without re-classifying)
- **THEN** counts per `market_type` are printed without re-running classification

### Requirement: Classify at collection time
When `backtest collect` inserts a new market row into `bt_markets`, it MUST call
`classify_market_type(question, category)` and store the result in `market_type`.

#### Scenario: New market classified on insert
- **WHEN** `backtest collect` fetches a resolved market and inserts it
- **THEN** the inserted row has `market_type` populated (not NULL)
