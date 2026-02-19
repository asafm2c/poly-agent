## Context

The Polymarket trading agent has a tactical layer (scanner, estimator, adversarial pass, risk manager) but no strategic layer. Every parameter — which categories to target, how much edge to require, when to be skeptical — is a guess. The system needs an empirical foundation.

Two actors operate the strategic layer: a human (directing research, making judgment calls) and LLM agents (querying data, running analyses, generating narratives). Both need access to historical data and composable analysis tools. Their findings need to flow into the tactical layer as concrete directives, not just coefficients.

Polymarket exposes 30,000+ resolved markets with daily price candles via free, unauthenticated APIs. Empirical testing confirmed:
- ~30,500 resolved markets available (Gamma API, paginated at 500/page)
- Daily candles: consistently available, ~2-8KB per market
- Hourly candles: unreliable for markets older than ~30 days (API returns empty)
- No rate limit issues at 10+ req/s; total collection time ~2 hours
- Total dataset size: ~100-200MB
- No authentication required for any read endpoint

## Goals / Non-Goals

**Goals:**
- Collect all resolved Polymarket markets and their daily price histories into a local backtest database
- Provide composable analysis functions usable by humans (CLI, notebooks) and LLM agents (conversation, scripts)
- Answer key questions: Which categories are efficient? Where does alpha plausibly exist? Is efficiency increasing over time? How do different signals perform vs market baseline?
- Produce a strategy configuration file that the tactical layer reads at runtime — targeting rules, edge thresholds, regime awareness
- Monitor strategy assumptions against actual predict-mode performance and flag drift

**Non-Goals:**
- LLM-based backtesting (can't replay historical information environments)
- Order book backtesting (no historical book data exists)
- Autonomous strategy updates (research produces config proposals; human approves)
- Sub-daily granularity (hourly data is unreliable from CLOB API for older markets)
- On-chain data from Dune/The Graph (unnecessary complexity for this use case)
- Visualization / dashboards (analysis functions return data; plotting is left to notebooks or future work)

## Decisions

### D1: Three-loop architecture (research / strategy monitoring / tactical)

The system operates as three distinct loops:

**Research loop** (async, human + LLM agents): Queries backtest DB, runs analyses, generates insights, proposes strategy config updates. Triggered on-demand — during conversations, in notebooks, or via CLI.

**Strategy monitoring loop** (daily, automated): During the daily report, compares actual predict-mode Brier scores against strategy expectations. Flags drift. Does NOT auto-update strategy.

**Tactical loop** (every 15 min, automated): Existing scheduler. Reads `strategy.yaml` at startup for category targeting, edge thresholds, and regime flags. Never modifies strategy config.

*Alternative*: Single unified loop. Rejected — conflates deliberate research decisions with automated trading, and makes it impossible for humans to maintain strategic oversight.

### D2: Strategy config as YAML file

Strategy directives live in `strategy.yaml` — human-readable, version-controllable, editable by hand or by LLM agents. The tactical layer reads this on startup. Research sessions propose updates; human approves by reviewing the diff.

*Alternative*: Strategy in database tables. Rejected — harder to review, version, and approve changes. YAML is inspectable and diffable.

*Alternative*: Strategy baked into `config.py`. Rejected — config is for infrastructure settings (DB paths, API URLs, intervals). Strategy is for trading directives that change as research produces insights.

### D3: Composable analysis library, not rigid batch runner

Analysis functions are standalone, composable, and callable from any context (CLI, Python script, LLM agent tool call). Each function takes a dataframe or market set and returns structured results. No rigid "run all signals → produce report" pipeline.

Functions include: `load_markets()`, `efficiency_index()`, `category_calibration()`, `price_momentum()`, `cross_market_arbitrage()`, `market_baseline_brier()`, `regime_comparison()`.

*Alternative*: Batch runner with predefined signal pipeline. Rejected — too rigid for research. Humans and LLM agents need to ask ad-hoc questions, not run predefined jobs.

### D4: Separate backtest database

Store all historical data in `backtest.db`, separate from the live `polymarket_agent.db`. Can be deleted and rebuilt from APIs at any time.

*Alternative*: Shared database. Rejected — coupling live and backtest data creates migration risk.

### D5: Daily candle granularity only

Use `fidelity=1440` (daily candles) from the CLOB API. Empirical testing showed hourly data returns empty for markets older than ~30 days.

*Alternative*: Hourly with fallback. Rejected — inconsistent availability makes analysis unreliable.

### D6: Idempotent collection with progress tracking

`backtest collect` upserts markets and skips already-fetched price histories. Interrupted runs resume where they left off.

*Alternative*: One-shot collection. Rejected — markets resolve continuously; incremental updates are essential.

### D7: Market-price-as-predictor baseline

Every analysis compares against the null strategy: "use the market price as the prediction." A signal is only valuable if it beats this baseline. Aligns with the live system's `compute_brier_comparison()`.

### D8: Regime tagging for self-aware analysis

Each market is tagged with a "regime" based on resolution date relative to major model releases. All analysis functions accept regime filters. This enables the core question: "Is the market getting more efficient as LLMs improve?"

Known regimes: pre-GPT4 (before 2023-03-14), GPT4-era (2023-03-14 to 2024-03-04), Claude3-era (2024-03-04 to 2024-05-13), GPT4o-era (2024-05-13 to 2024-09-12), o1-era (2024-09-12 to 2025-06-25), post-Claude4 (2025-06-25 onward).

## Risks / Trade-offs

- [Survivorship bias] Cancelled/invalidated markets may not appear in Gamma's `closed=true` → Accept; note in analysis output. Cross-reference with on-chain data later if needed.
- [Stationarity] Historical patterns may not persist → Mitigated by regime tagging. If signals don't hold in recent regimes, we know.
- [Strategy staleness] `strategy.yaml` could become outdated if research doesn't run regularly → Strategy monitoring loop flags drift via daily report.
- [Human bottleneck] Strategy updates require human approval → Intentional. Autonomous strategy updates without oversight is more dangerous than slow updates.
- [API availability] Polymarket could rate-limit or change APIs → Collection is idempotent; can resume.
- [Daily granularity] Misses intraday dynamics → Accept for now; extend later if hourly data improves.
