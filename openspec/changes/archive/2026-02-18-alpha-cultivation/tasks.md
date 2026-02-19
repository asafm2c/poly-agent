## 1. Plumbing Fixes (Foundation)

- [x] 1.1 Implement `compute_taker_fee(price, fee_rate, exponent)` in `trading/edge.py`: returns fee-per-share using Polymarket formula `price * fee_rate * (price * (1 - price))^exponent`
- [x] 1.2 Add `default_fee_rate: float = 0.0` and `default_fee_exponent: float = 1.0` to `config.py`
- [x] 1.3 Subtract round-trip fee impact from raw edge in `compute_edge()` before threshold comparison
- [x] 1.4 Parse `maker_base_fee` and `taker_base_fee` from Gamma API response in `_parse_market()`, store on Market model
- [x] 1.5 Fix `current_exposure` bug: in `_analysis_job`, compute actual portfolio exposure from open positions and pass to `build_recommendation()`
- [x] 1.6 Change screening error handler in `estimator.screen()` from `return True` (fail-open) to `return False` (fail-closed)

## 2. CLOB Integration

- [x] 2.1 In `build_recommendation()`, accept an optional `clob_midpoint` parameter. When provided, use it as `market_price` and `limit_price` instead of Gamma last-trade price
- [x] 2.2 In `_analysis_job`, call `clob_client.get_midpoint(token_id)` for each market being analyzed, pass result to `build_recommendation()`
- [x] 2.3 Ensure CLOB client is accessible from scheduler (pass through from scanner or instantiate separately)

## 3. Richer Research Dossier

- [x] 3.1 Increase web search content truncation from 500 to 2000 chars in `gatherer.format_dossier_for_llm()`
- [x] 3.2 Add second Tavily search query in `gatherer.gather()`: temporal/forecast-focused query `"{category} {key_entities} latest news forecast {year}"`, deduplicate results by URL
- [x] 3.3 Accept optional `clob_client` in `ResearchGatherer.__init__()` and call `get_prices_history(token_id, interval="1w", fidelity=60)` during research gathering
- [x] 3.4 Add price history summary to dossier formatting: open price, current price, high, low, trend direction and magnitude
- [x] 3.5 Pass `outcome_yes_token` to research gatherer so it can fetch CLOB price history

## 4. Screening Signal Extraction

- [x] 4.1 Modify `estimator.screen()` return type to include `initial_direction` and `confidence`: return a dataclass/dict instead of `tuple[bool, str]`
- [x] 4.2 Extract `initial_direction` (default "fair") and `confidence` (default "low") from screening LLM response
- [x] 4.3 Update `_analysis_job` to collect screening results for all candidates before scoring

## 5. Opportunity Scoring

- [x] 5.1 Create `market/scoring.py` with `score_candidates(markets, events, screening_results)` function
- [x] 5.2 Implement `price_score(price_yes)`: peaks at 0.50, linear falloff. `1.0 - 2 * abs(price - 0.5)`
- [x] 5.3 Implement `volume_score(volume, max_volume)`: inverse log scale. `1.0 - log10(volume) / log10(max_volume)`, clamped [0, 1]
- [x] 5.4 Implement `event_score(market_id, events)`: 1.0 if any event detected, else 0.0
- [x] 5.5 Implement `screening_score(direction, confidence)`: 0.0 for fair/failed, 0.5-1.0 for directional signals
- [x] 5.6 Implement `time_score(days_to_resolution)`: linear from 0.0 at 60 days to 1.0 at 1 day
- [x] 5.7 Implement `category_score(category, calibration_data)`: 0.5 default, adjusted by Brier score when data exists
- [x] 5.8 Implement composite `compute_opportunity_score()` with configurable weights
- [x] 5.9 Add scoring weight config params to `config.py`: `opportunity_weight_price`, `opportunity_weight_volume`, `opportunity_weight_event`, `opportunity_weight_screen`, `opportunity_weight_time`, `opportunity_weight_calibration`

## 6. Pipeline Rewiring

- [x] 6.1 Rewrite `_analysis_job` flow: screen all candidates → score → sort by score → analyze top-N
- [x] 6.2 Retain detected events from `_scan_job` on the scheduler instance for use in `_analysis_job`
- [x] 6.3 Pass events and screening results to `score_candidates()` in the analysis job
- [x] 6.4 Log the top-5 scored candidates with their scores before analysis begins

## 7. Testing

- [x] 7.1 Test fee computation: verify `compute_taker_fee()` matches Polymarket's formula at key price points (0.10, 0.50, 0.90)
- [x] 7.2 Test fee-adjusted edge: market with 12% raw edge and fees results in lower adjusted edge
- [x] 7.3 Test opportunity scoring: mid-volume market scores higher than high-volume; mid-price scores higher than extreme
- [x] 7.4 Test screening signal extraction: verify direction and confidence are returned and defaulted correctly
- [x] 7.5 Test price history dossier formatting: verify trend summary appears in formatted dossier
- [x] 7.6 Test fail-closed screening: verify exception returns `worth_analyzing=False`
- [x] 7.7 Test CLOB midpoint fallback: verify Gamma price used when midpoint unavailable
- [x] 7.8 Test portfolio exposure passed correctly: verify non-zero exposure reaches Kelly sizing
