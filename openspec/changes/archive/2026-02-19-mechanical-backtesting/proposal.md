## Why

Our trading system has a tactical layer (scanner, estimator, adversarial pass, risk manager) but no strategic layer — no empirical foundation telling it *where* to look, *how much* edge to require, or *whether* the competitive landscape has shifted. Every parameter is a guess. Meanwhile, Polymarket has 30,000+ resolved markets with daily price histories available via free APIs, and the humans and LLM agents operating this system need a way to research markets, test hypotheses, and generate insights that feed back into trading decisions — without waiting months for forward predictions to resolve.

This change builds the strategic layer: a historical data foundation, a composable analysis library for research by humans and LLM agents, a strategy configuration that the tactical layer reads at runtime, and monitoring that detects when strategy assumptions drift from reality.

## What Changes

- Build a historical data collector that enumerates resolved markets from the Gamma API and fetches daily price histories from the CLOB API into a dedicated backtest SQLite database
- Implement a composable analysis library — functions for efficiency indexing, category calibration, momentum detection, cross-market arbitrage, and regime comparison — callable ad-hoc by humans (notebooks/CLI) or LLM agents (conversation/scripts)
- Introduce a strategy configuration file (`strategy.yaml`) that captures research findings and directives (target categories, per-category edge thresholds, regime assessment), consumed by the tactical layer at runtime
- Wire the tactical layer to read strategy config: market selection filters, edge threshold overrides, and regime awareness flags
- Enhance the daily report to monitor strategy drift: compare actual predict-mode performance against strategy expectations and flag divergence

## Capabilities

### New Capabilities
- `historical-data`: Collection, storage, and querying of resolved market data and daily price histories from Polymarket APIs into a dedicated backtest database
- `analysis-library`: Composable analysis functions for market research — efficiency indexing, category calibration, momentum, cross-market arbitrage, regime comparison — usable by humans and LLM agents in ad-hoc research sessions
- `strategy-config`: A YAML-based strategy configuration that captures research findings and trading directives, bridging the strategic layer (research/backtesting) to the tactical layer (live trading loop)

### Modified Capabilities
- `scheduler`: The scheduler reads `strategy.yaml` at startup to apply category targeting, per-category edge thresholds, and regime awareness flags. The daily report monitors actual performance against strategy expectations.

## Impact

- New code: `src/polymarket_agent/backtest/` package (collector, database, analysis library)
- New file: `strategy.yaml` — strategy configuration consumed by tactical layer
- New dependency: `pyyaml` for strategy config parsing
- New database: Separate `backtest.db` file — does not touch live `polymarket_agent.db`
- New CLI commands: `backtest collect`, `backtest analyze`
- Existing code modified: `config.py` (new settings), `cli/main.py` (new subcommands), `cli/scheduler.py` (reads strategy config), `trading/edge.py` (accepts category overrides from strategy config), daily report (strategy drift monitoring)
