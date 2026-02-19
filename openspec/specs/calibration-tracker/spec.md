## MODIFIED Requirements

### Requirement: Record prediction outcomes on resolution
The system SHALL automatically update prediction records when markets resolve. When resolution is detected during a scan, `update_prediction_outcome()` SHALL be called with the binary outcome (1.0 for YES, 0.0 for NO). This closes the calibration feedback loop, enabling Pass 3 calibration adjustment after sufficient data accumulates.

#### Scenario: Market resolves
- **WHEN** a Polymarket market that has a recorded prediction resolves
- **THEN** the prediction record is updated with the actual outcome (YES=1, NO=0) and the prediction error (estimate - outcome), triggered automatically by the scan job's resolution detection step

#### Scenario: Multiple predictions for same market
- **WHEN** a market has been analyzed multiple times (multiple prediction records) and then resolves
- **THEN** all unresolved prediction records for that market are updated with the outcome
