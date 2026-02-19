## MODIFIED Requirements

### Requirement: Adaptive edge threshold scales by market efficiency
The system SHALL compute a per-market edge threshold based on market efficiency signals instead of using a flat minimum edge. Higher-volume, narrower-spread markets SHALL require more edge. Markets in well-calibrated categories SHALL require less edge. The threshold SHALL be bounded by configurable floor and ceiling values. When a strategy configuration is loaded, per-category edge threshold overrides from the strategy SHALL take precedence over computed defaults.

#### Scenario: High-volume market requires more edge
- **WHEN** a market has $5M volume and narrow spread
- **THEN** the required edge threshold is higher than the default, reflecting that the market is likely efficiently priced

#### Scenario: Low-volume niche market requires less edge
- **WHEN** a market has $15K volume and wide spread
- **THEN** the required edge threshold is lower than the default, reflecting that mispricings are more plausible

#### Scenario: Wide confidence band increases required edge
- **WHEN** the estimation pipeline produces a confidence band width of 0.40 (high uncertainty)
- **THEN** the required edge threshold is increased, reflecting that we need more margin to compensate for estimation uncertainty

#### Scenario: Threshold bounded by floor and ceiling
- **WHEN** the computed threshold would fall below `min_edge_floor` or above `max_edge_ceiling`
- **THEN** the threshold is clamped to the floor or ceiling value

#### Scenario: Well-calibrated category reduces required edge
- **WHEN** the agent has 20+ resolved predictions in a category with a Brier score better than 0.25
- **THEN** the required edge threshold for markets in that category is reduced, reflecting demonstrated estimation accuracy

#### Scenario: Strategy config category override applied
- **WHEN** `strategy.yaml` specifies an edge threshold override for a market's category
- **THEN** `compute_required_edge()` uses the strategy-specified threshold as the base instead of the default computed value

### Requirement: Opportunity-scored analysis pipeline
The analysis job SHALL screen all candidates first, then score and rank them by opportunity, then analyze the top-N with full estimation including the adversarial pass. The analysis job SHALL pass actual portfolio exposure to the edge computation instead of a hardcoded value. In `predict` mode, the analysis job SHALL record predictions for all analyzed markets but SHALL NOT build trade recommendations or execute trades. In `paper` and `live` modes, predictions SHALL be recorded for all analyzed markets regardless of edge threshold, and trade recommendations SHALL be built only when the adaptive edge threshold is met. When a strategy configuration is loaded, the analysis job SHALL apply category targeting and avoidance rules before screening.

#### Scenario: Screen-then-score-then-analyze flow
- **WHEN** the analysis job runs with N candidates
- **THEN** all N candidates are screened with the screening model, surviving candidates are scored by opportunity (incorporating screening results and detected events), and the top `max_analyses_per_cycle` candidates by score are analyzed with the full estimation pipeline including the adversarial pass

#### Scenario: Portfolio exposure passed to edge computation
- **WHEN** a trade recommendation is built for a market
- **THEN** the current total portfolio exposure (sum of open position costs) is passed to the Kelly sizing function, not 0.0

#### Scenario: Strategy category targeting applied
- **WHEN** `strategy.yaml` specifies `target_categories: ["crypto", "science"]`
- **THEN** only markets in those categories are considered as candidates, before screening

#### Scenario: Strategy category avoidance applied
- **WHEN** `strategy.yaml` specifies `avoid_categories: ["politics"]`
- **THEN** politics markets are excluded from candidates, before screening

#### Scenario: No strategy config uses all categories
- **WHEN** no `strategy.yaml` exists or it specifies no category rules
- **THEN** all categories are considered as candidates (existing default behavior)

### Requirement: Daily portfolio report
The system SHALL generate a daily portfolio report at a configurable time (default 18:00 UTC) summarizing the day's activity, P&L, calibration metrics, and Brier score comparison. The report SHALL also compute and persist daily P&L to the `daily_pnl` table, and run price snapshot cleanup. When a strategy configuration is loaded, the report SHALL include strategy drift monitoring.

#### Scenario: Daily report generation
- **WHEN** the daily report time is reached
- **THEN** a comprehensive report is generated and logged, including: trades, resolutions, P&L (realized and unrealized using latest price snapshots), calibration update, and open positions

#### Scenario: Daily P&L persistence
- **WHEN** the daily report is generated
- **THEN** the system computes today's realized P&L (from positions closed today), unrealized P&L (mark-to-market using latest price snapshots), total P&L, portfolio value, and trade count, and writes them to the `daily_pnl` table via INSERT OR REPLACE

#### Scenario: Snapshot cleanup during daily report
- **WHEN** the daily report runs
- **THEN** the system deletes price snapshots older than `snapshot_retention_days` (default 30) and logs the count of deleted rows

#### Scenario: Brier comparison in daily report
- **WHEN** the daily report is generated and 20+ predictions have resolved outcomes
- **THEN** the report logs the agent's Brier score, the market baseline Brier score, and the difference between them

#### Scenario: Strategy drift monitoring in daily report
- **WHEN** the daily report is generated and a strategy configuration is loaded
- **THEN** the report compares per-category Brier scores against strategy expectations and flags categories where actual performance diverges by more than 0.05 from expected, recommending a research review
