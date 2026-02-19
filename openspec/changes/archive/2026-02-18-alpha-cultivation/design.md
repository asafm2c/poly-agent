## Context

The Polymarket trading agent has a well-structured scan-analyze-trade pipeline with a 3-pass LLM estimation system, Kelly sizing, risk management, and (since the adaptive-feedback-loop change) functioning calibration and re-evaluation loops. However, a comprehensive audit revealed that the system systematically undermines its own alpha potential through three compounding issues:

1. **Market selection is inverted**: Markets are analyzed in volume-descending order (Gamma API default). The 5 markets per cycle that receive expensive Sonnet analysis are the most liquid, most efficiently priced markets on the platform — exactly where an LLM-based agent has the least edge.

2. **Research is thin**: The LLM receives ~3,000 tokens of context per market: 5 web snippets truncated to 500 chars, bag-of-words sentiment from 5 comments at 200 chars each, no price history, and zero domain data. This is less information than a human trader would gather in 5 minutes.

3. **Edge computation has systematic errors**: Polymarket's price-dependent taker fees are not subtracted from edge, the limit price uses stale Gamma API last-trade price instead of CLOB midpoint, portfolio exposure is hardcoded to 0.0 in Kelly sizing, and the screening LLM's directional signal is discarded.

The CLOB client already has `get_midpoint()`, `get_order_book()`, and `get_prices_history()` methods that are never called in the analysis pipeline. The screening prompt already asks for `initial_direction` and `confidence` that are never extracted.

## Goals / Non-Goals

**Goals:**
- Analyze the right markets (opportunity-scored, not volume-sorted)
- Give the LLM meaningfully richer context per market (~8,000-12,000 tokens vs. ~3,000)
- Compute edge correctly (net of fees, using real-time prices, with actual exposure)
- Use existing CLOB client capabilities that are currently unused
- Use existing screening output fields that are currently discarded
- Keep daily LLM cost under $10/day for a $1,000 paper portfolio

**Non-Goals:**
- Implementing domain sources (crypto, politics APIs) — stays as stubs for now
- Changing the 3-pass estimation pipeline structure
- Adding new LLM passes or models
- Improving execution (spread-aware limit orders, smart routing) — paper mode doesn't need it
- Cross-market correlation analysis or arbitrage detection (L3+ work)
- Changing the screening prompt itself (only how we use its output)

## Decisions

### D1: Opportunity scoring as a separate module, not embedded in filter

**Choice:** New `market/scoring.py` module with a `score_candidates(markets, events, screening_results)` function that returns candidates sorted by descending opportunity score. The filter stays pure (pass/fail criteria); scoring is a separate ranking step called after filtering.

**Alternatives:** (a) Embed scoring into `MarketFilter.apply()` (mixes concerns — filtering and ranking are different operations), (b) Score inside the scheduler (clutters the job logic), (c) Use the screening LLM to rank markets (too expensive at Haiku scale for all candidates).

**Rationale:** Separation lets us iterate on scoring weights independently from filtering criteria. The score function is pure (no side effects, no DB queries) and easily testable. It takes in all available signals — market data, detected events, and screening results — and produces a ranked list.

### D2: Opportunity score formula — weighted composite of 6 signals

**Choice:** Linear weighted composite score:

```
score = (
    w_price * price_score(price_yes)        # Mid-range prices score higher
  + w_volume * volume_score(volume)          # Lower volume scores higher (inverse)
  + w_event * event_score(events)            # Recent events boost score
  + w_screen * screening_score(direction, confidence)  # Screening signal
  + w_time * time_score(days_to_resolution)  # Nearer resolution scores higher
  + w_calibration * category_score(category) # Categories we're calibrated on
)
```

Where:
- `price_score`: peaks at 0.50, falls linearly toward 0.10 and 0.90. `1.0 - 2 * abs(price - 0.5)`
- `volume_score`: inverse log scale. `1.0 - log10(volume) / log10(max_volume)`, clamped to [0, 1]
- `event_score`: 1.0 if any event detected for this market, 0.0 otherwise
- `screening_score`: 0.0 (not screened yet), 0.5 ("fair"), 0.75 ("higher"/"lower" + low confidence), 1.0 ("higher"/"lower" + high confidence)
- `time_score`: linear from 0.0 at 60 days to 1.0 at 1 day
- `category_score`: 0.5 default (no data), higher for categories with lower Brier scores (better calibration)

Default weights: `w_price=0.20, w_volume=0.25, w_event=0.20, w_screen=0.15, w_time=0.10, w_calibration=0.10`

**Alternatives:** (a) Single-factor ranking by one signal (too crude), (b) ML-based scoring trained on past outcomes (no data yet), (c) LLM-based ranking (too expensive for 200+ candidates).

**Rationale:** Linear composite is simple, interpretable, and tunable. Weights are configurable so we can adjust after observing calibration data. Volume gets the highest weight because it's our strongest signal for market efficiency. Events get high weight because they signal something just changed (potential mispricing window).

### D3: Screen all candidates, then score, then analyze top-N

**Choice:** The analysis job flow becomes: (1) screen all candidates with Haiku, collecting direction/confidence, (2) score and rank using screening results + other signals, (3) analyze top-N with Sonnet. This reorders the current flow where screening and analysis are interleaved.

**Alternatives:** (a) Score before screening (loses the screening signal for ranking), (b) Keep current interleaved flow and just sort candidates first (misses screening signal in the score).

**Rationale:** Screening is cheap (~$0.001/market). For 200 candidates, screening costs ~$0.20 per cycle — about the same as 1 Sonnet analysis. The payoff is that we get a directional signal for all candidates, enabling much better prioritization of the 5 expensive Sonnet analyses. The screening results are ephemeral (not persisted) and only used within the same analysis cycle.

### D4: Fee computation uses Polymarket's price-dependent formula

**Choice:** Implement `compute_taker_fee(price, fee_rate, exponent)` using the formula: `fee_per_share = price * fee_rate * (price * (1 - price))^exponent`. Subtract the round-trip fee impact (entry + exit) from raw edge before the threshold gate.

The fee parameters (`fee_rate`, `exponent`) are per-market. If the Gamma API provides them (via `maker_base_fee` / `taker_base_fee` fields), parse and use them. Otherwise, default to `fee_rate=0.0` (most Polymarket markets are fee-free) with a configurable global fallback.

**Alternatives:** (a) Flat 2% fee assumption (too aggressive — most markets are free), (b) Ignore fees entirely (current state — systematically overestimates edge on fee-enabled markets), (c) Only apply fees for known fee categories (fragile — new fee markets appear without warning).

**Rationale:** The formula is well-documented (Polymarket docs). Most markets have zero fees, so the default of 0.0 is correct. The configurable fallback lets us apply a conservative fee assumption if we're unsure. This is a correctness fix, not an optimization — incorrect edge computation directly causes bad trades.

### D5: CLOB midpoint replaces Gamma last-trade price for edge computation

**Choice:** In `build_recommendation()`, call `clob_client.get_midpoint(token_id)` to get the real-time price. Fall back to Gamma price if CLOB call fails. The midpoint is used for: (a) edge computation, (b) limit price, (c) Kelly sizing.

The CLOB client is already instantiated on the `MarketScanner` (`scanner.py:24`) but never used. Pass it through to the analysis job, or instantiate a new one in the scheduler.

**Alternatives:** (a) Use `get_price()` instead of `get_midpoint()` (returns last trade, same staleness as Gamma), (b) Use full order book and compute VWAP (overkill for paper mode), (c) Keep using Gamma price (current state — up to 15 minutes stale).

**Rationale:** The midpoint between best bid and best ask is the most accurate representation of the current "fair" price. It's also what professional traders use for mark-to-market. One API call per market is negligible cost. Falls back gracefully if CLOB is unavailable.

### D6: Price history added to research dossier via CLOB prices-history API

**Choice:** Call `clob_client.get_prices_history(token_id, interval="1w", fidelity=60)` and include a summary in the research dossier: opening price, current price, high, low, trend direction, and magnitude. Format as a text section in the dossier.

**Alternatives:** (a) Use our own `price_snapshots` table (only has data for tracked markets, not pre-trade), (b) Use Gamma API price data (only current price, no history), (c) Skip price history (current state — LLM has no price trajectory context).

**Rationale:** Knowing "this market was at 0.30 last week and is now 0.55" is highly informative for the LLM's Bayesian update. The CLOB history API is free and already implemented in our client. We summarize rather than dump raw data to stay within token budgets.

### D7: Web search content window increased, second query added

**Choice:** Increase the per-result content truncation from 500 to 2000 chars. Add a second Tavily search with a temporal/forecast-focused query: `"{category} {key_entities} latest news forecast {current_year}"`. Cap total search results at 8 across both queries (5 + 3) to keep dossier under ~12,000 tokens.

**Alternatives:** (a) Keep 500-char truncation, add more queries (more breadth, same shallow depth), (b) Single query with max_results=10 (Tavily supports up to 10, less query diversity), (c) Keep current 5x500 (current state — thin coverage).

**Rationale:** The 500-char truncation often cuts off the most relevant paragraph. 2000 chars captures 2-3 substantive paragraphs. The second query adds temporal context ("latest") that the first query (market question directly) often misses. Total Tavily cost per market goes from ~$0.005 to ~$0.010 — negligible.

### D8: Fail-closed screening on error

**Choice:** Change the `except` handler in `estimator.screen()` from `return True` (proceed with analysis) to `return False` (skip market). Log at warning level.

**Alternatives:** (a) Keep fail-open (current state — API errors cause expensive unscreened analyses), (b) Retry once on error (adds latency, might hit rate limits again).

**Rationale:** A screening failure means we have zero signal about this market. Spending $0.04 on a Sonnet analysis without any screening pre-filter is wasteful. The market will be screened again on the next cycle. Better to skip one cycle than waste LLM budget on unscreened markets.

## Risks / Trade-offs

**[Screening all candidates increases Haiku costs]** → At ~$0.001/market for 200 candidates, total screening cost is ~$0.20/cycle vs. ~$0.005 currently (screening 5). This is a 40x increase in screening cost but still small relative to the $0.20/cycle Sonnet analysis cost. Net budget increase is ~50%.

**[CLOB midpoint calls add latency to analysis]** → One `get_midpoint()` call per analyzed market (~100ms each). For 5 markets, that's ~500ms added latency per cycle. Acceptable for a 1-hour analysis interval.

**[Opportunity scoring may over-rotate away from liquid markets]** → If the volume score weights too heavily toward illiquid markets, we may try to trade markets where our orders can't fill. Mitigate: the existing liquidity floor ($1,000) stays in place, and the risk manager's liquidity depth check still runs. The volume score pushes toward mid-volume, not ultra-low-volume.

**[Second Tavily search may return overlapping results]** → The temporal query might return the same articles as the direct question query. Mitigate: deduplicate by URL before formatting for LLM. This is a minor efficiency concern, not a correctness issue.

**[Fee parameters may not be present in Gamma API response]** → If Gamma doesn't return fee data for a market, we default to 0.0 (free). This is correct for the majority of markets but may overestimate edge on fee-enabled markets we haven't seen before. Mitigate: configurable global fee fallback for categories known to have fees (crypto 5/15-min, specific sports).
