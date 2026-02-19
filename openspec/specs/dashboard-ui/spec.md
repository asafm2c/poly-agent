## Requirements

### Requirement: Single-page dashboard served as static HTML
The dashboard SHALL serve a single `index.html` file via FastAPI's `StaticFiles` mount at the root path `/`. The file SHALL contain all HTML, CSS, and JavaScript inline (no separate asset files). External libraries (Pico CSS, Plotly.js) SHALL be loaded from CDN.

#### Scenario: Load dashboard in browser
- **WHEN** a browser navigates to `http://host:port/`
- **THEN** the full dashboard page loads with dark theme, navigation tabs, and chart containers

### Requirement: Dark theme styling
The dashboard SHALL use a dark color scheme (dark background, light text) suitable for long-duration monitoring. Pico CSS SHALL be used in dark mode (`data-theme="dark"`) as the base stylesheet.

#### Scenario: Visual appearance
- **WHEN** the dashboard loads
- **THEN** the background is dark (#0f172a), text is light (#e2e8f0), and cards/charts have subtle borders on a slightly lighter background (#1e293b)

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

### Requirement: Kill switch status indicator
The dashboard SHALL display a status badge in the navigation bar showing whether trading is active (green badge "TRADING ACTIVE") or halted (red pulsing badge "KILL SWITCH ACTIVE").

#### Scenario: Kill switch inactive
- **WHEN** the portfolio summary reports `kill_switch_active: false`
- **THEN** a green badge reading "TRADING ACTIVE" is displayed

#### Scenario: Kill switch active
- **WHEN** the portfolio summary reports `kill_switch_active: true`
- **THEN** a red pulsing badge reading "KILL SWITCH ACTIVE" is displayed

### Requirement: Portfolio tab with KPI cards and charts
The Portfolio tab SHALL display four KPI cards at the top: Portfolio Value, Cash Balance, Total Return %, and Today's P&L. Positive values SHALL be green, negative values SHALL be red. Below, a Plotly line chart of portfolio value over time with range slider, and a daily P&L bar chart with green/red color coding.

#### Scenario: Positive returns
- **WHEN** total_return_pct is 5.2 and today_pnl is 12.50
- **THEN** both values are displayed in green

#### Scenario: No equity data
- **WHEN** the equity-curve endpoint returns empty arrays
- **THEN** an empty state message is displayed instead of blank charts

### Requirement: Positions tab with tables and expandable price charts
The Positions tab SHALL display: (1) open positions table with columns Market, Side, Shares, Entry Price, Current Price, Unrealized P&L, Return %, Agent Estimate, Edge Remaining, Days Held, and a chart expand button; (2) closed positions table and recent trades table side-by-side. Rows SHALL be color-coded by P&L. Clicking "chart" on a position row SHALL insert an inline Plotly price history chart.

#### Scenario: Expand price chart
- **WHEN** the user clicks the "chart" button on an open position row
- **THEN** an inline Plotly chart of the market's YES price history is inserted below the row

#### Scenario: No open positions
- **WHEN** the open positions endpoint returns an empty list
- **THEN** a "No open positions" empty state message is displayed

### Requirement: Calibration tab with accuracy analysis
The Calibration tab SHALL display: (1) four KPI cards for Agent Brier Score, Market Brier Score, Comparison result, and Prediction counts; (2) calibration curve scatter plot with diagonal perfect-calibration reference line, marker size proportional to bucket count; (3) individual prediction scatter plot (estimate vs outcome) colored by category; (4) category performance grouped bar chart comparing agent vs market Brier scores.

#### Scenario: Calibration with resolved predictions
- **WHEN** the calibration report includes Brier scores and bucket data
- **THEN** the calibration curve shows data points, the scatter shows individual predictions, and the category chart shows grouped bars

#### Scenario: No resolved predictions
- **WHEN** calibration data has no resolved predictions
- **THEN** KPI values show dashes and charts show empty state messages

### Requirement: Operations tab with status and predictions
The Operations tab SHALL display: (1) four KPI cards for Active Markets, Categories, Pending Predictions, and Kill Switch status; (2) recent predictions table with columns Time, Market, Category, Estimate, Market Price, Edge, Threshold, Outcome badge, and Thesis (truncated with hover expansion); (3) daily trade count bar chart for the last 30 days.

#### Scenario: Prediction outcome badges
- **WHEN** a prediction has resolved with outcome 1.0
- **THEN** the Outcome column shows a green "YES" badge

#### Scenario: Pending prediction
- **WHEN** a prediction has no outcome yet
- **THEN** the Outcome column shows a gray "pending" badge

### Requirement: Graceful error handling in frontend
The dashboard frontend SHALL handle API errors without clearing existing data. If an API call fails, the "Last updated" indicator SHALL show "Error: [message]" and previously rendered charts and tables SHALL remain visible.

#### Scenario: API endpoint returns error
- **WHEN** a fetch call fails with a network or server error
- **THEN** the error is logged to console, the refresh info shows the error, and existing rendered content remains unchanged

### Requirement: Responsive layout
The dashboard SHALL use CSS grid for two-column layouts (calibration charts, closed positions / trades). On viewports narrower than 900px, columns SHALL stack vertically.

#### Scenario: Narrow viewport
- **WHEN** the browser window is narrower than 900px
- **THEN** paired sections stack vertically instead of side-by-side
