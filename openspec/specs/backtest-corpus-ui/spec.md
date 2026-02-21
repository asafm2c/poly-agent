## ADDED Requirements

### Requirement: Data tab displays corpus KPI strip
The dashboard SHALL include a "Data" tab with a KPI strip showing: total markets in `bt_markets`, count with `has_history=1`, coverage percentage (has_history / total × 100), resolution date range (MIN to MAX end_date), distinct category count, and volume range (MIN to MAX).

#### Scenario: Backtest DB is available
- **WHEN** the user opens the Data tab with a populated `backtest.db`
- **THEN** the KPI strip displays all 6 values with the coverage % color-coded (green ≥50%, yellow 25–49%, red <25%)

#### Scenario: Backtest DB is missing
- **WHEN** the user opens the Data tab and `backtest.db` does not exist
- **THEN** an empty state message is shown and no error is raised

### Requirement: Data tab displays category breakdown chart
The dashboard SHALL display a grouped bar chart per category showing total markets (gray) and markets with price history (blue), ordered by total descending. Markets with NULL category SHALL appear as "unknown".

#### Scenario: Multiple categories present
- **WHEN** `bt_markets` contains markets across multiple categories
- **THEN** each category renders as a group with two bars (total and with_history), ordered largest-to-smallest by total

#### Scenario: Category with zero price history
- **WHEN** a category has no markets with `has_history=1`
- **THEN** that category's "with_history" bar renders at zero height (not absent)

### Requirement: Data tab displays volume tier distribution chart
The dashboard SHALL display a grouped bar chart across five volume tiers (`<$10K`, `$10K–$100K`, `$100K–$1M`, `$1M–$10M`, `>$10M`) showing total markets and markets with price history per tier.

#### Scenario: Volume tier breakdown
- **WHEN** markets span multiple volume tiers
- **THEN** each tier renders as a group with total and with_history bars

#### Scenario: Tiers below collection threshold
- **WHEN** markets in `<$10K` or `$10K–$100K` tiers exist
- **THEN** those tiers render with near-zero with_history bars, confirming they are below the $100K collection threshold

### Requirement: Data tab displays temporal resolution histogram with regime overlays
The dashboard SHALL display a bar chart of market counts by resolution month (YYYY-MM), with vertical band overlays for each LLM regime from `bt_regimes`. Both total and with_history counts SHALL be shown per month.

#### Scenario: Temporal distribution with regimes
- **WHEN** markets span multiple years and regimes are defined in `bt_regimes`
- **THEN** the histogram shows monthly bars with colored vertical bands marking each regime boundary

#### Scenario: Months with no markets
- **WHEN** some months have zero markets
- **THEN** no bar is rendered for those months (Plotly sparse bar behavior)

### Requirement: Data API endpoints return corpus aggregations
The system SHALL expose four endpoints under `/api/data/`:
- `GET /api/data/summary` → 6 KPI values
- `GET /api/data/by-category` → list of {category, total, with_history}
- `GET /api/data/by-volume-tier` → list of {tier, total, with_history}
- `GET /api/data/temporal` → list of {month, total, with_history} + regimes list

All endpoints SHALL return `{"available": false}` when `backtest.db` is missing or tables do not exist.

#### Scenario: Summary endpoint with data
- **WHEN** `GET /api/data/summary` is called with a populated DB
- **THEN** response includes total_markets, with_history, coverage_pct, date_range_start, date_range_end, category_count, volume_min, volume_max

#### Scenario: Any endpoint with missing DB
- **WHEN** any `/api/data/*` endpoint is called and `backtest.db` is absent
- **THEN** response is `{"available": false}` with HTTP 200
