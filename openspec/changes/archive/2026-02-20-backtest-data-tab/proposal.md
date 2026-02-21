## Why

When running backtests, there's no way to see what historical data the agent is operating against — how many markets exist, which categories, what volume distribution, what time period, and what fraction has price history. This makes it hard to trust evaluation results or know where coverage is sparse.

## What Changes

- Add a new **"Data" tab** to the dashboard (8th tab) showing corpus health metrics from `backtest.db`
- Add 4 new API endpoints under `/api/data/` serving summary KPIs, category breakdown, volume tier distribution, and temporal (resolution date) histogram
- New `routes/data.py` router following the existing pattern
- Grouped bar charts showing total markets vs. markets with price history — revealing coverage gaps by category and volume tier
- Resolution date histogram with LLM regime overlays, showing which eras the corpus spans

## Capabilities

### New Capabilities
- `backtest-corpus-ui`: Dashboard tab displaying backtest corpus statistics — KPI strip (total markets, history coverage %, date range, categories, volume range), category breakdown (grouped bars: total vs. has_history), volume tier distribution (grouped bars), and temporal histogram with regime overlays

### Modified Capabilities
<!-- No existing spec-level behavior changes; dashboard-api and dashboard-ui are extended but requirements are unchanged -->

## Impact

- `src/polymarket_dashboard/static/index.html`: nav button, content div, `refreshData()`, switch case
- `src/polymarket_dashboard/app.py`: import and register data router
- `src/polymarket_dashboard/routes/data.py`: new file, 4 endpoints reading from `backtest.db`
- Reads from `backtest.db` via existing `BacktestDB` class — soft-fails when DB missing
- No changes to agent operational DB or existing tabs
