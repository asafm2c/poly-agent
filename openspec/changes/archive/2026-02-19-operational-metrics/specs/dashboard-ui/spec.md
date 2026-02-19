## MODIFIED Requirements

### Requirement: Four-tab navigation
The dashboard SHALL display a tab bar with five tabs: Portfolio, Positions, Calibration, Operations, and Costs & Ops. Only the active tab's content SHALL be visible. The Portfolio tab SHALL be active by default.

#### Scenario: Switch between tabs
- **WHEN** the user clicks the "Costs & Ops" tab
- **THEN** the Costs & Ops tab content is shown, all other tabs are hidden, and the Costs & Ops tab button is visually highlighted

#### Scenario: Initial load
- **WHEN** the dashboard loads for the first time
- **THEN** the Portfolio tab is active and its data is fetched immediately

### Requirement: Auto-refresh with active-tab optimization
The dashboard SHALL automatically refresh data every 30 seconds. Only the active tab's API endpoints SHALL be called during each refresh cycle. A "Last updated" timestamp SHALL be displayed in the navigation bar.

#### Scenario: Refresh on Portfolio tab
- **WHEN** the Portfolio tab is active and 30 seconds elapse
- **THEN** `/api/portfolio/summary` and `/api/portfolio/equity-curve` are fetched and charts are updated

#### Scenario: Refresh on Costs & Ops tab
- **WHEN** the Costs & Ops tab is active and 30 seconds elapse
- **THEN** `/api/metrics/summary`, `/api/metrics/timeseries`, `/api/metrics/cost-breakdown`, `/api/metrics/storage`, and `/api/metrics/recent` are fetched and charts are updated

#### Scenario: Tab switch triggers immediate refresh
- **WHEN** the user switches to the Costs & Ops tab
- **THEN** the Costs & Ops tab data is fetched immediately without waiting for the next refresh interval
