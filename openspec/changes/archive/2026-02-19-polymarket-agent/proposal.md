## Why

Polymarket is the largest prediction market, where prices represent crowd-estimated probabilities of real-world events. LLMs have a unique edge here: they can synthesize vast unstructured information (news, filings, polls, domain data) into calibrated probability estimates faster and more broadly than any human trader. This creates an opportunity to build an autonomous agent that identifies mispriced markets and trades on informational edge — starting with politics and crypto categories where research sources are richest and coverage gaps are widest.

## What Changes

- Build a market scanner that discovers and filters tradeable Polymarket markets via the Gamma and CLOB APIs
- Build a research engine that gathers relevant information per market (web search via Tavily, Polymarket comments, domain-specific sources)
- Build an LLM-powered probability estimator using Claude API with a three-pass approach (base rate, Bayesian update, calibration check)
- Build an edge calculator with Kelly criterion position sizing
- Build a paper trading system that simulates trades and tracks P&L against live market data
- Build a calibration tracker that records all predictions vs outcomes to measure and improve accuracy over time
- Build a risk manager enforcing position limits, portfolio exposure limits, and loss limits
- Build a live execution engine using py-clob-client for real CLOB order placement
- Build a CLI interface for operating the system (scan, analyze, trade, report)
- Build a scheduler to orchestrate periodic scanning, analysis, and portfolio re-evaluation

## Capabilities

### New Capabilities
- `market-scanner`: Discover, filter, and track active Polymarket markets via Gamma and CLOB APIs
- `research-engine`: Gather and structure per-market research dossiers from web search, Polymarket data, and domain sources
- `probability-estimator`: LLM-powered three-pass probability estimation with structured reasoning output
- `edge-calculator`: Compute expected edge, Kelly sizing, and trade decisions from agent estimates vs market prices
- `paper-trading`: Simulate trades against live markets, track virtual portfolio and P&L
- `calibration-tracker`: Record predictions vs outcomes, compute calibration curves, feed accuracy data back to the estimator
- `risk-manager`: Enforce per-market, per-category, and portfolio-level risk limits with kill switch
- `live-execution`: Place and manage real orders on Polymarket via the CLOB API (py-clob-client)
- `cli`: Command-line interface for operating the agent (scan, analyze, trade, report, status)
- `scheduler`: Orchestrate periodic market scanning, re-evaluation, and portfolio management

### Modified Capabilities
<!-- None — greenfield project, no existing specs -->

## Impact

- **New project**: Entire Python codebase created from scratch
- **Dependencies**: py-clob-client (Polymarket SDK), anthropic (Claude API), tavily-python (web search), SQLite (storage), APScheduler (scheduling)
- **External APIs**: Polymarket Gamma API, Polymarket CLOB API, Polymarket WebSocket, Claude API, Tavily Search API
- **Infrastructure**: Runs on local Proxmox host, needs Polygon wallet with USDC for live trading
- **Cost**: Claude API usage (~$200-400/month estimated), Tavily API usage (~$20-50/month estimated)
