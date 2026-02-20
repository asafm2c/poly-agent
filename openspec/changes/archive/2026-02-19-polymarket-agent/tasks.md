## 1. Project Setup

- [x] 1.1 Initialize Python project with uv: pyproject.toml, src layout, .gitignore, .env.example
- [x] 1.2 Add core dependencies: py-clob-client, anthropic, tavily-python, click, rich, pydantic, apscheduler, httpx
- [x] 1.3 Create config module with Pydantic settings: API keys, risk limits, filter thresholds, schedule intervals (loaded from .env + config.yaml)
- [x] 1.4 Create SQLite database module with connection management and initial schema migration (markets, positions, trades, predictions tables)
- [x] 1.5 Create Pydantic data models: Market, Position, Trade, Prediction, ResearchDossier, TradeRecommendation, PortfolioSummary

## 2. Market Scanner

- [x] 2.1 Implement Gamma API client: fetch all active markets with metadata (title, description, category, end date, volume, liquidity)
- [x] 2.2 Implement CLOB API client: fetch current prices, midpoint, order book depth, and price history for a given market
- [x] 2.3 Implement market filter: configurable criteria for volume, liquidity, price range, time-to-resolution, category
- [x] 2.4 Implement market event detection: price movement threshold, volume spikes, new markets in tracked categories
- [x] 2.5 Implement market storage: save/update markets in SQLite, incremental updates on subsequent scans

## 3. Research Engine

- [x] 3.1 Implement Tavily search integration: query builder from market title/description, result parsing into structured format
- [x] 3.2 Implement Polymarket comment fetcher: retrieve recent comments via Gamma API, basic sentiment summary
- [x] 3.3 Implement related market discovery: find associated markets within the same event, fetch their prices
- [x] 3.4 Implement research dossier builder: aggregate all sources into a structured ResearchDossier model with caching (configurable max age)
- [x] 3.5 Implement domain source plugin interface: base class for category-specific research sources (politics, crypto), with stub implementations

## 4. Probability Estimator

- [x] 4.1 Implement Claude API wrapper: client setup, message construction, response parsing, cost tracking, error handling with retries
- [x] 4.2 Implement Haiku screening prompt: quick market assessment for mispicing potential, structured YES/NO output with brief reasoning
- [x] 4.3 Implement Pass 1 (base rate): prompt template that asks for reference class forecasting, parse probability + reasoning from response
- [x] 4.4 Implement Pass 2 (Bayesian update): prompt template with dossier + base rate, parse updated probability with itemized evidence shifts
- [x] 4.5 Implement Pass 3 (calibration adjustment): prompt template with calibration stats, parse adjusted probability (skip if insufficient data)
- [x] 4.6 Implement estimation pipeline: orchestrate screening → 3-pass analysis, produce structured ProbabilityEstimate output with all fields

## 5. Edge Calculator

- [x] 5.1 Implement edge computation: raw edge (estimate - market price), adjusted edge (incorporating confidence band)
- [x] 5.2 Implement half-Kelly position sizing: compute Kelly fraction from edge and odds, apply half-Kelly, enforce hard caps (per-market, portfolio)
- [x] 5.3 Implement trade recommendation builder: produce TradeRecommendation with market, direction, size, limit price, edge, reasoning
- [x] 5.4 Implement minimum edge threshold filter: configurable minimum adjusted edge to generate a recommendation

## 6. Risk Manager

- [x] 6.1 Implement per-market position limit check: reject or reduce trades exceeding per-market maximum
- [x] 6.2 Implement portfolio exposure limit check: reject trades that would push total exposure beyond maximum
- [x] 6.3 Implement category concentration limit check: reject trades that would exceed per-category exposure limit
- [x] 6.4 Implement daily loss limit tracking: track daily P&L, halt trading if threshold breached
- [x] 6.5 Implement pre-trade liquidity check: verify order book depth supports position size within slippage tolerance
- [x] 6.6 Implement kill switch: global halt flag that blocks all new order placement, with optional open order cancellation

## 7. Paper Trading

- [x] 7.1 Implement virtual portfolio: starting balance, cash tracking, position management in SQLite
- [x] 7.2 Implement virtual trade execution: record trades at market midpoint, update virtual cash and positions
- [x] 7.3 Implement position resolution: detect resolved markets, close virtual positions, record realized P&L
- [x] 7.4 Implement P&L calculation: realized P&L, unrealized P&L at current prices, total portfolio return
- [x] 7.5 Implement trade history log: complete audit trail of all virtual trades with query support

## 8. Calibration Tracker

- [x] 8.1 Implement prediction recording: store every estimate with market context, agent probability, market price, timestamp, category
- [x] 8.2 Implement outcome tracking: update predictions when markets resolve, compute prediction errors
- [x] 8.3 Implement calibration curve computation: bucket predictions by probability range, compute actual outcome rate per bucket, compute Brier score
- [x] 8.4 Implement category-level calibration: separate calibration stats per market category
- [x] 8.5 Implement calibration export for LLM: generate text summary of calibration biases for inclusion in Pass 3 prompts

## 9. Live Execution

- [x] 9.1 Implement py-clob-client integration: wallet setup, API credential derivation, token allowance checking
- [x] 9.2 Implement limit order placement: construct and sign orders, submit to CLOB, record order IDs
- [x] 9.3 Implement order status monitoring: poll or WebSocket for fill/cancel/expiry status, update positions on fill
- [x] 9.4 Implement order timeout and cancellation: cancel unfilled orders after configurable timeout
- [x] 9.5 Implement position exit: sell existing positions via CLOB sell orders
- [x] 9.6 Implement execution logging: full audit trail of all order state changes

## 10. CLI

- [x] 10.1 Set up Click CLI structure with main group and subcommands, Rich console for formatted output
- [x] 10.2 Implement `scan` command: run scanner, display filtered markets table
- [x] 10.3 Implement `analyze` command: run full pipeline on specific market, display estimate + edge + recommendation
- [x] 10.4 Implement `portfolio` command: display positions, P&L, portfolio summary
- [x] 10.5 Implement `trade` command: manual trade with confirmation prompt (paper or live mode)
- [x] 10.6 Implement `report` command: daily activity summary, calibration metrics
- [x] 10.7 Implement `run` command: start scheduler in paper or live mode
- [x] 10.8 Implement `kill` command: activate kill switch
- [x] 10.9 Implement `config` command: display current settings with masked API keys

## 11. Scheduler

- [x] 11.1 Implement APScheduler setup: configure scan interval, analysis interval, re-evaluation interval, daily report time
- [x] 11.2 Implement scan job: periodic market scanning and candidate flagging
- [x] 11.3 Implement analysis job: periodic deep analysis of flagged candidates, generate trade recommendations
- [x] 11.4 Implement re-evaluation job: periodic logging of open position status (stub — full re-analysis with exit signals not yet implemented)
- [x] 11.5 Implement daily report job: generate and log daily portfolio report
- [x] 11.6 Implement graceful shutdown: handle SIGTERM/SIGINT, complete in-progress cycle, stop cleanly
- [x] 11.7 Implement missed cycle detection: run immediately if a scheduled cycle was missed

## 12. Integration Testing

- [x] 12.1 End-to-end paper trading test: scan → research → estimate → edge → paper trade → track, verify full pipeline works
- [x] 12.2 Risk manager integration test: verify trades are correctly rejected when limits are breached
- [x] 12.3 Calibration pipeline test: create mock predictions with known outcomes, verify calibration curve computation
- [x] 12.4 CLI smoke tests: verify all commands execute without errors with test data

## 13. Post-Implementation Fixes

- [x] 13.1 Fix Gamma API comments endpoint: changed `asset_id` to `parent_entity_id` + `parent_entity_type=market`
- [x] 13.2 Fix market parser to use correct Gamma API fields: `outcomePrices`, `clobTokenIds`, `outcomes` instead of `tokens[].price`
- [x] 13.3 Add server-side volume/liquidity filtering to `fetch_all_active_markets()`: batch size 500, `volume_num_min`/`liquidity_num_min` params, MAX_PAGES=20 cap
- [x] 13.4 Add stale/extreme price warnings to CLI `analyze` command
- [x] 13.5 Fix `volumeNum` field parsing: prefer numeric `volumeNum` over string `volume`
- [x] 13.6 Fix database locked error during bulk market upsert: single-connection batch transactions + WAL mode + busy_timeout=30s
- [x] 13.7 Fix `find_related_markets()` to use `outcomePrices`/`outcomes` instead of old `tokens[].price` pattern
- [x] 13.8 Add non-binary market fallback: index 0=YES, 1=NO when outcomes aren't "YES"/"NO" (e.g. team names)
- [x] 13.9 Update all OpenSpec artifacts to match implementation (specs, design decisions, task accuracy)
