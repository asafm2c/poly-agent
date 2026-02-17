# Agentic Quantitative Trading System

## Problem

Manual trading can't compete with systematic approaches at scale. Retail quant tools are either black-box SaaS or require massive infrastructure. There's a gap for a self-hosted, agentic system that autonomously discovers, validates, and executes trading strategies across markets — with strong risk controls and full transparency.

## Vision

An autonomous trading platform where AI agents:
1. Ingest real-time and historical market data
2. Generate trading hypotheses
3. Backtest and validate strategies
4. Paper trade to prove viability
5. Execute live trades with strict risk guardrails

All components API-accessible. All decisions auditable.

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   Orchestrator Agent                 │
│            (strategy lifecycle manager)              │
└──────┬──────────┬──────────┬──────────┬─────────────┘
       │          │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌──▼───┐ ┌───▼──────┐
  │  Data  │ │Hypothe-│ │Back- │ │Execution │
  │Pipeline│ │sis Eng.│ │tester│ │  Engine   │
  └────┬───┘ └───┬────┘ └──┬───┘ └───┬──────┘
       │         │         │         │
  ┌────▼─────────▼─────────▼─────────▼────────┐
  │              Shared Data Store             │
  │    (market data, positions, strategies)    │
  └────────────────────────────────────────────┘
```

## Components

### 1. Data Pipeline

**Purpose:** Continuous ingestion and normalization of market data.

- **Sources:** Exchange APIs (Alpaca, Polygon, Binance), news feeds, alternative data
- **Storage:** Time-series DB (TimescaleDB or QuestDB) for OHLCV, order book snapshots
- **Interface:** Internal REST/gRPC API for all other components
- **Requirements:**
  - Sub-second latency for real-time feeds
  - Historical data backfill (5+ years for backtesting)
  - Normalized schema across asset classes (equities, crypto, forex)

### 2. Hypothesis Engine

**Purpose:** Agents autonomously generate and structure trading hypotheses.

- **Inputs:** Market data, technical indicators, macro signals, sentiment
- **Process:**
  1. Agent observes patterns or anomalies in data
  2. Formulates a structured hypothesis (entry/exit conditions, timeframe, expected edge)
  3. Assigns confidence score and required validation criteria
  4. Submits to backtesting pipeline
- **Hypothesis Schema:**
  ```json
  {
    "id": "hyp-001",
    "name": "Mean Reversion on RSI Extremes",
    "asset_classes": ["us_equities"],
    "timeframe": "1d",
    "entry": { "condition": "RSI(14) < 30", "type": "long" },
    "exit": { "condition": "RSI(14) > 50 OR stop_loss(-2%)" },
    "expected_edge": "0.3% per trade",
    "min_sample_size": 200,
    "status": "proposed"
  }
  ```
- **Iteration:** Agents can refine hypotheses based on backtest results (parameter tuning, filter additions)

### 3. Backtesting Engine

**Purpose:** Validate hypotheses against historical data before any capital allocation.

- **Features:**
  - Event-driven simulation (not vectorized — handles slippage, fills, partial orders)
  - Transaction cost modeling (commissions, spread, market impact)
  - Walk-forward validation (no lookahead bias)
  - Monte Carlo analysis for robustness
  - Out-of-sample testing (train/validate/test splits)
- **Output:** Strategy report with Sharpe, max drawdown, win rate, profit factor, equity curve
- **Gate:** Strategy must pass minimum criteria before advancing to paper trading

### 4. Paper Trading Engine (Internal)

**Purpose:** Forward-test strategies in real-time without risking capital.

- **Not** a third-party paper trading platform — fully internal simulation
- Tracks hypothetical positions, P&L, and fills against live market data
- Maintains a virtual portfolio with realistic execution assumptions
- **Duration:** Configurable (e.g., 30-90 days minimum before live consideration)
- **Tracking:**
  ```
  paper_trades/
  ├── strategy-001/
  │   ├── positions.jsonl      # position log
  │   ├── trades.jsonl         # executed trades
  │   ├── equity_curve.json    # daily snapshots
  │   └── report.md            # performance summary
  ```
- **Promotion criteria:** Defined per strategy (min Sharpe, max drawdown, min trades)

### 5. Execution Engine

**Purpose:** Execute validated strategies with real capital.

- **Broker integration:** Alpaca (equities), Binance/Kraken (crypto) via unified interface
- **Order types:** Market, limit, stop-loss, trailing stop
- **Features:**
  - Smart order routing
  - Position sizing (Kelly criterion or fixed-fraction)
  - Slippage monitoring (expected vs actual)

### 6. Risk Management

**Purpose:** Prevent catastrophic losses. Non-negotiable.

- **Portfolio-level:**
  - Max daily drawdown (e.g., -2% → halt all trading)
  - Max total drawdown (e.g., -10% → liquidate and pause)
  - Max correlation between active strategies
  - Max allocation per strategy / asset class
- **Strategy-level:**
  - Per-trade stop loss (hard limit)
  - Max position size
  - Max concurrent positions
  - Cooldown after consecutive losses
- **System-level:**
  - Kill switch (manual and automated)
  - Circuit breaker on unusual market conditions (VIX spike, flash crash detection)
  - All risk checks enforced at execution layer (not advisory)
- **Alerts:** Telegram notifications for risk events, position changes, anomalies

### 7. Orchestrator Agent

**Purpose:** Manages the lifecycle of strategies from hypothesis to live trading.

- Monitors all active strategies (paper and live)
- Promotes/demotes strategies based on performance
- Allocates capital across strategies
- Generates daily reports
- Can pause/resume strategies autonomously within defined parameters

## Technology Stack (Proposed)

| Layer | Tech | Rationale |
|-------|------|-----------|
| Language | Python | Ecosystem (pandas, numpy, scipy, ML libs) |
| Data Store | TimescaleDB | Time-series optimized PostgreSQL |
| Message Queue | Redis Streams | Low-latency event pipeline |
| API | FastAPI | Async, typed, fast |
| Agent Framework | LangGraph or custom | Structured agent orchestration |
| Broker API | CCXT (crypto) + Alpaca SDK | Unified multi-exchange |
| Monitoring | Grafana + Prometheus | Dashboards, alerting |
| Deployment | Docker Compose → K8s | Start simple, scale later |

## Phases

### Phase 0: Foundation (2-3 weeks)
- [ ] Set up repo structure, CI, dev environment
- [ ] Deploy TimescaleDB + Redis
- [ ] Build data pipeline for 1 source (Alpaca or Binance)
- [ ] Historical data backfill for 1 asset class

### Phase 1: Backtest Loop (2-3 weeks)
- [ ] Implement backtesting engine (event-driven)
- [ ] Define hypothesis schema and storage
- [ ] Build 3-5 classic strategies manually (mean reversion, momentum, pairs)
- [ ] Validate backtester against known results

### Phase 2: Paper Trading (2 weeks)
- [ ] Internal paper trading engine (live data, simulated execution)
- [ ] Position and P&L tracking
- [ ] Daily reporting
- [ ] Deploy 2-3 backtested strategies in paper mode

### Phase 3: Agentic Hypothesis Generation (2-3 weeks)
- [ ] LLM-powered hypothesis engine
- [ ] Autonomous strategy iteration based on backtest results
- [ ] Agent guardrails (hypothesis rate limiting, novelty checks)

### Phase 4: Live Trading (1-2 weeks)
- [ ] Broker integration (start with small capital, one broker)
- [ ] Full risk management stack
- [ ] Kill switch and alerting
- [ ] Promotion pipeline (paper → live)

### Phase 5: Scale & Optimize (ongoing)
- [ ] Additional data sources and asset classes
- [ ] Advanced strategies (ML-based signals, alternative data)
- [ ] Performance optimization (latency, throughput)
- [ ] Multi-broker support

## Open Questions

- **Which markets first?** US equities (most accessible, Alpaca free tier) vs crypto (24/7, more volatile, lower barriers)
- **Agent framework:** Custom orchestration vs LangGraph vs CrewAI?
- **Capital allocation:** How much to start with? Suggest $1-5k initial for live phase
- **Regulatory:** Any broker restrictions or tax implications to research upfront?
- **Hosting:** Local (Proxmox) vs cloud? Latency matters for some strategies

## Success Criteria

1. **Paper trading** shows positive risk-adjusted returns over 60+ days
2. **At least 3 strategies** running concurrently with uncorrelated returns
3. **Risk system** successfully prevents drawdown beyond defined limits
4. **Agentic loop** generates at least 1 viable strategy without manual intervention
5. **Live trading** achieves positive returns net of costs over first quarter

---

*Created: 2026-02-15 | Status: Proposal*
