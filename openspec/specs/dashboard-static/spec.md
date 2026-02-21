## Purpose

Modify `static/index.html` to add two new tabs (Evaluation and Hypotheses) following the established tab pattern, dark theme, Plotly.js charting conventions, and auto-refresh behavior. Adds CSS for new UI elements (status badges, sortable headers, clickable chart cells) and JavaScript state management for cross-filtering.

## MODIFIED Requirements

### Requirement 1: Seven-tab navigation
The tab bar SHALL display seven tabs: Portfolio, Positions, Calibration, Operations, Costs & Ops, Evaluation, and Hypotheses. The two new buttons SHALL use the same `data-tab` attribute pattern. The existing tab-switching code SHALL handle all seven tabs without modification.

#### Scenario: All tabs present
- **GIVEN** the dashboard is loaded
- **WHEN** the user views the tab bar
- **THEN** 7 tab buttons are visible: Portfolio, Positions, Calibration, Operations, Costs & Ops, Evaluation, Hypotheses

#### Scenario: Tab switching works for new tabs
- **WHEN** the user clicks "Evaluation" then "Hypotheses" then "Portfolio"
- **THEN** each tab's content is shown/hidden correctly using the existing `data-tab` switching logic

### Requirement 2: Evaluation tab content structure
The `index.html` SHALL contain a `<div id="tab-evaluation" class="tab-content">` with the following structure: (1) run selector dropdown (`#eval-run-select`); (2) KPI grid (`#eval-kpis`); (3) 2x2 chart grid using `grid-2` class containing model comparison chart (`#eval-model-chart`), category heatmap (`#eval-category-heatmap`), volume tier chart (`#eval-volume-chart`), and temporal chart (`#eval-temporal-chart`), each with `height: 300px`; (4) full-width drill-down section with filter badge, clear-filter button, search input (`#eval-search`), and table container (`#eval-drilldown-table`).

#### Scenario: Evaluation tab structure
- **WHEN** the Evaluation tab content is inspected
- **THEN** all chart containers, the KPI grid, the run selector, and the drill-down table container exist in the DOM

### Requirement 3: Hypotheses tab content structure
The `index.html` SHALL contain a `<div id="tab-hypotheses" class="tab-content">` with two sub-containers: (1) `hyp-list-container` (visible by default) containing status filter buttons and the hypothesis table (`#hyp-table`); (2) `hyp-detail-container` (hidden by default) containing a "Back to list" button, KPI cards (`#hyp-detail-kpis`), and a 2-column grid with evidence table (`#hyp-evidence-table`) and actions table (`#hyp-actions-table`).

#### Scenario: Hypotheses tab structure
- **WHEN** the Hypotheses tab content is inspected
- **THEN** both the list container and detail container exist, with the list visible and detail hidden

### Requirement 4: CSS additions for new components
The `<style>` block SHALL include styles for: (1) `#eval-run-select` — dark background, slate border, light text; (2) `#eval-search` — matching dark input styling, 300px width; (3) hypothesis status badges (`.hyp-badge` with pill shape) with 5 status-specific classes: `.hyp-proposed` (blue: bg `#1e3a5f`, text `#60a5fa`), `.hyp-testing` (yellow: bg `#422006`, text `#fbbf24`), `.hyp-confirmed` (green: bg `#14532d`, text `#86efac`), `.hyp-rejected` (red: bg `#450a0a`, text `#fca5a5`), `.hyp-invalidated` (gray: bg `#1e293b`, text `#64748b`); (4) sortable table headers (`.data-table th.sortable`) with cursor pointer, hover highlight, and directional arrow indicators (`.sort-asc::after`, `.sort-desc::after`).

#### Scenario: Status badge rendering
- **GIVEN** a hypothesis has `status: "confirmed"`
- **WHEN** the badge renders
- **THEN** it has green background `#14532d`, green text `#86efac`, pill shape, and small bold font

#### Scenario: Sortable header indicators
- **GIVEN** the drill-down table is sorted by "Diff" ascending
- **WHEN** the header renders
- **THEN** the "Diff" header shows an up arrow indicator and other sortable headers show a bidirectional arrow

### Requirement 5: JavaScript refresh integration
The `refresh()` function SHALL include `case 'evaluation': await refreshEvaluation(); break;` and `case 'hypotheses': await refreshHypotheses(); break;` in its switch statement. These cases SHALL follow the same pattern as the existing 5 tabs.

#### Scenario: Refresh dispatches to new tabs
- **GIVEN** `activeTab` is `"evaluation"`
- **WHEN** the 30-second refresh fires
- **THEN** `refreshEvaluation()` is called

#### Scenario: Refresh dispatches to hypotheses
- **GIVEN** `activeTab` is `"hypotheses"`
- **WHEN** the 30-second refresh fires
- **THEN** `refreshHypotheses()` is called

### Requirement 6: Evaluation JavaScript state
The `index.html` SHALL define evaluation state variables: `evalRunId` (current run ID), `evalTrials` (full trial array from API), `evalFilter` (`{category: null, volume_tier: null}`), `evalSortCol` (current sort column), and `evalSortDir` (current sort direction). The `clearEvalFilter()` function SHALL reset the filter state and re-render the drill-down table.

#### Scenario: State initialization
- **WHEN** the page loads
- **THEN** `evalRunId` is `null`, `evalTrials` is `[]`, `evalFilter` is `{category: null, volume_tier: null}`

### Requirement 7: Hypotheses JavaScript state
The `index.html` SHALL define `hypStatusFilter` (default `"all"`) and the `filterHypStatus(status)` function that toggles the active class on filter buttons and re-renders the hypothesis table. The `showHypDetail(id)` and `closeHypDetail()` functions SHALL toggle visibility between list and detail containers.

#### Scenario: Status filter toggle
- **WHEN** the user calls `filterHypStatus("testing")`
- **THEN** `hypStatusFilter` is `"testing"`, the "Testing" button has `active` class, and the table re-renders

### Requirement 8: Color scheme consistency
All new chart and UI elements SHALL use the established color palette: agent blue `#3b82f6`, market/neutral slate `#475569`, agent-better green `#22c55e`, market-better red `#ef4444`, muted annotations `#94a3b8`, dark background `#0f172a`, card background `#1e293b`, border `#334155`, text `#e2e8f0`.

#### Scenario: Color consistency check
- **WHEN** the Evaluation tab charts render
- **THEN** agent data uses `#3b82f6`, market data uses `#475569`, positive diffs use `#22c55e`, negative diffs use `#ef4444`, matching the existing dashboard color language

### Requirement 9: Drill-down search input event binding
The `#eval-search` input SHALL have an `input` event listener that calls `renderEvalDrilldown()` on each keystroke, enabling live filtering of the trial table as the user types.

#### Scenario: Live search filtering
- **GIVEN** 20 trials are displayed in the drill-down table
- **WHEN** the user types "Bitcoin" in the search input
- **THEN** only trials with "Bitcoin" in the question field remain visible, without requiring a submit action

## Scenarios

### Scenario: File size and structure
- **GIVEN** the existing `index.html` is approximately 815 lines
- **WHEN** the Evaluation and Hypotheses tabs are added
- **THEN** the file grows to approximately 1400-1500 lines, remaining a single self-contained file with no build step and no new external dependencies

### Scenario: No new CDN dependencies
- **GIVEN** the existing `index.html` loads Plotly.js (`plotly-basic-2.35.2`) and PicoCSS from CDN
- **WHEN** the new tabs are added
- **THEN** no additional CDN scripts or stylesheets are added; all new functionality uses the existing libraries
