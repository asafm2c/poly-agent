## MODIFIED Requirements

### Requirement: Opportunity-scored analysis pipeline
The analysis job SHALL screen all candidates first, then score and rank them by opportunity, then analyze the top-N with full estimation including the adversarial pass. The analysis job SHALL pass actual portfolio exposure to the edge computation instead of a hardcoded value. In `predict` mode, the analysis job SHALL record predictions for all analyzed markets but SHALL NOT build trade recommendations or execute trades. In `paper` and `live` modes, predictions SHALL be recorded for all analyzed markets regardless of edge threshold, and trade recommendations SHALL be built only when the adaptive edge threshold is met.

#### Scenario: Screen-then-score-then-analyze flow
- **WHEN** the analysis job runs with N candidates
- **THEN** all N candidates are screened with the screening model, surviving candidates are scored by opportunity (incorporating screening results and detected events), and the top `max_analyses_per_cycle` candidates by score are analyzed with the full estimation pipeline including the adversarial pass

#### Scenario: Portfolio exposure passed to edge computation
- **WHEN** a trade recommendation is built for a market
- **THEN** the current total portfolio exposure (sum of open position costs) is passed to the Kelly sizing function, not 0.0

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

## ADDED Requirements

### Requirement: Adaptive edge threshold scales by market efficiency
The system SHALL compute a per-market edge threshold based on market efficiency signals instead of using a flat minimum edge. Higher-volume, narrower-spread markets SHALL require more edge. Markets in well-calibrated categories SHALL require less edge. The threshold SHALL be bounded by configurable floor and ceiling values.

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

### Requirement: Daily report includes Brier comparison
The daily portfolio report SHALL include the agent vs market Brier score comparison when sufficient resolved predictions exist, alongside existing calibration metrics.

#### Scenario: Brier comparison in daily report
- **WHEN** the daily report is generated and 20+ predictions have resolved outcomes
- **THEN** the report logs the agent's Brier score, the market baseline Brier score, and the difference between them
