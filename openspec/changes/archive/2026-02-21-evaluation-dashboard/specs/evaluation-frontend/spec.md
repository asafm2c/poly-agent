## Purpose

New Evaluation tab in `static/index.html` providing information-dense visualization of simulation results. Integrates into the existing dark theme, tab system, auto-refresh cycle, and Plotly.js charting patterns. Features a run selector, KPI strip, 2x2 chart grid with cross-filtering, and a full-width drill-down table with sorting and text search.

## Requirements

### Requirement 1: Evaluation tab integration
The Evaluation tab SHALL be added as the 6th tab in the existing `<div class="tabs">` bar, after "Costs & Ops", using a `<button data-tab="evaluation">Evaluation</button>` element. The tab content SHALL be in a `<div id="tab-evaluation" class="tab-content">` container. The existing tab-switching JavaScript SHALL handle the new tab without modification (it operates on all buttons with `data-tab` attributes).

#### Scenario: Tab visible in navigation
- **GIVEN** the dashboard is loaded
- **WHEN** the user views the tab bar
- **THEN** an "Evaluation" button appears after "Costs & Ops"

#### Scenario: Tab switching
- **WHEN** the user clicks the "Evaluation" tab
- **THEN** the Evaluation tab content is shown, all other tabs are hidden, and the button is visually highlighted

#### Scenario: Tab does not load by default
- **WHEN** the dashboard loads for the first time
- **THEN** the Portfolio tab is active; the Evaluation tab content is hidden and no evaluation API calls are made

### Requirement 2: Auto-refresh integration
The `refresh()` function's switch statement SHALL include a `case 'evaluation'` that calls `refreshEvaluation()`. When the Evaluation tab is active, data SHALL refresh every 30 seconds. Switching to the Evaluation tab SHALL trigger an immediate refresh.

#### Scenario: Auto-refresh on Evaluation tab
- **GIVEN** the Evaluation tab is active
- **WHEN** 30 seconds elapse
- **THEN** `refreshEvaluation()` is called, fetching `/api/evaluation/runs` and run-specific endpoints

#### Scenario: Switching to Evaluation triggers refresh
- **WHEN** the user switches from Portfolio to Evaluation
- **THEN** `refreshEvaluation()` is called immediately

### Requirement 3: Run selector dropdown
The Evaluation tab SHALL display a `<select>` dropdown populated with all simulation runs from `/api/evaluation/runs`. Each option SHALL show: `Run #ID -- N trials -- date`. Changing the selection SHALL re-fetch all run-specific data and re-render charts. The dropdown SHALL preserve the current selection across refreshes if the run still exists.

#### Scenario: Multiple runs available
- **GIVEN** 3 simulation runs exist
- **WHEN** the Evaluation tab loads
- **THEN** the dropdown contains 3 options, with the most recent run selected by default

#### Scenario: Run selection change
- **WHEN** the user selects a different run from the dropdown
- **THEN** all 4 charts and the drill-down table update to reflect the newly selected run's data

### Requirement 4: KPI summary strip
The Evaluation tab SHALL display a compact row of 6 KPI cards using the existing `kpiCard()` helper and `kpi-grid` CSS class: Agent Brier, Market Brier, Brier Diff (color-coded: green if agent better by >0.005, red if worse, neutral otherwise), Trials (valid/total with trade count subtitle), Win Rate, and LLM Cost (with per-trial cost subtitle).

#### Scenario: Agent outperforms market
- **GIVEN** the selected run has `agent_brier: 0.1675` and `market_brier: 0.1788`
- **WHEN** KPIs render
- **THEN** Brier Diff shows `-0.0113` in green with subtitle "Agent Better"

#### Scenario: No trades triggered
- **GIVEN** the selected run has `trade_count: 0`
- **WHEN** KPIs render
- **THEN** Win Rate shows "N/A" and Trials subtitle shows "0 trades triggered"

### Requirement 5: Model comparison grouped bar chart
The Evaluation tab SHALL display a Plotly grouped bar chart comparing agent Brier (blue `#3b82f6`) vs market Brier (slate `#475569`) across all simulation runs. Each bar pair SHALL be annotated with the trial count (`n=X`) in muted color (`#94a3b8`). The chart SHALL use the existing `PLOTLY_DARK` layout and `PLOTLY_CONFIG`. Data SHALL come from `/api/evaluation/compare`.

#### Scenario: Multiple runs with different models
- **GIVEN** 3 runs exist with different model configurations
- **WHEN** the model comparison chart renders
- **THEN** 3 bar pairs are shown with agent and market Brier scores, labeled `Run #1`, `Run #2`, `Run #3`

#### Scenario: Single run
- **GIVEN** only 1 run exists
- **WHEN** the model comparison chart renders
- **THEN** a single bar pair is shown (still useful for agent vs market comparison)

#### Scenario: No comparison data
- **GIVEN** no runs exist or `/api/evaluation/compare` returns empty
- **WHEN** the chart area renders
- **THEN** an empty state message "Need multiple runs for comparison" is displayed

### Requirement 6: Category heatmap with cross-filtering
The Evaluation tab SHALL display a Plotly heatmap with categories on the x-axis and a single "Brier Diff" row. Cell color SHALL use a diverging color scale: green (`#22c55e`) for negative diff (agent better), dark slate (`#1e293b`) at zero, red (`#ef4444`) for positive diff (market better), centered at zero via `zmid: 0`. Cell text SHALL show trial count and diff value. Clicking a heatmap cell SHALL set `evalFilter.category` to that category and re-render the drill-down table.

#### Scenario: Click category to filter
- **GIVEN** the heatmap shows categories `["(null)", "Match Winner"]`
- **WHEN** the user clicks the `"(null)"` cell
- **THEN** `evalFilter.category` is set to `"(null)"`, the drill-down table shows only trials in that category, a filter badge shows `"Filtered: category = (null)"`, and a "Clear filter" button appears

#### Scenario: Agent better in a category
- **GIVEN** category `"(null)"` has `brier_diff: -0.013`
- **WHEN** the heatmap renders
- **THEN** the `"(null)"` cell is colored green (closer to `#22c55e`)

### Requirement 7: Volume tier bar chart with cross-filtering
The Evaluation tab SHALL display a Plotly bar chart with volume tiers on the x-axis (ordered: `10K-100K`, `100K-1M`, `1M-10M`, `>10M`) and Brier diff on the y-axis. Each bar SHALL be colored conditionally: green (`#22c55e`) if agent better by >0.005, red (`#ef4444`) if worse, muted (`#94a3b8`) if neutral. Trial counts SHALL appear as annotations above/below each bar. A dashed zero line SHALL be drawn at y=0. Clicking a bar SHALL set `evalFilter.volume_tier` and re-render the drill-down table.

#### Scenario: Click volume tier to filter
- **GIVEN** the chart shows tiers `["1M-10M", ">10M"]`
- **WHEN** the user clicks the `"1M-10M"` bar
- **THEN** `evalFilter.volume_tier` is set to `"1M-10M"`, the drill-down table filters to that tier, and the filter badge updates

#### Scenario: Mixed performance across tiers
- **GIVEN** `1M-10M` has `brier_diff: -0.013` and `>10M` has `brier_diff: 0.005`
- **WHEN** the chart renders
- **THEN** the `1M-10M` bar is green and the `>10M` bar is muted gray

### Requirement 8: Temporal line chart with regime boundaries
The Evaluation tab SHALL display a Plotly scatter chart with two traces: (1) rolling Brier diff as `lines+markers` in blue (`#3b82f6`), and (2) per-trial Brier diff as `markers` only in muted gray (`#94a3b8`, 50% opacity). The x-axis SHALL be the resolution date (type: `date`). Vertical dashed lines SHALL mark each regime boundary (from `regimes` array), with rotated regime name annotations at the top. A zero line SHALL be emphasized at y=0.

#### Scenario: Temporal chart with regime markers
- **GIVEN** the temporal data includes 6 regimes with end dates
- **WHEN** the chart renders
- **THEN** vertical dashed lines appear at each regime boundary with regime name labels rotated -45 degrees

#### Scenario: Rolling average convergence
- **GIVEN** 20 trials with varying Brier diffs
- **WHEN** the chart renders
- **THEN** the rolling line starts volatile and smooths out as more data accumulates

### Requirement 9: Drill-down table with sorting and search
The Evaluation tab SHALL display a full-width sortable table below the charts showing individual trials. Columns SHALL be: Market (question, truncated to 40 chars with title tooltip), Category, Vol Tier, Estimate, Mkt Price, Outcome (YES/NO), Agent Brier, Mkt Brier, Diff (color-coded), Edge, and Cost. The table SHALL support: (1) client-side cross-filtering from chart clicks via `evalFilter`; (2) text search on the question field via an input box; (3) column sorting via clickable headers with sort direction indicators. The "Clear filter" button SHALL reset `evalFilter` and re-render.

#### Scenario: Cross-filter from heatmap then search
- **GIVEN** the user clicks the `"(null)"` category cell, filtering to 18 trials
- **WHEN** the user types "Bitcoin" in the search box
- **THEN** only trials matching both filters (category = `"(null)"` AND question contains "Bitcoin") are shown

#### Scenario: Sort by Brier diff ascending
- **WHEN** the user clicks the "Diff" column header
- **THEN** trials are sorted by `brier_diff` ascending (best agent performance first) and the header shows an up arrow

#### Scenario: Toggle sort direction
- **GIVEN** the table is sorted by "Diff" ascending
- **WHEN** the user clicks the "Diff" header again
- **THEN** the sort reverses to descending and the header shows a down arrow

#### Scenario: Clear all filters
- **GIVEN** a category filter and search text are active
- **WHEN** the user clicks "Clear filter"
- **THEN** `evalFilter` resets to `{category: null, volume_tier: null}`, the search box clears, and all trials are shown

### Requirement 10: Empty and degraded states
The Evaluation tab SHALL display appropriate messages for degraded states: "No backtest database found. Run a simulation first." when `available` is `false`; "No simulation runs yet. Use: polymarket backtest simulate" when `available` is `true` but `runs` is empty; "No trials match current filters" when filters exclude all trials.

#### Scenario: No backtest database
- **GIVEN** `backtest.db` does not exist
- **WHEN** the Evaluation tab loads
- **THEN** only the empty state message is shown; charts and tables are not rendered

#### Scenario: Database exists but empty
- **GIVEN** `backtest.db` exists but has no simulation runs
- **WHEN** the Evaluation tab loads
- **THEN** the message "No simulation runs yet. Use: polymarket backtest simulate" is displayed

### Requirement 11: Chart layout and styling
All Evaluation charts SHALL use the existing `PLOTLY_DARK` layout base and `PLOTLY_CONFIG` (`{displayModeBar: false, responsive: true}`). Charts SHALL be arranged in a 2x2 grid using the existing `grid-2` CSS class, each with `height: 300px`. The drill-down table SHALL span the full width below the grid. Color scheme SHALL be consistent: blue `#3b82f6` for agent, slate `#475569` for market/neutral, green `#22c55e` for agent-better, red `#ef4444` for market-better, muted `#94a3b8` for annotations.

#### Scenario: Responsive layout
- **WHEN** the browser viewport is narrower than 900px
- **THEN** the 2x2 chart grid stacks into a single column

## Scenarios

### Scenario: Full interactive workflow
- **GIVEN** the Evaluation tab is active with run_id 3 selected, showing 20 trials
- **WHEN** the user clicks the `"(null)"` heatmap cell, then sorts by Brier diff, then types "Iran" in search
- **THEN** the drill-down table shows only `"(null)"`-category trials mentioning "Iran", sorted by Brier diff, with filter badge and clear button visible

### Scenario: Switch runs preserves no filters
- **GIVEN** the user has active category and volume filters on run_id 3
- **WHEN** the user selects run_id 2 from the dropdown
- **THEN** filters are cleared and the full trial set for run_id 2 is displayed
