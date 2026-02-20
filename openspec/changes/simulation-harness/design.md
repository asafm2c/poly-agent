## Context

The agent has a 4-pass estimation pipeline: base rate → Bayesian update with research dossier → adversarial challenge → calibration adjustment. The research dossier normally includes Tavily web search, Polymarket comments, related market prices, and CLOB order book data.

For historical simulation, web search is contaminated — searching for "Will Trump win 2024?" in 2026 returns articles that reveal the outcome. Comments and order book snapshots aren't available historically. The only clean historical data we have is: market question, description, category, resolution date, volume, and daily price history from the CLOB API (stored in `bt_price_history`).

The backtest DB currently has 90K+ markets with metadata and is collecting price histories for the top ~46K by volume. The estimation pipeline (`ProbabilityEstimator`) accepts a `Market` object and returns a `ProbabilityEstimate` with `final_estimate`, confidence bounds, and reasoning.

## Goals / Non-Goals

**Goals:**
- Run the LLM estimation pipeline against historical resolved markets using only information available at a given horizon (no future leakage)
- Persist every trial so we can aggregate and analyze without re-running expensive LLM calls
- Answer: does the agent's estimate have better Brier score than the market price? At which horizons, categories, and volume tiers?
- Compute simulated P&L assuming the agent would trade when its edge exceeds the adaptive threshold
- Keep per-trial LLM cost under $0.05 (use Haiku for screening pass, Sonnet for estimation)
- Support both small targeted runs (10-20 markets, interactive) and large batch runs (100+ markets, background)

**Non-Goals:**
- Replay actual web search results (no historical web archive available)
- Simulate order execution dynamics (slippage, queue position, fill rate)
- Backtest the full scheduler loop (scan → screen → analyze → trade → reeval)
- Support live/paper mode in simulation — this is purely historical analysis
- Optimize LLM prompts during this change — that's a follow-up once we have baseline data

## Decisions

### 1. Historical mode via research gatherer replacement, not estimator modification

**Decision**: Create a `HistoricalResearchGatherer` that constructs a dossier from backtest DB data only (price history summary, market metadata) instead of modifying `ProbabilityEstimator` internals.

**Rationale**: The estimator's 4-pass flow is exactly what we want to test. Modifying it would test a different system than what runs live. Instead, we inject a different research gatherer that provides the same `ResearchDossier` format but sourced from historical data. The estimator doesn't need to know it's running on historical data.

**Alternative considered**: Adding an `if historical:` branch throughout the estimator. Rejected — this couples test infrastructure to production code and risks divergence.

### 2. Price history as the primary context signal

**Decision**: The historical dossier will include: (a) price history summary (open, current at horizon, high, low, 7d trend, 30d trend), (b) market metadata (question, description, category, end date, volume), and (c) an explicit note that web search is unavailable. No comments, no order book, no related markets.

**Rationale**: This tests the LLM's *base reasoning ability* — can it extract signal from just the question and price trajectory? This is actually the hardest test. If the LLM can beat market prices with just this, it's genuinely adding value. If it can't, adding more context won't help with calibration.

### 3. Persist trials to backtest DB, not a separate database

**Decision**: Add `bt_simulation_runs` and `bt_simulation_trials` tables to the existing backtest DB.

**Rationale**: Keeps all backtest data in one place. The analysis library already connects to this DB. A run groups trials for a single simulation invocation; trials are the individual market estimates.

**Schema**:
```sql
bt_simulation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, completed_at TEXT,
    config TEXT,  -- JSON: horizon, volume range, category filter, model, etc.
    market_count INTEGER,
    agent_brier REAL, market_brier REAL,
    simulated_pnl REAL,
    total_cost REAL  -- LLM API cost
)

bt_simulation_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES bt_simulation_runs(id),
    market_id TEXT REFERENCES bt_markets(id),
    horizon_days INTEGER,
    market_price_at_horizon REAL,
    agent_estimate REAL,
    confidence_low REAL, confidence_high REAL,
    outcome REAL,  -- 1.0 or 0.0
    agent_brier REAL,  -- (estimate - outcome)^2
    market_brier REAL,  -- (price - outcome)^2
    edge REAL,  -- estimate - price (signed)
    simulated_trade TEXT,  -- JSON: side, size, entry, exit, pnl (null if no trade)
    reasoning TEXT,  -- LLM's thesis
    llm_cost REAL,
    duration_ms INTEGER
)
```

### 4. Market selection strategy

**Decision**: Select markets using configurable filters (category, volume range, regime, resolution outcome) plus random sampling within those filters. Default: 50 randomly sampled markets with >$100K volume from the null-category (prediction markets, not sports).

**Rationale**: Random sampling avoids cherry-picking. Volume floor ensures markets have real liquidity. Null-category focuses on the markets where our agent would actually trade. The sample size (50) balances cost (~$2.50 in API fees) against statistical significance.

### 5. Simulated P&L computation

**Decision**: For each trial where `|agent_estimate - market_price| > adaptive_threshold`, simulate a trade: buy YES if estimate > price, buy NO if estimate < price. Position size from Kelly criterion with bankroll=$1000 (normalized). Exit at resolution. Deduct taker fees.

**Rationale**: This mirrors exactly what the live agent would do. Using a fixed bankroll normalizes across markets. Kelly sizing naturally penalizes low-confidence bets.

### 6. CLI interface

**Decision**: Two commands: `backtest simulate` (runs trials, shows progress, writes results) and `backtest results` (queries completed runs, shows Brier comparison, P&L, category breakdown).

**Rationale**: Separation allows re-analyzing past runs without re-running expensive LLM calls.

## Risks / Trade-offs

**[No web search = weaker context than production]** → This is the point. If the LLM can't beat market prices with minimal context, it certainly can't do so reliably with noisy web search. This establishes a *lower bound* on agent value.

**[LLM knowledge cutoff contamination]** → Claude's training data includes news through early 2025. For markets that resolved before the cutoff, the LLM may "know" the answer. → Mitigation: Track regime in results. Focus analysis on post-cutoff markets (o1-era and later). Flag suspiciously confident estimates on pre-cutoff markets.

**[Cost scales linearly]** → 100 markets × ~$0.03/market = ~$3. 1000 markets = ~$30. → Mitigation: Start with small targeted runs. Use results to decide if larger runs are worth the cost. Support `--dry-run` to preview market selection without calling the LLM.

**[Small sample sizes may not be statistically significant]** → 50 markets gives wide confidence intervals on Brier score. → Mitigation: Report confidence intervals. Run larger batches once initial results justify the cost. Pool across multiple runs.
