## Context

This is a greenfield Python project building an autonomous Polymarket trading agent. The agent uses Claude (Anthropic API) to synthesize information and estimate probabilities for prediction market outcomes, then trades when it detects mispricing.

Polymarket operates a hybrid-decentralized CLOB (Central Limit Order Book) on Polygon. Orders are signed off-chain (EIP-712), matched by an operator, and settled on-chain via the CTF Exchange contract. Collateral is USDC.e on Polygon.

The project runs self-hosted on a Proxmox LXC container (Debian 13). No cloud infrastructure.

**Key APIs:**
- Gamma API (`gamma-api.polymarket.com`) — market discovery, metadata, free/public
- CLOB API (`clob.polymarket.com`) — prices, order books, order placement
- CLOB WebSocket (`ws-subscriptions-clob.polymarket.com`) — real-time order book updates
- Claude API (Anthropic) — LLM analysis and probability estimation
- Tavily API — web search for research gathering

**Official SDK:** `py-clob-client` — Python SDK for CLOB interaction, order signing, and execution.

## Goals / Non-Goals

**Goals:**
- Autonomous market scanning, research, and probability estimation
- Paper trading with full P&L tracking to validate the system before risking capital
- Calibration tracking to measure and improve LLM accuracy over time
- Live trading with strict risk controls and position sizing
- CLI-driven operation (no web UI needed)
- Cost-efficient LLM usage via tiered analysis (cheap screening, expensive deep analysis)

**Non-Goals:**
- High-frequency trading or latency-sensitive execution (we're competing on information quality, not speed)
- Web UI or dashboard (CLI + logs + optional Telegram alerts are sufficient)
- Multi-user support (single operator, single wallet)
- Market making or liquidity provision
- Supporting prediction markets other than Polymarket
- Mobile app or notifications beyond Telegram

## Decisions

### D1: Python with uv for package management
**Choice:** Python 3.12+ with uv for dependency management
**Alternatives:** Node.js/TypeScript (good Polymarket SDK support but weaker data science ecosystem), Go (fast but poor LLM library ecosystem)
**Rationale:** Python has the best ecosystem for this: py-clob-client (official SDK), anthropic SDK, data analysis libraries. uv is fast, modern, and handles lockfiles well.

### D2: SQLite for storage
**Choice:** SQLite via sqlite3 stdlib module
**Alternatives:** PostgreSQL/TimescaleDB (overkill for single-user), flat files/JSON (fragile for relational data)
**Rationale:** Single-user, single-process, low write volume. SQLite is zero-config, embedded, and handles the data volumes here easily. Can migrate to PostgreSQL later if needed.

### D3: Tiered LLM analysis to control costs
**Choice:** Two-tier approach:
- **Tier 1 (screening):** Claude Haiku — quick market assessment, ~$0.01/market
- **Tier 2 (deep analysis):** Claude Sonnet — full probability estimation with reasoning, ~$0.10-0.30/market
**Alternatives:** Single model for everything (expensive), local models for screening (lower quality), OpenAI mix (less consistent reasoning)
**Rationale:** Most markets aren't worth deep analysis. Haiku screens cheaply; Sonnet does the heavy lifting only on candidates. Keeps monthly costs in the $200-400 range.

### D4: Three-pass probability estimation
**Choice:** Structured estimation pipeline:
1. Base rate estimation (reference class forecasting)
2. Bayesian update with gathered evidence
3. Calibration adjustment based on historical accuracy
**Alternatives:** Single prompt ("what's the probability?" — poorly calibrated), ensemble of models (expensive, complex)
**Rationale:** Superforecasting research shows structured estimation outperforms gut feel. The three-pass approach forces systematic thinking and provides audit trail.

### D5: APScheduler for task orchestration
**Choice:** APScheduler (in-process Python scheduler)
**Alternatives:** Cron (external, no state), Celery (overkill, needs Redis/RabbitMQ), custom asyncio loop (reinventing the wheel)
**Rationale:** Lightweight, runs in-process, supports cron-like schedules, interval triggers, and job persistence. No external dependencies.

### D6: Tavily for web search
**Choice:** Tavily Search API
**Alternatives:** Brave Search (good free tier but less AI-optimized output), Perplexity (combines search + synthesis but more expensive and less controllable), Google Custom Search (rate-limited, expensive)
**Rationale:** Tavily is built for AI agent use cases — returns clean structured results ready for LLM consumption. Good cost/quality ratio at ~$0.005/search.

### D7: CLI-first with Click
**Choice:** Click framework for CLI
**Alternatives:** Typer (nice but adds dependency on pydantic), argparse (verbose), Rich CLI (good for display, not command routing)
**Rationale:** Click is mature, well-documented, and handles subcommands cleanly. Combine with Rich for table/progress display.

### D8: Pydantic for data models
**Choice:** Pydantic v2 for all data models (markets, positions, predictions, research dossiers)
**Alternatives:** dataclasses (no validation), attrs (less ecosystem support), raw dicts (unstructured)
**Rationale:** Pydantic gives validation, serialization, and type safety. Models are shared across the system (API responses → storage → LLM prompts → execution).

### D9: Paper trading before live
**Choice:** Mandatory paper trading phase. Paper trading uses the same analysis pipeline but records virtual trades in SQLite instead of placing real orders.
**Rationale:** Calibration data is essential before risking capital. Paper trading validates the full pipeline (scan → research → estimate → decide → track) end-to-end.

### D10: Position sizing via fractional Kelly
**Choice:** Half-Kelly criterion for position sizing, with hard caps
**Alternatives:** Fixed size (ignores edge magnitude), full Kelly (too aggressive, assumes perfect calibration), equal weight (ignores information)
**Rationale:** Half-Kelly provides a good balance between growth and risk. Hard caps (max per-market, max portfolio exposure) provide additional safety.

### DD-11: Gamma API Field Mapping
**Discovery:** Post-implementation testing revealed discrepancies between assumed and actual Gamma API response structure.
- The Gamma API returns market outcomes as parallel arrays: `outcomes` (["Yes","No"]), `outcomePrices` (["0.55","0.45"] as JSON string), and `clobTokenIds` (["token0","token1"] as JSON string)
- Volume is available as numeric `volumeNum` (preferred) and string `volume`
- Server-side filtering uses `volume_num_min` and `liquidity_num_min` query params
- Comments endpoint uses `parent_entity_id` + `parent_entity_type=market`, NOT `asset_id`
- These fields may be JSON-encoded strings and need conditional parsing

## Risks / Trade-offs

**[LLM calibration is poor initially]** → Start with paper trading, collect prediction data, adjust calibration over time. Don't trade live until calibration curve is acceptable (minimum 50 resolved predictions).

**[Claude API costs exceed budget]** → Aggressive filtering in Tier 1 reduces Tier 2 calls. Cache research dossiers (refresh on new information, not every cycle). Monitor costs via API usage tracking.

**[Polymarket API changes or rate limits tighten]** → Respect rate limits with backoff. Cache market data aggressively. The py-clob-client SDK abstracts some of this.

**[Market liquidity insufficient for position sizes]** → Check order book depth before placing orders. Limit position size to 5% of daily volume. Use limit orders, not market orders.

**[LLM hallucinates research or fabricates evidence]** → Web search results are grounded in real sources. Prompt design emphasizes "only use provided evidence." Research dossier is auditable.

**[Capital locked in long-duration markets]** → Filter markets by time-to-resolution (prefer < 60 days). Track capital lockup as a risk metric. Can sell positions early on the CLOB if needed (liquidity permitting).

**[Polygon network issues or gas spikes]** → Order matching is off-chain (gas only for settlement). py-clob-client handles gas estimation. Keep MATIC for gas on the wallet.
