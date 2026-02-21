## ADDED Requirements

### Requirement: Historical market collection from Gamma API
The system SHALL enumerate all resolved markets from the Gamma API (`closed=true`) with pagination and store their metadata in a dedicated backtest SQLite database. Collection SHALL be idempotent — re-running SHALL upsert existing markets and add new ones without duplicating data.

#### Scenario: Full collection run
- **WHEN** the `backtest collect` command is run for the first time
- **THEN** all resolved markets are fetched from Gamma API in batches of 500, parsed into market records with id, question, description, category, end_date, volume, resolution_outcome, and CLOB token IDs, and inserted into the `bt_markets` table

#### Scenario: Incremental collection
- **WHEN** `backtest collect` is run after a previous collection
- **THEN** only markets not already in the database have their price histories fetched, and existing market metadata is updated via upsert

#### Scenario: Market without CLOB tokens
- **WHEN** a resolved market has no `clobTokenIds` in the Gamma response
- **THEN** the market is stored with metadata but skipped for price history collection, and a warning is logged

### Requirement: Daily price history collection from CLOB API
The system SHALL fetch the full daily price history for each resolved market's YES token from the CLOB API (`/prices-history` with `interval=max`, `fidelity=1440`) and store the candles in the backtest database.

#### Scenario: Price history fetched for market
- **WHEN** a market has a valid YES token ID and no existing price history in the backtest DB
- **THEN** the system calls `/prices-history?market={token_id}&interval=max&fidelity=1440` and stores each candle (timestamp, price) in the `bt_price_history` table

#### Scenario: Empty price history response
- **WHEN** the CLOB API returns an empty history array for a market
- **THEN** the market is flagged as `has_history=false` in `bt_markets` and skipped in subsequent collection runs

#### Scenario: Rate limiting during collection
- **WHEN** the CLOB API returns HTTP 429 during price history collection
- **THEN** the collector backs off exponentially (starting at 1 second, max 60 seconds) and retries, logging the rate limit event

### Requirement: Backtest database schema
The backtest database SHALL use a separate SQLite file (`backtest.db`) with its own schema, independent of the live database. The schema SHALL include tables for markets, daily price candles, and regime tags.

#### Scenario: Database initialization
- **WHEN** `backtest collect` is run and `backtest.db` does not exist
- **THEN** the database is created with tables: `bt_markets` (id, question, description, category, end_date, volume, liquidity, resolution_outcome, yes_token, no_token, has_history, collected_at), `bt_price_history` (market_id, timestamp, price), and `bt_regimes` (name, start_date, end_date)

#### Scenario: Regime table seeded with model release dates
- **WHEN** the database is initialized
- **THEN** the `bt_regimes` table is populated with known regime boundaries: pre-GPT4 (before 2023-03-14), GPT4-era (2023-03-14 to 2024-03-04), Claude3-era (2024-03-04 to 2024-05-13), GPT4o-era (2024-05-13 to 2024-09-12), o1-era (2024-09-12 to 2025-06-25), and post-Claude4 (2025-06-25 onward)

### Requirement: Collection progress tracking and resumption
The system SHALL track collection progress so that interrupted runs can resume without re-fetching already-collected data. Every collection run SHALL be recorded in `bt_import_jobs` with progress counters updated per batch, enabling external observers (dashboard, CLI) to monitor status without blocking the collection process.

#### Scenario: Interrupted collection resumes
- **WHEN** collection is interrupted after fetching 5,000 of 30,000 markets' price histories
- **THEN** re-running `backtest collect` skips the 5,000 already-collected markets and continues with the remaining 25,000

#### Scenario: Collection progress logged
- **WHEN** collection is in progress
- **THEN** the system logs progress every 100 markets: "Collected 100/30000 markets (0.3%), 15 skipped (no tokens)"

#### Scenario: Collection progress written to bt_import_jobs
- **WHEN** collection is in progress
- **THEN** the `bt_import_jobs` row for the current run is updated with current `markets_done`, `histories_done`, `histories_skipped`, and `updated_at` at least every 50 records

#### Scenario: Job row status reflects terminal state
- **WHEN** collection completes successfully
- **THEN** the job row has `status='done'` and `completed_at` set

#### Scenario: Job row reflects cancellation via SIGTERM
- **WHEN** the collection process receives SIGTERM
- **THEN** the job row has `status='cancelled'` before the process exits

## ADDED Requirements (market-relevance-flag)

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
