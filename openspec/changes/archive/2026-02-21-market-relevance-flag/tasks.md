## 1. Schema Migration

- [x] 1.1 Add `ALTER TABLE bt_markets ADD COLUMN market_type TEXT` migration in `database.py` init, guarded by column existence check
- [x] 1.2 Add `CREATE INDEX IF NOT EXISTS idx_bt_markets_market_type ON bt_markets(market_type)` after column creation

## 2. Classifier Module

- [x] 2.1 Create `src/polymarket_agent/backtest/classifier.py` with `classify_market_type(question: str, category: str | None) -> str`
- [x] 2.2 Implement rule priority: tick → sports (category) → sports (vs. pattern) → economic-range (regex) → prediction
- [x] 2.3 Define `SPORTS_CATEGORIES` set and `SPORTS_CATEGORY_PREFIXES` tuple as module-level constants
- [x] 2.4 Write unit tests in `tests/test_backtest.py` covering all 7 classifier scenarios from the spec

## 3. Backfill Command

- [x] 3.1 Add `backtest backfill` Click command in `src/polymarket_agent/cli/commands/backtest.py`
- [x] 3.2 Implement backfill loop: SELECT all rows, classify, batch UPDATE `market_type`
- [x] 3.3 Print Rich summary table of counts per `market_type` after backfill
- [x] 3.4 Implement `--stats` flag: query and print current distribution without modifying rows

## 4. Collection Integration

- [x] 4.1 In `backtest collect` market insert/upsert path, call `classify_market_type(question, category)` and include result in INSERT
- [x] 4.2 Ensure upsert (ON CONFLICT) does NOT overwrite an existing `market_type` value

## 5. select_markets() Filter

- [x] 5.1 Add `market_types: list[str] | None = None` parameter to `select_markets()` in `simulator.py`
- [x] 5.2 When `market_types` is not None, append `AND market_type IN (...)` to the eligibility WHERE clause using parameterized query

## 6. select_markets_stratified() Filter

- [x] 6.1 Add `market_types: list[str] | None = None` parameter to `select_markets_stratified()` in `simulator.py`
- [x] 6.2 Apply `market_type IN (...)` filter in the per-cell candidate query when `market_types` is not None

## 7. CLI Options

- [x] 7.1 Add `--market-type` repeatable Click option to `backtest simulate` command; default to `['prediction']` at call site
- [x] 7.2 Add `--market-type` repeatable Click option to `backtest evaluate` command; default to `['prediction']` at call site
- [x] 7.3 Pass the resolved `market_types` list through to `select_markets()` / `select_markets_stratified()` respectively

## 8. Run Backfill & Verify

- [x] 8.1 Run `polymarket backtest backfill` against live `backtest.db`
- [x] 8.2 Run `polymarket backtest backfill --stats` and confirm distribution matches expectations (~28K tick, ~8K sports, ~5K economic-range, ~49K prediction)
- [x] 8.3 Spot-check `unknown` rows (if any) and update classifier rules if gaps found
