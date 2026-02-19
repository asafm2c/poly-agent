## Why

The agent's pipeline is architecturally sound but systematically undermined by three compounding problems: it analyzes the most efficiently priced markets (highest volume first), feeds the LLM thin research (5 web snippets at 500 chars, zero domain data), and computes edge without accounting for fees, stale prices, or existing portfolio exposure. The result is plausible-looking trade recommendations with likely negative expected value. Before deploying to paper trading, we need to fix the math, enrich the information, and point the system at markets where mispricing is probable.

## What Changes

- **Opportunity-based market prioritization**: Replace volume-descending ordering with a composite opportunity score that favors mid-volume, mid-price, event-active markets where mispricing is more likely. Use the screening signal (initial_direction, confidence) that is currently discarded.
- **Fee-aware edge computation**: Subtract Polymarket's price-dependent taker fee from raw edge before the threshold gate. Parse fee parameters from Gamma API response.
- **CLOB-aware pricing**: Use the CLOB client's `get_midpoint()` for real-time price instead of stale Gamma last-trade price. Use `get_prices_history()` to feed price trend context to the LLM.
- **Richer research dossier**: Increase web search content window from 500 to 2000 chars. Add a second search query for temporal context. Feed CLOB price history (1-week trend) into the dossier.
- **Fix current_exposure bug**: Pass actual portfolio exposure to Kelly sizing instead of hardcoded 0.0.
- **Wire discarded signals**: Extract and use screening `initial_direction` and `confidence` for prioritization. Wire detected events (price_change, volume_spike) into the opportunity score.
- **Fail-closed screening**: Change screening error handling from fail-open (proceed on error) to fail-closed (skip on error).

## Capabilities

### New Capabilities
- `opportunity-scoring`: Composite scoring function that ranks candidate markets by likelihood of mispricing, replacing the implicit volume-descending ordering. Incorporates price position, volume tier, detected events, screening signals, and category calibration performance.

### Modified Capabilities
- `scheduler`: Analysis job uses opportunity-scored ordering instead of raw candidate list. Passes real portfolio exposure to edge computation. Wires detected events into prioritization.
- `price-snapshots`: No requirement changes (implementation only — CLOB midpoint used for edge calc, not snapshot storage).

## Impact

- **Modified files**: `market/filter.py` (scoring), `trading/edge.py` (fees, exposure), `analyst/estimator.py` (extract screening signals), `research/gatherer.py` (richer dossier, price history), `cli/scheduler.py` (wiring), `market/gamma_client.py` (parse fee fields), `config.py` (new config params)
- **New file**: `market/scoring.py` (opportunity score computation)
- **Dependencies**: No new external dependencies. Uses existing Tavily and CLOB client APIs.
- **Cost impact**: ~$0.01/market additional Tavily cost for second search query. CLOB calls are free. Total daily cost increase: ~$2.40 (from ~$4.80 to ~$7.20).
