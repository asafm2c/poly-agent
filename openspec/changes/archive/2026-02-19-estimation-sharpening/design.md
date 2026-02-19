## Context

The agent has a 3-pass LLM estimation pipeline (base rate → Bayesian update → calibration adjustment) that produces probability estimates for Polymarket prediction markets. The pipeline has never been validated against actual outcomes. We have zero resolved predictions, zero calibration data, and no evidence the LLM produces estimates better than market consensus.

Research into the Polymarket bot ecosystem reveals that all successful bots share one trait: they have an objective data source more accurate than the crowd (NOAA forecasts for weather, Binance prices for crypto, mathematical constraints for arbitrage). Our LLM pipeline's theoretical advantage is in markets requiring synthesis of multiple information sources where no single data point is authoritative — primarily politics, geopolitics, and complex multi-factor events.

Current gaps: (1) `ResearchGatherer` is created with `clob_client=None` in the estimator, so CLOB price history never reaches the dossier despite being implemented. (2) The flat 10% edge threshold treats a $5M politics market the same as a $15K niche market. (3) The estimation pipeline has no adversarial check — the LLM never considers why the market might be right. (4) We can't collect calibration data without also trading.

## Goals / Non-Goals

**Goals:**
- Enable data collection phase: run estimation pipeline without trading to gather calibration evidence
- Add adversarial reasoning that uses order book and related market data to challenge estimates
- Make edge thresholds responsive to market efficiency and estimation uncertainty
- Fix the CLOB client wiring so price history reaches the dossier
- Record all predictions (not just edge-qualifying) to maximize calibration data collection
- Enable Brier score comparison: agent estimates vs market-price-as-forecast baseline

**Non-Goals:**
- Weather bot / quantitative trading strategies (different paradigm, established competition)
- Cross-platform arbitrage (Polymarket vs PredictIt/Kalshi)
- Combinatorial arbitrage (related market consistency as a constraint — we use it as a signal, not a trading strategy)
- Domain-specific data source integration (polling APIs, on-chain data — that's a separate future change)
- Changing the 3-pass estimation structure (we're adding a pass, not restructuring)
- Live trading deployment (this change is about proving signal exists first)

## Decisions

### D1: Prediction-only mode as a scheduler mode, not a separate binary

**Decision:** Add `mode="predict"` alongside existing `"paper"` and `"live"` modes in `AgentScheduler`. In predict mode, the analysis job runs the full estimation pipeline (screen → score → research → 3-pass estimate) and records predictions, but skips `build_recommendation()`, risk checks, and trade execution entirely.

**Why not a separate command?** The pipeline is identical up to the trade decision point. Duplicating it creates drift risk. A mode flag is simpler and keeps the code unified.

**Why not just paper trade with $0 bankroll?** Paper trading still skips markets below edge threshold. Prediction-only mode needs to record all estimates to maximize calibration data, including markets where our estimate roughly agrees with the market.

### D2: Adversarial pass as Pass 2.5 between update and calibration

**Decision:** Insert a new LLM pass after the Bayesian update (Pass 2) and before calibration adjustment (Pass 3). This pass receives the current estimate, the market price, order book imbalance data, and related market prices. It asks the LLM to articulate why the market might be right, identify what information it might be missing, and optionally revise the estimate downward toward the market price.

**Why between Pass 2 and Pass 3?** Pass 2 produces the "raw" evidence-based estimate. The adversarial pass challenges it before calibration has a chance to adjust. This preserves the calibration pass's role as a final metacognitive check.

**Why not just modify the Pass 2 prompt?** Pass 2 already handles a lot (process all dossier evidence, produce shifts, generate thesis). Adding adversarial reasoning to the same prompt would overload it and muddle the chain of thought. A separate pass with a dedicated prompt produces cleaner reasoning.

**Model:** Use the same analysis model (Sonnet) at temperature 0.3 (slightly higher than the 0.2 used elsewhere) to encourage more creative falsification attempts. Max tokens: 768.

### D3: Order book signals as computed metrics, not raw data

**Decision:** Compute three metrics from the CLOB order book and include them in the dossier and adversarial pass as structured data:
- **Bid/ask imbalance ratio:** `total_bid_size / (total_bid_size + total_ask_size)` — values >0.6 suggest informed buying, <0.4 suggest informed selling
- **Spread width:** `best_ask - best_bid` — wider spread = less efficient market
- **Depth at price:** Total liquidity available within 5% of midpoint — indicates how much we could trade without impact

**Why computed metrics, not raw order book?** The LLM doesn't need 50 price levels of bid/ask data. Three numbers tell the story. This also keeps the dossier compact and the adversarial prompt focused.

**Where to compute:** Add methods to `ClobClient` that return a structured `OrderBookSignals` dataclass. The gatherer includes these in the dossier; the adversarial pass receives them directly.

### D4: Adaptive edge threshold as a function, not a config parameter

**Decision:** Replace `settings.min_edge_threshold` (flat 0.10) with a function `compute_required_edge(market, confidence_band, category_brier)` that returns a per-market threshold. The function scales edge requirements based on:

- **Volume factor:** `base * (1 + log10(volume) / log10(reference_volume))` — higher volume → higher threshold. Reference volume ~$100K.
- **Confidence factor:** `base * (1 + confidence_width)` — wider confidence band → need more edge to compensate for uncertainty.
- **Calibration factor:** If category Brier score is available and better than 0.25 (coin flip), reduce threshold; if worse, increase it.

**Floor:** Never below `min_edge_floor` (configurable, default 0.05). Even on the thinnest market we need 5% edge.
**Ceiling:** Never above `max_edge_ceiling` (configurable, default 0.25). We don't want to reject all markets.

**Why not keep the flat threshold?** A 10% edge on a $5M politics market is almost certainly noise — thousands of informed traders have already priced it. A 10% edge on a $15K niche market about grain export policy is plausible — few people are paying attention.

### D5: Record all analyzed predictions, gate trading separately

**Decision:** In the analysis job, always call `record_prediction()` for every market that completes the estimation pipeline, regardless of whether edge exceeds threshold. The trade decision (edge check, Kelly sizing, risk management) happens after prediction recording.

**Schema change:** Add `edge_at_prediction` and `threshold_at_prediction` columns to the predictions table so we can analyze which predictions we would have traded on and what happened.

**Why?** Calibration data is the scarcest resource. Every estimation costs ~$0.03-0.05 in LLM calls. Throwing away the prediction because it didn't meet the edge threshold is wasteful. We need all data points for Brier score analysis, especially "near-miss" predictions where we almost traded.

### D6: Brier score comparison as the key Phase 0 success metric

**Decision:** Add a function `compute_brier_comparison()` that computes two Brier scores side by side:
- **Agent Brier:** `mean((agent_estimate - outcome)^2)` — how accurate are we?
- **Market Brier:** `mean((market_price_at_prediction - outcome)^2)` — how accurate is the market?

If Agent Brier < Market Brier, we have signal. The magnitude of the difference tells us how much edge exists in theory before fees and execution costs.

**Where:** Extend `calibration.py` with the comparison function. Include in daily report output.

### D7: CLOB client wiring through dependency injection

**Decision:** Pass `ClobClient` instance from `AgentScheduler` → `ProbabilityEstimator` → `ResearchGatherer` via constructor injection. The scheduler already creates a `ClobClient` instance (`self.clob`). Currently `ProbabilityEstimator()` creates `ResearchGatherer()` with no arguments.

**Change:** `ProbabilityEstimator.__init__()` accepts optional `clob_client` and passes it to `ResearchGatherer(clob_client=clob_client)`. Scheduler creates `ProbabilityEstimator(clob_client=self.clob)` instead of bare `ProbabilityEstimator()`.

Also pass `token_id` from the analysis job into `estimator.estimate()` so the gatherer can fetch price history for the correct token.

## Risks / Trade-offs

**[LLM cost increase from adversarial pass]** → Each analysis now costs 4 Sonnet calls instead of 3 (~33% increase). At 5 analyses/hour, this adds ~$0.01-0.02/hour. Acceptable for the reasoning quality improvement. Can skip the adversarial pass in prediction-only mode to save costs if needed.

**[Adversarial pass might make the agent too conservative]** → The pass is designed to challenge the estimate, which could systematically push estimates toward the market price (i.e., toward no trade). Mitigation: the pass asks the LLM to revise only if the falsification argument is compelling, not unconditionally. Monitor the "estimate revision magnitude" to detect if the pass is just adding noise.

**[Adaptive threshold complexity]** → More parameters = more things to tune wrong. Mitigation: start with conservative defaults (floor=0.05, ceiling=0.25) and a simple linear scaling model. Tune based on Phase 0 data.

**[Prediction-only mode burns LLM budget without trading]** → At ~$3-5/day, running for 2-4 weeks costs $40-140 before any trading revenue. This is the cost of empirical validation — much cheaper than losing trading capital on an uncalibrated system.

**[Order book data is ephemeral]** → By the time we act on order book signals (minutes to hours later), the book may have changed completely. Mitigation: use order book data as a reasoning input (is this an efficient market?) not as a trading signal (which direction is it going?). The spread width and general imbalance pattern are more stable than individual price levels.

## Open Questions

- Should the adversarial pass be skipped in prediction-only mode to reduce cost, or is the adversarial reasoning important even for calibration data collection? (Tentative answer: include it — we want to calibrate the full pipeline, not a subset.)
- What's the right `max_analyses_per_cycle` for prediction-only mode? Current default is 5. Prediction-only could go to 10-15 since there's no trading cost, but LLM cost scales linearly. (Tentative: 10.)
- How many resolved predictions do we need before the Brier comparison is statistically meaningful? Rule of thumb: 50+ for overall, 20+ per category. With 10 analyses/hour and markets resolving over 1-60 days, expect 2-4 weeks to first meaningful signal.
