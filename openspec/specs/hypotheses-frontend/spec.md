## Purpose

New Hypotheses tab in `static/index.html` providing a sortable hypothesis list with status badges, evidence detail panel, and actions table. Integrates into the existing dark theme, tab system, auto-refresh cycle, and PicoCSS styling. Supports status filtering, click-to-drill-down detail view, and graceful degradation when hypothesis tables do not exist.

## Requirements

### Requirement 1: Hypotheses tab integration
The Hypotheses tab SHALL be added as the 7th tab in the existing `<div class="tabs">` bar, after "Evaluation", using a `<button data-tab="hypotheses">Hypotheses</button>` element. The tab content SHALL be in a `<div id="tab-hypotheses" class="tab-content">` container with two sub-containers: `hyp-list-container` (visible by default) and `hyp-detail-container` (hidden by default).

#### Scenario: Tab visible in navigation
- **GIVEN** the dashboard is loaded
- **WHEN** the user views the tab bar
- **THEN** a "Hypotheses" button appears after "Evaluation"

#### Scenario: Tab switching
- **WHEN** the user clicks the "Hypotheses" tab
- **THEN** the Hypotheses tab content is shown with the list view active, all other tabs are hidden

### Requirement 2: Auto-refresh integration
The `refresh()` function's switch statement SHALL include a `case 'hypotheses'` that calls `refreshHypotheses()`. When the Hypotheses tab is active, data SHALL refresh every 30 seconds. Switching to the Hypotheses tab SHALL trigger an immediate refresh.

#### Scenario: Auto-refresh on Hypotheses tab
- **GIVEN** the Hypotheses tab is active showing the hypothesis list
- **WHEN** 30 seconds elapse
- **THEN** `refreshHypotheses()` is called, re-fetching `/api/hypotheses/list`

### Requirement 3: Status filter buttons
The hypothesis list view SHALL display a row of filter buttons: All (default, active), Proposed, Testing, Confirmed, Rejected. Each button SHALL use the existing `expand-btn` CSS class. Clicking a filter button SHALL toggle the `active` class and re-render the table showing only hypotheses with the matching status. "All" SHALL show all hypotheses.

#### Scenario: Filter to testing only
- **GIVEN** 5 hypotheses exist across multiple statuses
- **WHEN** the user clicks the "Testing" filter button
- **THEN** only hypotheses with `status: "testing"` are shown, and the "Testing" button has the `active` class

#### Scenario: Return to all
- **GIVEN** the "Confirmed" filter is active
- **WHEN** the user clicks "All"
- **THEN** all hypotheses are shown and "All" has the `active` class

### Requirement 4: Hypothesis list table
The hypothesis list SHALL display a `data-table` with columns: Hypothesis (title, truncated to 45 chars with title tooltip), Status (color-coded badge), Category, Confidence (percentage), Evidence (count), Updated (date). Each row SHALL be clickable (cursor: pointer) and SHALL call `showHypDetail(id)` on click.

#### Scenario: Status badge colors
- **GIVEN** hypotheses with all 5 statuses exist
- **WHEN** the table renders
- **THEN** badges use the correct CSS classes: `hyp-proposed` (blue), `hyp-testing` (yellow), `hyp-confirmed` (green), `hyp-rejected` (red), `hyp-invalidated` (gray)

#### Scenario: Badge CSS styling
- **GIVEN** a hypothesis with `status: "proposed"`
- **WHEN** the badge renders
- **THEN** it uses `background: #1e3a5f` and `color: #60a5fa` with rounded pill shape (`border-radius: 9999px`)

### Requirement 5: Hypothesis detail panel
Clicking a hypothesis row SHALL hide the list container and show the detail container. The detail panel SHALL display: (1) a "Back to list" button that returns to the list view; (2) KPI cards showing the hypothesis title with status badge, confidence percentage, evidence count with last-evidence date, and filter criteria (category, volume range); (3) a 2-column grid with an evidence table on the left and an actions table on the right.

#### Scenario: View hypothesis detail
- **GIVEN** hypothesis_id 1 has title "Agent tempers overconfidence", status "testing", 3 evidence records, and 1 action
- **WHEN** the user clicks that hypothesis row
- **THEN** the list is hidden, the detail panel shows with 4 KPI cards, the evidence table shows 3 rows, and the actions table shows 1 row

#### Scenario: Back to list
- **GIVEN** the detail panel is visible
- **WHEN** the user clicks "Back to list"
- **THEN** the detail panel is hidden and the list container is shown

### Requirement 6: Evidence table in detail panel
The evidence table SHALL display columns: Run (as `Run #ID`), Result (color-coded: green "Supports" or red "Contradicts" based on `supports` boolean), Brier Diff, p-value, n (sample size), and Date. Evidence SHALL be ordered by `created_at` descending (most recent first).

#### Scenario: Supporting evidence
- **GIVEN** an evidence record has `supports: true` and `brier_diff: -0.013`
- **WHEN** the evidence table renders
- **THEN** the Result cell shows "Supports" in green (`positive` class)

#### Scenario: Contradicting evidence
- **GIVEN** an evidence record has `supports: false` and `brier_diff: 0.008`
- **WHEN** the evidence table renders
- **THEN** the Result cell shows "Contradicts" in red (`negative` class)

#### Scenario: No evidence records
- **GIVEN** a hypothesis has no evidence
- **WHEN** the detail panel loads
- **THEN** the evidence area shows "No evidence records" empty state

### Requirement 7: Actions table in detail panel
The actions table SHALL display columns: Type (action_type), Config (JSON string, smaller font), Strength (as percentage), and Active (color-coded: green "Active" or red "Inactive"). Actions SHALL be ordered by `created_at` descending.

#### Scenario: Active action display
- **GIVEN** an action with `action_type: "edge_override"`, `strength: 0.65`, `active: true`
- **WHEN** the actions table renders
- **THEN** the row shows type "edge_override", strength "65%", and "Active" in green

#### Scenario: No actions
- **GIVEN** a hypothesis has no actions
- **WHEN** the detail panel loads
- **THEN** the actions area shows "No actions generated" empty state

### Requirement 8: Empty and degraded states
The Hypotheses tab SHALL display appropriate messages for degraded states: "No backtest database found" when `available` is `false`; "Hypothesis tables not yet created. Run the hypothesis-tracker migration first." when `available` is `true` but `tables_exist` is `false`; "No hypotheses defined yet. Use: polymarket backtest hypothesis propose" when tables exist but are empty.

#### Scenario: No backtest database
- **GIVEN** `backtest.db` does not exist
- **WHEN** the Hypotheses tab loads
- **THEN** the message "No backtest database found" is displayed

#### Scenario: Tables not migrated
- **GIVEN** `backtest.db` exists but hypothesis tables have not been created
- **WHEN** the Hypotheses tab loads
- **THEN** the message "Hypothesis tables not yet created. Run the hypothesis-tracker migration first." is displayed

#### Scenario: Empty hypothesis list
- **GIVEN** hypothesis tables exist but contain no rows
- **WHEN** the Hypotheses tab loads
- **THEN** the message "No hypotheses defined yet. Use: polymarket backtest hypothesis propose" is displayed

### Requirement 9: Detail panel data fetching
When `showHypDetail(id)` is called, it SHALL fetch `/api/hypotheses/{id}/evidence`, `/api/hypotheses/{id}/actions`, and `/api/hypotheses/list` in parallel using `Promise.all()`. The hypothesis metadata (title, status, confidence, filters) SHALL be extracted from the list response to populate KPI cards.

#### Scenario: Parallel data fetch
- **WHEN** the user clicks hypothesis_id 1
- **THEN** 3 API calls are made in parallel and the detail panel renders after all 3 complete

#### Scenario: Hypothesis not found in list
- **GIVEN** hypothesis_id 99 was deleted between list load and click
- **WHEN** `showHypDetail(99)` is called
- **THEN** the function returns early without rendering (no crash)

## Scenarios

### Scenario: Full hypothesis exploration workflow
- **GIVEN** the Hypotheses tab shows 5 hypotheses
- **WHEN** the user filters to "Testing", clicks a testing hypothesis, reviews its evidence and actions, then clicks "Back to list"
- **THEN** the list reappears with the "Testing" filter still active

### Scenario: Responsive layout for detail panel
- **GIVEN** the detail panel is showing evidence and actions tables
- **WHEN** the viewport is narrower than 900px
- **THEN** the evidence and actions tables stack vertically instead of side-by-side (via existing `grid-2` responsive CSS)
