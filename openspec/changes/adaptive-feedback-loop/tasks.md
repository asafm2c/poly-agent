## 1. Database Schema & Storage

- [x] 1.1 Add schema migration v2: create `price_snapshots` table with columns (id, market_id, timestamp, price_yes, price_no, volume) and composite index on (market_id, timestamp)
- [x] 1.2 Implement `insert_price_snapshots(markets)`: bulk insert price snapshots for a list of markets in a single transaction
- [x] 1.3 Implement `get_price_history(market_id, since=None)`: query snapshots for a market, optionally filtered by time, ordered by timestamp ascending
- [x] 1.4 Implement `get_latest_prices(market_ids)`: return dict mapping market_id to most recent price_yes for a set of markets
- [x] 1.5 Implement `cleanup_old_snapshots(retention_days)`: delete snapshots older than retention period, return count deleted
- [x] 1.6 Implement `upsert_daily_pnl(date, realized, unrealized, total, portfolio_value, trade_count)`: INSERT OR REPLACE into daily_pnl table
- [x] 1.7 Add `snapshot_retention_days: int = 30` to config.py

## 2. Resolution Detection

- [x] 2.1 Implement `_detect_resolutions(markets)` in scheduler: after upsert, find markets where resolved=True that have open positions or unresolved predictions
- [x] 2.2 Wire resolution detection into `_scan_job`: call `update_prediction_outcome()` with outcome mapping (YES→1.0, NO→0.0) and `resolve_positions()` for each resolved market
- [x] 2.3 Add exit trade recording to `resolve_positions()`: insert a sell trade in the trades table for each closed position
- [x] 2.4 Implement `get_open_position_market_ids()` and `get_unresolved_prediction_market_ids()` helper queries for efficient resolution checking

## 3. Price Snapshot Integration

- [x] 3.1 Wire `insert_price_snapshots()` into `_scan_job`: after market upsert, record snapshots for all fetched markets
- [x] 3.2 Wire `cleanup_old_snapshots()` into `_daily_report_job`

## 4. Position Re-evaluation

- [x] 4.1 Implement `get_prediction_for_position(market_id)`: retrieve the most recent prediction's agent_estimate for a given market
- [x] 4.2 Implement `compute_remaining_edge(position, original_estimate, current_price)`: compute remaining edge based on position side
- [x] 4.3 Implement paper exit method `exit_position(position_id, exit_price)`: close position at given price, compute P&L, credit cash, record sell trade
- [x] 4.4 Add `reeval_edge_exit_threshold: float = 0.0` and `max_reanalyses_per_cycle: int = 3` to config.py
- [x] 4.5 Rewrite `_reevaluation_job`: implement tiered decision framework (hold/exit/re-analyze) using edge computation, with LLM re-analysis cap
- [x] 4.6 Wire LLM re-analysis into re-evaluation: for ambiguous positions, run fresh `estimator.estimate()` and compare new estimate to market price

## 5. Daily P&L

- [x] 5.1 Implement daily P&L computation in `_daily_report_job`: compute realized (closed today), unrealized (mark-to-market via latest snapshots), total, portfolio value, trade count
- [x] 5.2 Wire `upsert_daily_pnl()` into `_daily_report_job` after computation
- [x] 5.3 Update daily report log output to include mark-to-market unrealized P&L

## 6. Testing

- [x] 6.1 Test price snapshot insert and query (bulk insert, time-windowed retrieval, latest prices)
- [x] 6.2 Test resolution detection: mock resolved market triggers prediction outcome update and position resolution
- [x] 6.3 Test re-evaluation edge computation: YES and NO positions, positive and negative edge
- [x] 6.4 Test paper exit at market price: correct P&L, cash credit, sell trade recorded
- [x] 6.5 Test daily P&L computation and persistence
- [x] 6.6 End-to-end test: scan with resolved market → positions closed → predictions updated → daily P&L written
