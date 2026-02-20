## Why

The agent has a full estimation pipeline (screening, 4-pass LLM estimation, edge computation, Kelly sizing) and a backtest database with 90K+ resolved markets and growing price histories. But we have no way to answer the only question that matters: **would the agent have been profitable on historical markets?** All thresholds, parameters, and the estimation approach itself are unvalidated. Before risking real capital, we need empirical evidence that the LLM's base reasoning adds predictive value beyond what the market price already reflects.

## What Changes

- Add a simulation runner that selects historical markets from the backtest DB, constructs the context the agent would have seen at a configurable horizon before resolution, runs the actual estimation pipeline (with web search disabled to prevent future-knowledge contamination), and compares the agent's estimate against the market price and actual outcome
- Add a simulation results schema to persist each trial (market, horizon, agent estimate, market price, outcome, simulated P&L) for analysis
- Add a simulation report that computes agent Brier score vs market baseline Brier score, simulated P&L with fee deductions, accuracy by category/volume tier/regime, and identifies where the agent adds or destroys value
- Add CLI commands: `backtest simulate` to run trials, `backtest results` to display reports
- Adapt the estimation pipeline to accept a "historical mode" flag that disables web search and uses only the market question, description, category, resolution date, and price history as context — testing pure LLM reasoning

## Capabilities

### New Capabilities
- `simulation-runner`: Orchestrates historical simulation trials — market selection, context construction, estimation invocation, result persistence, and P&L computation
- `simulation-results`: Schema for persisting trial outcomes and reporting functions that compare agent vs market performance across dimensions

### Modified Capabilities
- `analysis-library`: Add functions to query and aggregate simulation results alongside existing market analysis

## Impact

- New module: `src/polymarket_agent/backtest/simulator.py` — simulation runner and context builder
- New tables in backtest DB: `bt_simulation_runs`, `bt_simulation_trials`
- Modified: `src/polymarket_agent/backtest/analysis.py` — new result aggregation functions
- Modified: `src/polymarket_agent/cli/main.py` — new `backtest simulate` and `backtest results` CLI commands
- Modified: `src/polymarket_agent/analyst/estimator.py` — accept historical mode flag to skip web search
- Dependencies: Uses existing Anthropic API (Claude calls cost ~$0.01-0.05 per market estimation)
- Cost consideration: Running 100 markets through the full estimation pipeline costs ~$1-5 in API fees
