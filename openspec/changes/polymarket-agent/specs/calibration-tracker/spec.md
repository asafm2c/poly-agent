## ADDED Requirements

### Requirement: Record all predictions
The system SHALL record every probability estimate the agent makes, including: market ID, timestamp, market price at time of prediction, agent's estimate, confidence band, reasoning summary, and market category.

#### Scenario: Prediction recorded
- **WHEN** the probability estimator produces an estimate for a market
- **THEN** a prediction record is stored in the database with all required fields

### Requirement: Track prediction outcomes
The system SHALL update prediction records with actual outcomes when markets resolve, computing whether the prediction was accurate.

#### Scenario: Market resolves
- **WHEN** a Polymarket market that has a recorded prediction resolves
- **THEN** the prediction record is updated with the actual outcome (YES=1, NO=0) and the prediction error (estimate - outcome)

### Requirement: Compute calibration statistics
The system SHALL compute calibration metrics by bucketing predictions into probability ranges (e.g., 0.0-0.1, 0.1-0.2, ..., 0.9-1.0) and comparing predicted probabilities to actual outcome rates within each bucket.

#### Scenario: Sufficient data for calibration curve
- **WHEN** at least 20 predictions have resolved
- **THEN** the system produces a calibration table showing: probability bucket, number of predictions, average predicted probability, actual outcome rate, and calibration error per bucket

#### Scenario: Insufficient data
- **WHEN** fewer than 20 predictions have resolved
- **THEN** the system reports that calibration data is insufficient and provides raw prediction counts only

### Requirement: Category-level calibration
The system SHALL compute calibration statistics per market category (politics, crypto, sports, etc.) separately, since accuracy may vary by domain.

#### Scenario: Category calibration available
- **WHEN** a category has at least 10 resolved predictions
- **THEN** category-specific calibration statistics are available and included in the calibration report

### Requirement: Brier score tracking
The system SHALL compute the Brier score (mean squared error of probability estimates vs binary outcomes) as an overall accuracy metric, both aggregate and per-category.

#### Scenario: Brier score calculation
- **WHEN** calibration statistics are computed
- **THEN** the Brier score is calculated as the mean of (prediction - outcome)^2 across all resolved predictions

### Requirement: Calibration data export for LLM
The system SHALL export calibration statistics in a format suitable for inclusion in LLM prompts, enabling the Pass 3 calibration adjustment in the probability estimator.

#### Scenario: Calibration prompt data
- **WHEN** the probability estimator requests calibration data for Pass 3
- **THEN** the system returns a text summary of the calibration curve and any detected biases (e.g., "You are overconfident by ~12% when predicting political events at 70-80%")
