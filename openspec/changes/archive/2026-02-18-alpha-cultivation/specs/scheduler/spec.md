## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Opportunity-scored analysis pipeline
The analysis job SHALL screen all candidates first, then score and rank them by opportunity, then analyze the top-N with full estimation. The analysis job SHALL pass actual portfolio exposure to the edge computation instead of a hardcoded value.

#### Scenario: Screen-then-score-then-analyze flow
- **WHEN** the analysis job runs with N candidates
- **THEN** all N candidates are screened with the screening model, surviving candidates are scored by opportunity (incorporating screening results and detected events), and the top `max_analyses_per_cycle` candidates by score are analyzed with the full estimation pipeline

#### Scenario: Portfolio exposure passed to edge computation
- **WHEN** a trade recommendation is built for a market
- **THEN** the current total portfolio exposure (sum of open position costs) is passed to the Kelly sizing function, not 0.0

#### Scenario: Detected events used in scoring
- **WHEN** the scan detected events for markets that are also candidates
- **THEN** those events are passed to the opportunity scoring function and boost the affected markets' scores

### Requirement: Fee-aware edge computation
The analysis job SHALL subtract estimated taker fees from the raw edge before comparing against the minimum edge threshold. Fee parameters SHALL be per-market when available, with a configurable fallback.

#### Scenario: Edge reduced by fees
- **WHEN** a market has a taker fee rate of 0.0175 with exponent 1, and the raw edge is 0.12 at price 0.50
- **THEN** the fee-per-share is approximately 0.0044, the round-trip fee impact is approximately 0.0088, and the adjusted edge reflects this deduction

#### Scenario: Fee-free market
- **WHEN** a market has no fee data in the Gamma API response
- **THEN** the fee deduction is 0.0 (no impact on edge)

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
