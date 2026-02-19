### Requirement: Prediction-only mode runs estimation without trading
The system SHALL support a `predict` mode that runs the full estimation pipeline (screening, scoring, research, 3-pass estimation with adversarial pass) and records predictions, but SHALL NOT build trade recommendations, run risk checks, or execute trades.

#### Scenario: Predict mode analyzes and records without trading
- **WHEN** the scheduler is started in `predict` mode and the analysis job runs
- **THEN** all screened and scored markets are estimated, predictions are recorded for every completed estimation, and no trade recommendations are built or executed

#### Scenario: Predict mode records predictions for all analyzed markets
- **WHEN** a market completes the estimation pipeline in predict mode
- **THEN** a prediction record is created regardless of whether the estimate would have exceeded any edge threshold

#### Scenario: Predict mode respects analysis cap
- **WHEN** predict mode runs with `max_analyses_per_cycle` configured
- **THEN** only the top-N scored markets are analyzed per cycle, same as paper and live modes

### Requirement: All analyzed predictions are recorded with market context
The system SHALL record a prediction for every market that completes the estimation pipeline, regardless of mode or whether the edge threshold is met. Each prediction SHALL include the market price at prediction time, the computed edge, and the threshold that was applied.

#### Scenario: Prediction recorded for market below edge threshold
- **WHEN** the estimation pipeline completes for a market and the adjusted edge is below the required threshold
- **THEN** a prediction is still recorded with `edge_at_prediction` and `threshold_at_prediction` fields populated

#### Scenario: Prediction recorded for market above edge threshold
- **WHEN** the estimation pipeline completes and the adjusted edge exceeds the threshold
- **THEN** a prediction is recorded with edge and threshold fields, and the pipeline continues to trade recommendation

### Requirement: Brier score comparison measures agent signal vs market baseline
The system SHALL compute and report two parallel Brier scores: one for agent estimates and one for market prices at prediction time, both measured against actual outcomes. The difference indicates whether the agent adds value beyond market consensus.

#### Scenario: Agent outperforms market
- **WHEN** Brier score comparison is computed with sufficient resolved predictions and the agent's Brier score is lower than the market's Brier score
- **THEN** the report indicates the agent has positive signal (agent estimates are more accurate than market prices were at prediction time)

#### Scenario: Agent underperforms market
- **WHEN** the agent's Brier score is higher than the market's Brier score
- **THEN** the report indicates the agent is adding noise and should not be trusted for trading decisions

#### Scenario: Insufficient data for comparison
- **WHEN** fewer than 20 predictions have resolved outcomes
- **THEN** the comparison reports "insufficient data" without drawing conclusions

#### Scenario: Brier comparison appears in daily report
- **WHEN** the daily portfolio report is generated and sufficient resolved predictions exist
- **THEN** the report includes the agent vs market Brier score comparison alongside existing calibration metrics
