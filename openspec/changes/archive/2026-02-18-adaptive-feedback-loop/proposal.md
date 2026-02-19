## Why

The trading agent currently operates as a feedforward pipeline: scan, analyze, trade, forget. It has no functioning feedback loops — predictions are never reconciled with outcomes, positions are never re-evaluated for exits, price history is overwritten on every scan, and the daily P&L table is never written. The calibration system (Pass 3) is fully built but permanently disabled because resolution detection is not wired into the scheduler. The system cannot observe its own performance, adapt its behavior, or manage positions after entry.

## What Changes

- **Price snapshot recording**: Capture market price time-series on every scan cycle instead of overwriting. Enables unrealized P&L tracking, edge decay analysis, and position monitoring.
- **Resolution detection**: Automatically detect when markets resolve during scan, close positions, record outcomes against predictions, and compute daily P&L. This activates the existing (but broken) calibration feedback loop.
- **Position re-evaluation with exit signals**: Replace the re-evaluation stub with real logic that computes remaining edge on open positions and generates exit signals when edge disappears or reverses.
- **Daily P&L tracking**: Wire up the dead `daily_pnl` table so the daily loss limit risk check actually functions.

## Capabilities

### New Capabilities
- `price-snapshots`: Append-only price history recording on every scan cycle, with query support for time-series retrieval per market
- `position-reeval`: Active position re-evaluation that computes remaining edge, detects edge decay/reversal, and generates exit or hold signals

### Modified Capabilities
- `scheduler`: New resolution detection step in scan job; real re-evaluation logic replaces stub; daily P&L recording in daily report job
- `calibration-tracker`: Wire `update_prediction_outcome()` into the resolution detection flow so the calibration loop closes automatically
- `paper-trading`: Auto-resolution of paper positions when markets resolve; exit trade recording
- `risk-manager`: Daily P&L table is now written, activating the daily loss limit circuit breaker

## Impact

- **Database schema**: New `price_snapshots` table. `daily_pnl` table starts being written.
- **Scheduler**: `_scan_job` gains resolution detection step. `_reevaluation_job` is rewritten from stub to real logic. `_daily_report_job` writes daily P&L.
- **Storage layer**: New functions for price snapshot insert/query, daily P&L upsert.
- **Paper trading**: `resolve_positions()` called automatically. Exit trades recorded in `trades` table.
- **Risk manager**: `_check_daily_loss()` becomes a live circuit breaker instead of dead code.
- **LLM cost**: Re-evaluation may trigger ~1-3 re-analyses per cycle at ~$0.025 each ($0.075/cycle, ~$0.45/day at 4h intervals). Configurable cap.
- **No new dependencies**: All changes use existing libraries (sqlite3, APScheduler, Anthropic SDK).
