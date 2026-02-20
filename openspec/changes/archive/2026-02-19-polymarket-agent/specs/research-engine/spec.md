## ADDED Requirements

### Requirement: Build per-market research dossier
The system SHALL compile a structured research dossier for each market under analysis, containing the market description, resolution criteria, relevant web search results, Polymarket comment sentiment, related market prices, and domain-specific data.

#### Scenario: Research dossier creation
- **WHEN** a market is selected for deep analysis
- **THEN** the system creates a structured dossier containing all gathered research, timestamped and attributed to sources

#### Scenario: Dossier caching
- **WHEN** a dossier already exists for a market and is less than the configured max age
- **THEN** the system reuses the cached dossier instead of re-fetching all sources

### Requirement: Web search integration
The system SHALL search the web via Tavily API for information relevant to each market's resolution criteria, including recent news, expert analysis, and factual data.

#### Scenario: Successful web search
- **WHEN** the research engine queries Tavily for a market topic
- **THEN** the system receives structured search results with titles, URLs, content snippets, and relevance scores

#### Scenario: Web search failure
- **WHEN** a Tavily API call fails (rate limit, timeout, error)
- **THEN** the system logs the failure and continues analysis with available data (does not block the pipeline)

### Requirement: Polymarket comment analysis
The system SHALL fetch and summarize recent comments on Polymarket markets to capture community sentiment and reasoning.

#### Scenario: Comments available
- **WHEN** a market has recent comments on Polymarket
- **THEN** the system fetches comments via the Gamma API `/comments` endpoint using `parent_entity_id=<market_id>` and `parent_entity_type=market` query parameters, and includes a sentiment summary in the dossier

#### Scenario: Comments unavailable
- **WHEN** a market has no comments or the comments endpoint returns an error (e.g. 422)
- **THEN** the dossier notes the absence of community discussion (logged at debug level, not treated as an error)

**Note:** The Gamma `/comments` endpoint may return 422 for some markets or require authentication. The system degrades gracefully — comment data is supplementary, not required for analysis.

### Requirement: Related market context
The system SHALL identify related Polymarket markets and include their current prices in the dossier to provide correlation context.

#### Scenario: Related markets found
- **WHEN** an event has multiple associated markets (e.g., "Will X win?" alongside "Will Y win?")
- **THEN** the dossier includes related market titles and current YES prices, extracted from the Gamma API `outcomePrices`/`outcomes` parallel arrays (same field format as DD-11, with JSON string parsing and non-Yes/No fallback)

### Requirement: Domain-specific research sources
The system SHALL support pluggable domain-specific research sources per market category (e.g., polling data for politics, on-chain data for crypto).

#### Scenario: Domain source available for category
- **WHEN** a market belongs to a category with a configured domain source (e.g., politics → polls)
- **THEN** the system queries the domain source and includes results in the dossier

#### Scenario: No domain source configured
- **WHEN** a market belongs to a category without a specific domain source
- **THEN** the system relies on web search and Polymarket data only (no error)
