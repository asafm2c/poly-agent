## ADDED Requirements

### Requirement: Compute remaining edge on open positions
The system SHALL compute the remaining edge for each open position by comparing the original agent estimate (from the prediction at entry time) to the current market price. Remaining edge is defined as `original_estimate - current_price` for YES positions and `(1 - original_estimate) - (1 - current_price)` for NO positions (which simplifies to `current_price - original_estimate`).

#### Scenario: YES position with positive edge
- **WHEN** a YES position was entered with agent estimate 0.65 and current market price is 0.55
- **THEN** remaining edge is 0.10 (positive — edge still exists)

#### Scenario: YES position with reversed edge
- **WHEN** a YES position was entered with agent estimate 0.65 and current market price is 0.70
- **THEN** remaining edge is -0.05 (negative — market moved past our estimate)

#### Scenario: NO position edge computation
- **WHEN** a NO position was entered with agent estimate 0.35 (i.e., NO side valued at 0.65) and current market YES price is 0.30
- **THEN** remaining edge is 0.30 - 0.35 = -0.05 (negative — market agrees with our NO thesis even more, edge reversed because market moved in our favor past our estimate)

### Requirement: Tiered re-evaluation decisions
The system SHALL apply a two-tier decision framework when re-evaluating positions:
- **Tier 1 (no LLM cost):** If remaining edge > `min_edge_threshold`, HOLD. If remaining edge < `reeval_edge_exit_threshold` (default 0.0), EXIT.
- **Tier 2 (LLM re-analysis):** If remaining edge is between the exit threshold and `min_edge_threshold`, or if the position has been open longer than 7 days, trigger a fresh 3-pass estimation on the market.

#### Scenario: Clear hold — edge still large
- **WHEN** remaining edge is 0.12 and `min_edge_threshold` is 0.10
- **THEN** the position is held without LLM re-analysis

#### Scenario: Clear exit — edge reversed
- **WHEN** remaining edge is -0.03 and `reeval_edge_exit_threshold` is 0.0
- **THEN** the position is marked for exit without LLM re-analysis

#### Scenario: Ambiguous — triggers re-analysis
- **WHEN** remaining edge is 0.04 (between 0.0 and 0.10)
- **THEN** a fresh LLM 3-pass estimation is triggered for the market

#### Scenario: Stale position — triggers re-analysis
- **WHEN** a position has been open for longer than `reeval_staleness_days` (default: 7) regardless of edge
- **THEN** a fresh LLM 3-pass estimation is triggered

### Requirement: LLM re-analysis exit decision
When Tier 2 re-analysis is triggered, the system SHALL run the full estimation pipeline (research + 3-pass) on the position's market. The system SHALL compare the new estimate to the current market price. If the new estimate agrees with the market (no edge), the position SHALL be marked for exit. If the new estimate still disagrees with the market (edge remains), the position SHALL be held.

#### Scenario: Re-analysis confirms exit
- **WHEN** the original estimate was 0.65, the market is now at 0.62, and re-analysis produces a new estimate of 0.60
- **THEN** the position is marked for exit (new estimate agrees with market — no edge)

#### Scenario: Re-analysis confirms hold
- **WHEN** the original estimate was 0.65, the market is now at 0.50, and re-analysis produces a new estimate of 0.68
- **THEN** the position is held (new estimate still disagrees with market — edge of 0.18)

### Requirement: Re-analysis cap per cycle
The system SHALL enforce a configurable maximum number of LLM re-analyses per re-evaluation cycle (default: 3) via `max_reanalyses_per_cycle`. When the cap is reached, remaining ambiguous positions are deferred to the next cycle.

#### Scenario: Cap reached
- **WHEN** 3 positions have been re-analyzed in this cycle and 2 more are ambiguous
- **THEN** the 2 remaining positions are skipped with a log message and deferred to the next cycle

### Requirement: Paper exit on re-evaluation signal
When a position is marked for exit by the re-evaluation, the system SHALL close the position in paper mode at the current market price, record the realized P&L, credit cash to the portfolio, and record a sell trade in the trades table.

#### Scenario: Paper exit execution
- **WHEN** a YES position of 100 shares at entry price $0.40 is marked for exit and current price is $0.55
- **THEN** the position is closed with exit_price=0.55, realized_pnl=(100*0.55 - 100*0.40)=$15.00, cash is credited $55.00 (100 shares * $0.55), and a sell trade is recorded

### Requirement: Re-evaluation configuration
The system SHALL support the following configurable parameters:
- `reeval_edge_exit_threshold` (default: 0.0) — exit without re-analysis below this edge
- `max_reanalyses_per_cycle` (default: 3) — cap on LLM calls per re-evaluation cycle

#### Scenario: Custom thresholds
- **WHEN** `reeval_edge_exit_threshold` is set to -0.05
- **THEN** positions are only exited without re-analysis when edge is below -0.05 (more tolerant of small edge reversals)
