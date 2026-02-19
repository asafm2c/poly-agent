### Requirement: Periodic market scanning
The system SHALL run market scanning at a configurable interval (default every 15 minutes) to discover new markets, detect price events, record price snapshots, and detect market resolutions. Detected events SHALL be retained for use by the analysis job's opportunity scoring.

#### Scenario: Scheduled scan execution
- **WHEN** the scan interval elapses
- **THEN** the market scanner runs, updates the market database, records price snapshots for tracked markets (with open positions or unresolved predictions), identifies candidates for analysis, checks for resolved markets with open positions or predictions, and retains detected events for the next analysis cycle

#### Scenario: Resolution detected during scan
- **WHEN** the scan detects a market with `resolved=True` that has open positions or unresolved predictions
- **THEN** the system calls `update_prediction_outcome()` for that market's predictions and `resolve_positions()` for that market's open positions, logging each resolution

#### Scenario: Resolution outcome mapping
- **WHEN** a market resolves with `resolution_outcome` of "YES"
- **THEN** `update_prediction_outcome()` is called with outcome=1.0 and `resolve_positions()` is called with outcome="YES"

#### Scenario: Resolution outcome mapping for NO
- **WHEN** a market resolves with `resolution_outcome` of "NO"
- **THEN** `update_prediction_outcome()` is called with outcome=0.0 and `resolve_positions()` is called with outcome="NO"

### Requirement: Opportunity-scored analysis pipeline
The analysis job SHALL screen all candidates first, then score and rank them by opportunity, then analyze the top-N with full estimation including the adversarial pass. The analysis job SHALL pass actual portfolio exposure to the edge computation instead of a hardcoded value. In `predict` mode, the analysis job SHALL record predictions for all analyzed markets but SHALL NOT build trade recommendations or execute trades. In `paper` and `live` modes, predictions SHALL be recorded for all analyzed markets regardless of edge threshold, and trade recommendations SHALL be built only when the adaptive edge threshold is met. When a strategy configuration is loaded, the analysis job SHALL apply category targeting and avoidance rules before screening.

#### Scenario: Screen-then-score-then-analyze flow
- **WHEN** the analysis job runs with N candidates
- **THEN** all N candidates are screened with the screening model, surviving candidates are scored by opportunity (incorporating screening results and detected events), and the top `max_analyses_per_cycle` candidates by score are analyzed with the full estimation pipeline including the adversarial pass

#### Scenario: Portfolio exposure passed to edge computation
- **WHEN** a trade recommendation is built for a market
- **THEN** the current total portfolio exposure (sum of open position costs) is passed to the Kelly sizing function, not 0.0

#### Scenario: Strategy category targeting applied
- **WHEN** `strategy.yaml` specifies `target_categories: ["crypto", "science"]`
- **THEN** only markets in those categories are considered as candidates, before screening

#### Scenario: Strategy category avoidance applied
- **WHEN** `strategy.yaml` specifies `avoid_categories: ["politics"]`
- **THEN** politics markets are excluded from candidates, before screening

#### Scenario: No strategy config uses all categories
- **WHEN** no `strategy.yaml` exists or it specifies no category rules
- **THEN** all categories are considered as candidates (existing default behavior)

#### Scenario: Detected events used in scoring
- **WHEN** the scan detected events for markets that are also candidates
- **THEN** those events are passed to the opportunity scoring function and boost the affected markets' scores

#### Scenario: Prediction recorded for every analyzed market
- **WHEN** a market completes the estimation pipeline in any mode
- **THEN** a prediction record is created with `edge_at_prediction` and `threshold_at_prediction` fields, regardless of whether the edge threshold was met

#### Scenario: Predict mode skips trade execution
- **WHEN** the scheduler is in `predict` mode and a market completes estimation
- **THEN** the prediction is recorded but no trade recommendation is built, no risk checks are performed, and no trade is executed

### Requirement: CLOB client wired through estimation pipeline
The scheduler SHALL pass the CLOB client instance through the estimation pipeline so that the research gatherer can fetch CLOB price history and order book signals during dossier construction.

#### Scenario: CLOB client reaches research gatherer
- **WHEN** the scheduler creates the probability estimator
- **THEN** the CLOB client instance is passed to the estimator, which passes it to the research gatherer, enabling CLOB price history and order book signal fetching

#### Scenario: Token ID passed to estimation
- **WHEN** the analysis job calls the estimation pipeline for a market
- **THEN** the market's `outcome_yes_token` is passed to the estimator so the research gatherer can fetch price history and order book data for the correct token

### Requirement: Fee-aware edge computation
The analysis job SHALL subtract estimated taker fees from the raw edge before comparing against the minimum edge threshold. Fee parameters SHALL be per-market when available, with a configurable fallback.

#### Scenario: Edge reduced by fees
- **WHEN** a market has a taker fee rate of 0.0175 with exponent 1, and the raw edge is 0.12 at price 0.50
- **THEN** the fee-per-share is approximately 0.0044, the round-trip fee impact is approximately 0.0088, and the adjusted edge reflects this deduction

#### Scenario: Fee-free market
- **WHEN** a market has no fee data in the Gamma API response
- **THEN** the fee deduction is 0.0 (no impact on edge)

### Requirement: Adaptive edge threshold scales by market efficiency
The system SHALL compute a per-market edge threshold based on market efficiency signals instead of using a flat minimum edge. Higher-volume, narrower-spread markets SHALL require more edge. Markets in well-calibrated categories SHALL require less edge. The threshold SHALL be bounded by configurable floor and ceiling values. When a strategy configuration is loaded, per-category edge threshold overrides from the strategy SHALL take precedence over computed defaults.

#### Scenario: High-volume market requires more edge
- **WHEN** a market has $5M volume and narrow spread
- **THEN** the required edge threshold is higher than the default, reflecting that the market is likely efficiently priced

#### Scenario: Low-volume niche market requires less edge
- **WHEN** a market has $15K volume and wide spread
- **THEN** the required edge threshold is lower than the default, reflecting that mispricings are more plausible

#### Scenario: Wide confidence band increases required edge
- **WHEN** the estimation pipeline produces a confidence band width of 0.40 (high uncertainty)
- **THEN** the required edge threshold is increased, reflecting that we need more margin to compensate for estimation uncertainty

#### Scenario: Threshold bounded by floor and ceiling
- **WHEN** the computed threshold would fall below `min_edge_floor` or above `max_edge_ceiling`
- **THEN** the threshold is clamped to the floor or ceiling value

#### Scenario: Well-calibrated category reduces required edge
- **WHEN** the agent has 20+ resolved predictions in a category with a Brier score better than 0.25
- **THEN** the required edge threshold for markets in that category is reduced, reflecting demonstrated estimation accuracy

#### Scenario: Strategy config category override applied
- **WHEN** `strategy.yaml` specifies an edge threshold override for a market's category
- **THEN** `compute_required_edge()` uses the strategy-specified threshold as the base instead of the default computed value

### Requirement: CLOB midpoint pricing
The analysis job SHALL use the CLOB API midpoint price for edge computation and limit price setting when available. The Gamma API last-trade price SHALL be used as a fallback.

#### Scenario: Midpoint available
- **WHEN** a CLOB midpoint is successfully retrieved for a market's token
- **THEN** edge computation uses the midpoint instead of the Gamma last-trade price, and the limit price on the trade recommendation is set to the midpoint

#### Scenario: Midpoint unavailable
- **WHEN** the CLOB midpoint call fails or returns None
- **THEN** edge computation falls back to the Gamma API last-trade price (current behavior)

### Requirement: Fail-closed screening
The screening step SHALL skip markets (return not worth analyzing) when an error occurs, rather than proceeding with analysis.

#### Scenario: Screening API error
- **WHEN** the screening LLM call raises an exception
- **THEN** the market is marked as not worth analyzing, logged at warning level, and skipped for this cycle

### Requirement: Richer research dossier
The research gatherer SHALL provide richer context to the estimation LLM, including longer web search content, a second temporal search query, and CLOB price history.

#### Scenario: Expanded web search content
- **WHEN** web search results are formatted for the LLM
- **THEN** each result's content is truncated to 2000 characters instead of 500

#### Scenario: Second search query for temporal context
- **WHEN** research is gathered for a market
- **THEN** a second Tavily search is performed with a temporal/forecast-focused query, and results are deduplicated by URL and appended to the web search results

#### Scenario: Price history included in dossier
- **WHEN** a market has a valid outcome token ID
- **THEN** the CLOB price history (1-week interval) is fetched and a summary (open, current, high, low, trend direction) is included in the dossier text

#### Scenario: Price history unavailable
- **WHEN** the CLOB price history call fails or returns empty
- **THEN** the dossier is formatted without a price history section (graceful degradation)

### Requirement: Extract screening signals
The screening step SHALL extract `initial_direction` and `confidence` fields from the LLM response in addition to `worth_analyzing` and `reasoning`. These fields SHALL be returned for use in opportunity scoring.

#### Scenario: Full screening output extracted
- **WHEN** the screening LLM returns a valid response with all four fields
- **THEN** `worth_analyzing`, `reasoning`, `initial_direction`, and `confidence` are all extracted and returned

#### Scenario: Missing optional fields
- **WHEN** the screening LLM response is missing `initial_direction` or `confidence`
- **THEN** defaults of `initial_direction="fair"` and `confidence="low"` are used

### Requirement: Periodic position re-evaluation
The system SHALL re-evaluate open positions at a configurable interval (default every 4 hours) using a tiered decision framework: cheap edge computation first, expensive LLM re-analysis only when needed. Positions marked for exit SHALL be closed in paper mode.

#### Scenario: Position re-evaluation with exit signals
- **WHEN** the re-evaluation interval elapses and open positions exist
- **THEN** for each open position, the system retrieves the original prediction estimate and current market price, computes remaining edge, and applies the tiered decision framework (hold/exit/re-analyze)

#### Scenario: No open positions
- **WHEN** the re-evaluation interval elapses and no open positions exist
- **THEN** the cycle is skipped and logged

### Requirement: Daily portfolio report
The system SHALL generate a daily portfolio report at a configurable time (default 18:00 UTC) summarizing the day's activity, P&L, calibration metrics, and Brier score comparison. The report SHALL also compute and persist daily P&L to the `daily_pnl` table, and run price snapshot cleanup. When a strategy configuration is loaded, the report SHALL include strategy drift monitoring.

#### Scenario: Daily report generation
- **WHEN** the daily report time is reached
- **THEN** a comprehensive report is generated and logged, including: trades, resolutions, P&L (realized and unrealized using latest price snapshots), calibration update, and open positions

#### Scenario: Daily P&L persistence
- **WHEN** the daily report is generated
- **THEN** the system computes today's realized P&L (from positions closed today), unrealized P&L (mark-to-market using latest price snapshots), total P&L, portfolio value, and trade count, and writes them to the `daily_pnl` table via INSERT OR REPLACE

#### Scenario: Snapshot cleanup during daily report
- **WHEN** the daily report runs
- **THEN** the system deletes price snapshots older than `snapshot_retention_days` (default 30) and logs the count of deleted rows

#### Scenario: Brier comparison in daily report
- **WHEN** the daily report is generated and 20+ predictions have resolved outcomes
- **THEN** the report logs the agent's Brier score, the market baseline Brier score, and the difference between them

#### Scenario: Strategy drift monitoring in daily report
- **WHEN** the daily report is generated and a strategy configuration is loaded
- **THEN** the report compares per-category Brier scores against strategy expectations and flags categories where actual performance diverges by more than 0.05 from expected, recommending a research review
