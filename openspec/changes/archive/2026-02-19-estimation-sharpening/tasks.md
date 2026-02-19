## 1. Fix CLOB Wiring (Foundation)

- [x] 1.1 Pass `clob_client` parameter to `ProbabilityEstimator.__init__()`, store as `self.clob`
- [x] 1.2 In `ProbabilityEstimator.__init__()`, create `ResearchGatherer(clob_client=self.clob)` instead of bare `ResearchGatherer()`
- [x] 1.3 In `AgentScheduler.__init__()`, create `ProbabilityEstimator(clob_client=self.clob)` instead of bare `ProbabilityEstimator()`
- [x] 1.4 Add `token_id` parameter to `ProbabilityEstimator.estimate()`, pass through to `self.research.gather(market, token_id=token_id)`
- [x] 1.5 In `_analysis_job`, pass `token_id=market.outcome_yes_token` to `self.estimator.estimate()`

## 2. Order Book Signal Extraction

- [x] 2.1 Create `OrderBookSignals` dataclass in `models.py`: `imbalance_ratio: float`, `spread_width: float`, `depth_at_price: float`
- [x] 2.2 Add `get_order_book_signals(token_id, midpoint)` method to `ClobClient` that fetches the order book and computes the three metrics, returns `OrderBookSignals | None`
- [x] 2.3 Add `order_book_signals: OrderBookSignals | None` field to `ResearchDossier` model (default None)
- [x] 2.4 In `ResearchGatherer.gather()`, fetch order book signals via `self.clob.get_order_book_signals()` when CLOB client and token ID are available, store on dossier
- [x] 2.5 In `ResearchGatherer.format_dossier_for_llm()`, add "## Market Microstructure" section when `order_book_signals` is present: imbalance ratio with interpretation, spread width, depth at price

## 3. Adversarial Reasoning Pass

- [x] 3.1 Create `src/polymarket_agent/analyst/prompts/adversarial.py` with `ADVERSARIAL_SYSTEM` and `ADVERSARIAL_PROMPT` templates. Prompt receives: question, category, current estimate, market price, order book signals (if available), related market data. Asks LLM to articulate why market might be right, identify missing information, and optionally revise estimate. Returns JSON: `{revised_estimate, revision_applied, falsification_argument, confidence_low, confidence_high}`
- [x] 3.2 Add `_pass25_adversarial()` method to `ProbabilityEstimator`: takes market, current estimate, confidence band, market price, order book signals, related markets. Calls analysis model with temperature 0.3, max tokens 768. Returns dict with revised estimate and reasoning
- [x] 3.3 Wire adversarial pass into `estimate()` method: after Pass 2 and before Pass 3, call `_pass25_adversarial()`. Pass the result's `revised_estimate` and `confidence_low/high` to Pass 3 instead of Pass 2's raw output
- [x] 3.4 Store adversarial reasoning: add `pass25_reasoning` field to `ProbabilityEstimate` model, populate from adversarial pass result

## 4. Enhanced Prediction Recording

- [x] 4.1 Add `edge_at_prediction` (float, nullable) and `threshold_at_prediction` (float, nullable) columns to the `predictions` table schema in database initialization
- [x] 4.2 Update `record_prediction()` in `calibration.py` to accept optional `edge` and `threshold` parameters, store them in the new columns
- [x] 4.3 In `_analysis_job` (paper/live modes), move `record_prediction()` call to happen immediately after estimation completes, before edge check. Pass computed edge and threshold values
- [x] 4.4 Add `compute_brier_comparison()` function to `calibration.py`: queries resolved predictions, computes agent Brier score (`mean((agent_estimate - outcome)^2)`) and market Brier score (`mean((market_price - outcome)^2)`), returns both scores and the difference. Returns None if fewer than 20 resolved predictions

## 5. Adaptive Edge Threshold

- [x] 5.1 Add config params: `min_edge_floor: float = 0.05`, `max_edge_ceiling: float = 0.25`, `adaptive_edge_reference_volume: float = 100_000.0`
- [x] 5.2 Implement `compute_required_edge(market, confidence_width, spread_width, category_brier)` in `trading/edge.py`: computes per-market threshold scaled by volume factor, confidence factor, and calibration factor, clamped to [floor, ceiling]
- [x] 5.3 In `build_recommendation()`, call `compute_required_edge()` instead of using `settings.min_edge_threshold`. Pass spread width from order book signals if available (default to 0.0)
- [x] 5.4 Return the computed threshold from `build_recommendation()` alongside the recommendation (or None), so the caller can pass it to `record_prediction()`

## 6. Prediction-Only Mode

- [x] 6.1 Accept `mode="predict"` in `AgentScheduler.__init__()` alongside existing `"paper"` and `"live"` modes
- [x] 6.2 In `_analysis_job`, after estimation and prediction recording, skip `build_recommendation()`, risk checks, and trade execution when `self.mode == "predict"`
- [x] 6.3 In predict mode, don't compute portfolio exposure or bankroll (not needed since no trading)
- [x] 6.4 Add `predict` as a valid mode in the CLI entry point (same as paper but no PaperTrader needed)
- [x] 6.5 In predict mode, skip re-evaluation job and position-resolution logic in scan job (no positions to manage)

## 7. Daily Report Integration

- [x] 7.1 In `_daily_report_job`, call `compute_brier_comparison()` and log the agent vs market Brier scores when data is available
- [x] 7.2 Log the prediction count (total recorded, total resolved, total unresolved) in the daily report

## 8. Testing

- [x] 8.1 Test order book signal computation: verify imbalance ratio, spread width, and depth for a mocked order book with known bid/ask arrays
- [x] 8.2 Test adversarial pass integration: mock LLM to return a revised estimate, verify it flows through to Pass 3 and the final `ProbabilityEstimate`
- [x] 8.3 Test adversarial pass with missing order book: verify pass runs without order book signals, using only market price
- [x] 8.4 Test adaptive edge threshold: verify high-volume market produces higher threshold than low-volume; wide confidence band produces higher threshold
- [x] 8.5 Test adaptive edge threshold bounds: verify floor and ceiling are respected
- [x] 8.6 Test prediction recording with edge/threshold: verify `edge_at_prediction` and `threshold_at_prediction` are stored correctly
- [x] 8.7 Test Brier comparison: mock resolved predictions with known estimates and outcomes, verify agent and market Brier scores are computed correctly
- [x] 8.8 Test prediction-only mode: verify analysis job records predictions but does not call `build_recommendation()` or execute trades
- [x] 8.9 Test CLOB wiring: verify `ResearchGatherer` receives `clob_client` when created via `ProbabilityEstimator` from scheduler
- [x] 8.10 Test dossier includes order book section: verify formatted dossier contains "Market Microstructure" when signals are present, and omits it when absent
