## ADDED Requirements

### Requirement: Adversarial reasoning pass challenges the estimate before trade decisions
The estimation pipeline SHALL include an adversarial pass (Pass 2.5) between the Bayesian update (Pass 2) and calibration adjustment (Pass 3). This pass SHALL receive the current estimate, the market price, order book signals, and related market prices. It SHALL ask the LLM to articulate why the market might be right and the agent wrong, and optionally revise the estimate.

#### Scenario: Adversarial pass reduces an overconfident estimate
- **WHEN** Pass 2 produces an estimate of 0.42 and the market price is 0.55, and the adversarial pass identifies a compelling reason the market might be right (e.g., informed order flow, missing information)
- **THEN** the adversarial pass revises the estimate upward (closer to market price), and the revised estimate is passed to Pass 3 for calibration

#### Scenario: Adversarial pass confirms a well-supported estimate
- **WHEN** Pass 2 produces an estimate of 0.42 and the market price is 0.55, but the adversarial pass cannot identify a compelling falsification argument
- **THEN** the adversarial pass returns the estimate unchanged, and the original estimate is passed to Pass 3

#### Scenario: Adversarial pass receives order book signals
- **WHEN** the adversarial pass is invoked for a market with a valid token ID
- **THEN** the prompt includes the bid/ask imbalance ratio, spread width, and depth-at-price metrics computed from the CLOB order book

#### Scenario: Adversarial pass handles missing order book data
- **WHEN** order book data is unavailable (CLOB API error or no token ID)
- **THEN** the adversarial pass runs without order book signals, using only the market price and related market data

### Requirement: Order book signal extraction provides market microstructure data
The system SHALL compute structured signals from the CLOB order book for use in the adversarial pass and research dossier. Signals SHALL include bid/ask imbalance ratio, spread width, and depth at price.

#### Scenario: Balanced order book
- **WHEN** the order book has roughly equal bid and ask volume
- **THEN** the imbalance ratio is approximately 0.5, suggesting no strong directional signal from informed traders

#### Scenario: Bid-heavy order book
- **WHEN** total bid size is significantly larger than total ask size (imbalance > 0.6)
- **THEN** the signal suggests informed traders are accumulating (buying), which the adversarial pass can use to challenge or support a NO-side estimate

#### Scenario: Wide spread indicates inefficient market
- **WHEN** the spread width (best ask - best bid) exceeds 0.05
- **THEN** the signal indicates a less efficient market where mispricings are more plausible

### Requirement: Order book signals are included in the research dossier
The research dossier SHALL include a market microstructure section with order book signals when available, so the Bayesian update pass (Pass 2) also benefits from this data.

#### Scenario: Dossier includes order book section
- **WHEN** a research dossier is formatted for the LLM and order book data is available
- **THEN** a "Market Microstructure" section appears with bid/ask imbalance, spread width, and depth at price

#### Scenario: Dossier omits order book section when unavailable
- **WHEN** order book data could not be fetched
- **THEN** the dossier is formatted without a market microstructure section (graceful degradation)
