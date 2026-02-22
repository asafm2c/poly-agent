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

## ADDED Requirements

### Requirement: Blind adversarial mode omits market price
`ProbabilityEstimator._pass25_adversarial()` MUST accept an `include_market_price: bool = True` parameter. When `include_market_price=False`, the pass MUST use `BLIND_ADVERSARIAL_PROMPT` and `BLIND_ADVERSARIAL_SYSTEM` instead of the standard market-anchored prompts. The blind variant challenges the estimate on its own reasoning merits — systematic biases, overlooked evidence, base rate neglect — without any reference to market price or discrepancy.

#### Scenario: Blind adversarial challenges estimate without market reference
- **GIVEN** `_pass25_adversarial()` is called with `include_market_price=False`
- **WHEN** the LLM prompt is constructed
- **THEN** the prompt contains no market price, no discrepancy, and no order book signals; it asks the LLM to evaluate whether the estimate's assumptions might be wrong

#### Scenario: Standard adversarial unchanged when include_market_price=True
- **GIVEN** `_pass25_adversarial()` is called with `include_market_price=True` (the default)
- **WHEN** the LLM prompt is constructed
- **THEN** behavior is identical to before: market price, discrepancy, order book, and related markets are included in the prompt

### Requirement: Pass 2 market price section is conditional
`ProbabilityEstimator._pass2_update()` MUST accept an `include_market_price: bool = True` parameter. When `True`, the update prompt includes `**Current market price (YES):** {price}` as a labelled field. When `False`, that line is omitted entirely from the prompt (not replaced with a placeholder).

#### Scenario: Market price omitted in blind mode
- **GIVEN** `_pass2_update()` is called with `include_market_price=False`
- **WHEN** the LLM prompt is constructed
- **THEN** no market price value appears anywhere in the prompt text

#### Scenario: Market price included in standard mode
- **GIVEN** `_pass2_update()` is called with `include_market_price=True` and `market.last_price_yes=0.62`
- **WHEN** the LLM prompt is constructed
- **THEN** the prompt contains `**Current market price (YES):** 0.62`

### Requirement: include_market_price forwarded through estimate()
`ProbabilityEstimator.estimate()` MUST accept `include_market_price: bool = True` and forward it to both `_pass2_update()` and `_pass25_adversarial()`. Pass 1 (base rate) and Pass 3 (calibration) are unaffected — they never receive market price regardless of this flag.
