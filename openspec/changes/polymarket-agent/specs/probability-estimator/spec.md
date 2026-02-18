## ADDED Requirements

### Requirement: Three-pass probability estimation
The system SHALL estimate the probability of a market outcome using a structured three-pass approach via Claude API: (1) base rate estimation, (2) Bayesian update with evidence, (3) calibration adjustment.

#### Scenario: Full three-pass estimation
- **WHEN** the estimator receives a research dossier for a market
- **THEN** the system executes three sequential LLM calls, each building on the previous, and returns a final probability estimate with reasoning at each stage

### Requirement: Base rate estimation (Pass 1)
The system SHALL prompt Claude to establish a reference class probability before considering market-specific evidence. The prompt MUST ask: "For events of this type, what is the historical base rate?"

#### Scenario: Base rate with clear reference class
- **WHEN** the market has an identifiable reference class (e.g., "incumbent re-election", "bill passage")
- **THEN** the LLM returns a base rate probability with the reference class cited

#### Scenario: Base rate with unclear reference class
- **WHEN** the market is novel with no clear reference class
- **THEN** the LLM returns a base rate of 0.50 with reasoning explaining the uncertainty

### Requirement: Bayesian update with evidence (Pass 2)
The system SHALL prompt Claude to update the base rate given the specific evidence in the research dossier. The prompt MUST provide the dossier content and the Pass 1 base rate, and ask for an updated probability with explicit reasoning about which evidence shifts the probability and by how much.

#### Scenario: Evidence shifts probability
- **WHEN** the dossier contains evidence relevant to the outcome
- **THEN** the LLM returns an updated probability different from the base rate with itemized reasoning for each shift

#### Scenario: No meaningful evidence
- **WHEN** the dossier contains no evidence that should shift the base rate
- **THEN** the LLM returns the base rate unchanged with reasoning explaining why no update was warranted

### Requirement: Calibration adjustment (Pass 3)
The system SHALL prompt Claude to review its estimate against historical calibration data (if available) and adjust for known biases. The prompt MUST include the agent's calibration curve data showing historical accuracy at each confidence level.

#### Scenario: Calibration data available
- **WHEN** the system has at least 20 resolved predictions
- **THEN** the LLM receives calibration statistics and MAY adjust the final estimate to correct for observed biases (e.g., reduce if historically overconfident)

#### Scenario: No calibration data yet
- **WHEN** fewer than 20 resolved predictions exist
- **THEN** the system skips the calibration adjustment and uses the Pass 2 estimate as final, with a note that calibration is not yet available

### Requirement: Tiered screening before deep analysis
The system SHALL use Claude Haiku for an initial quick screen of candidate markets before committing to full three-pass analysis with Claude Sonnet. The screen determines whether a market is worth deep analysis.

#### Scenario: Market passes screening
- **WHEN** Haiku assesses a market as potentially mispriced or having researchable information edge
- **THEN** the market proceeds to full three-pass analysis with Sonnet

#### Scenario: Market fails screening
- **WHEN** Haiku assesses a market as efficiently priced or lacking information edge
- **THEN** the market is skipped for this analysis cycle (no Sonnet call made)

### Requirement: Structured output format
The system SHALL return probability estimates in a structured format containing: final probability, confidence band (low/high), per-pass reasoning, key evidence cited, and a human-readable thesis summary.

#### Scenario: Estimate output structure
- **WHEN** the estimator completes analysis of a market
- **THEN** the output contains all required fields: probability (float 0-1), confidence_low (float), confidence_high (float), base_rate (float), updated_estimate (float), final_estimate (float), reasoning per pass (string), key evidence (list of strings), thesis (string)
