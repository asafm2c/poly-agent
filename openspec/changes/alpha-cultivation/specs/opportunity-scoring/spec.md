## ADDED Requirements

### Requirement: Score candidate markets by opportunity
The system SHALL compute an opportunity score for each candidate market that passed filtering. The score SHALL be a weighted composite of signals that indicate likelihood of mispricing. Markets SHALL be analyzed in descending opportunity score order, not in volume-descending order.

#### Scenario: Markets ranked by opportunity score
- **WHEN** the analysis job has N filtered candidates
- **THEN** each candidate receives an opportunity score and candidates are analyzed in descending score order, up to the per-cycle analysis cap

#### Scenario: Mid-volume markets score higher than high-volume
- **WHEN** two markets are identical except market A has $20K volume and market B has $5M volume
- **THEN** market A receives a higher volume_score component than market B

#### Scenario: Mid-price markets score higher than extreme-price
- **WHEN** two markets are identical except market A has YES price 0.45 and market B has YES price 0.88
- **THEN** market A receives a higher price_score component than market B

### Requirement: Incorporate screening signals into opportunity score
The system SHALL extract `initial_direction` and `confidence` from the screening LLM response and use them as a scoring signal. Markets where screening indicates mispricing with high confidence SHALL score higher.

#### Scenario: Screening says mispriced with high confidence
- **WHEN** screening returns `initial_direction="higher"` and `confidence="high"`
- **THEN** the screening_score component is 1.0

#### Scenario: Screening says fair
- **WHEN** screening returns `initial_direction="fair"`
- **THEN** the screening_score component is 0.0

#### Scenario: Screening not performed or failed
- **WHEN** a market was not screened or screening failed
- **THEN** the screening_score component is 0.0

### Requirement: Incorporate detected events into opportunity score
The system SHALL use detected events (price_change, volume_spike, new_market) as a scoring signal. Markets with recent events SHALL score higher, as events signal potential mispricing windows.

#### Scenario: Market with price change event
- **WHEN** the EventDetector detected a price_change event for a market during the most recent scan
- **THEN** the event_score component is 1.0

#### Scenario: Market with no events
- **WHEN** no events were detected for a market
- **THEN** the event_score component is 0.0

### Requirement: Incorporate time-to-resolution into opportunity score
The system SHALL score markets with nearer resolution dates higher, as they provide faster feedback cycles and approaching deadlines often reveal mispricing.

#### Scenario: Near-term resolution
- **WHEN** a market resolves in 5 days
- **THEN** the time_score component is higher than a market resolving in 50 days

### Requirement: Incorporate category calibration into opportunity score
The system SHALL score markets in categories where the agent has demonstrated better calibration (lower Brier score) higher than markets in uncalibrated or poorly-calibrated categories. When insufficient calibration data exists, a neutral default score SHALL be used.

#### Scenario: Well-calibrated category
- **WHEN** the agent has 20+ resolved predictions in category "politics" with Brier score 0.18
- **THEN** the category_score is higher than the default

#### Scenario: No calibration data
- **WHEN** a market's category has fewer than 20 resolved predictions
- **THEN** the category_score is 0.5 (neutral default)

### Requirement: Configurable scoring weights
The system SHALL support configurable weights for each scoring component. Default weights SHALL be provided that favor low-volume, mid-price, event-active markets.

#### Scenario: Custom weights
- **WHEN** `opportunity_weight_volume` is set to 0.40 in configuration
- **THEN** the volume signal contributes 40% of the total opportunity score
