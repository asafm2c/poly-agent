## Why

The agent's estimation pipeline has no empirical evidence of producing calibrated probability estimates that beat market consensus. Before committing capital, we need to: (1) collect calibration data without trading risk, (2) add adversarial reasoning so the LLM considers why it might be wrong, (3) use order book microstructure data as an information source not just for execution, (4) scale edge thresholds by market efficiency so we don't take illusory edges on efficient markets, and (5) fix wiring gaps where CLOB data we already fetch isn't reaching the estimation pipeline. This change transforms the agent from "trade on first signal" to "prove signal exists, then trade with appropriate skepticism."

## What Changes

- **Prediction-only mode**: New scheduler mode that runs the full estimation pipeline and records predictions but skips trading. Allows collecting calibration data at LLM cost only (~$3-5/day). Records all estimates (not just those above edge threshold) against market prices for Brier score comparison.
- **Adversarial reasoning pass (Pass 2.5)**: New LLM pass between Bayesian update and calibration that explicitly challenges the estimate. Feeds in order book imbalance data and related market consistency data. Asks the LLM to articulate why the market might be right and the estimate wrong, then revise.
- **Order book signal extraction**: Compute bid/ask imbalance ratio and spread width from CLOB order book data. Include in research dossier and adversarial pass as signals about informed trader direction and market efficiency.
- **Adaptive edge thresholds**: Replace flat 10% minimum edge with a threshold that scales by market efficiency (volume, liquidity, spread width) and estimation uncertainty (confidence band width, category calibration quality). Low-volume niche markets need less edge; high-volume efficient markets need more.
- **Fix CLOB wiring gap**: Pass `ClobClient` from scheduler through `ProbabilityEstimator` to `ResearchGatherer` so CLOB price history (already implemented) actually reaches the dossier. Currently `ResearchGatherer()` is created with `clob_client=None`.
- **Enhanced prediction recording**: Record predictions for all analyzed markets regardless of whether edge threshold is met. Track market price at prediction time to enable Brier score comparison (agent vs market).

## Capabilities

### New Capabilities
- `adversarial-reasoning`: Adversarial LLM pass that challenges the estimation before trade decisions, using order book and related market data
- `prediction-tracking`: Prediction-only mode and enhanced prediction recording for calibration data collection without trading risk

### Modified Capabilities
- `scheduler`: Add prediction-only mode, wire CLOB client through estimation pipeline, use adaptive edge thresholds
- `opportunity-scoring`: No spec changes (scoring weights unchanged), but adaptive edge thresholds interact with scored candidates at the trade decision point

## Impact

- `src/polymarket_agent/analyst/estimator.py`: Add adversarial pass, accept CLOB client for injection into gatherer
- `src/polymarket_agent/analyst/prompts/`: New adversarial prompt template
- `src/polymarket_agent/cli/scheduler.py`: Prediction-only mode, CLOB client wiring, adaptive threshold integration
- `src/polymarket_agent/trading/edge.py`: Adaptive edge threshold function replacing flat `min_edge_threshold`
- `src/polymarket_agent/market/clob_client.py`: Order book signal extraction (imbalance ratio, spread width)
- `src/polymarket_agent/research/gatherer.py`: Include order book signals in dossier
- `src/polymarket_agent/config.py`: New config params for adaptive threshold and prediction-only mode
- `src/polymarket_agent/trading/calibration.py`: Brier score comparison (agent vs market baseline)
- `tests/test_integration.py`: Tests for all new functionality
