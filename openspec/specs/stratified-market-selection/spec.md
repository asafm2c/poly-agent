## Purpose

Provides stratified sampling of historical markets across category and volume tier dimensions, ensuring minimum trial counts per cell for statistical validity. This replaces ad-hoc random sampling when running systematic evaluations, guaranteeing balanced coverage so that per-cell comparisons have enough power to detect real differences.

## Requirements

### 1. Volume tier constants
`VOLUME_TIERS` dict in `simulator.py` MUST define four tiers: `">10M"` as (10,000,000, None), `"1M-10M"` as (1,000,000, 10,000,000), `"100K-1M"` as (100,000, 1,000,000), and `"10K-100K"` as (10,000, 100,000). These MUST match the tiers used in `simulation_by_volume_tier()` in `analysis.py`.

### 2. Function signature
`select_markets_stratified()` in `simulator.py` MUST accept parameters: `n_per_cell: int = 20`, `categories: list[str | None] | None = None`, `volume_tiers: dict[str, tuple[float, float | None]] | None = None`, `horizon: int = DEFAULT_HORIZON`, `db_path: Path | None = None`.

### 3. Return type
`select_markets_stratified()` MUST return a tuple of `(markets, cell_counts)` where `markets` is a list of market dicts and `cell_counts` is a dict keyed by `(category, tier_name)` tuples, each mapping to `{"requested": n, "available": m, "selected": k}`.

### 4. Category auto-discovery
When `categories` is None, the function MUST query distinct categories from `bt_markets` where the market is eligible (has_history=1, resolution_outcome in YES/NO, price data spanning the horizon window). NULL category MUST be included and appear first.

### 5. Market eligibility
A market MUST only be eligible for selection if it has `has_history = 1`, `resolution_outcome` in ('YES', 'NO'), volume within the tier's range, matching category (including NULL), and price history data at or before the horizon timestamp relative to its end date.

### 6. Random sampling within cells
Within each (category, volume_tier) cell, eligible markets MUST be randomly sampled up to `n_per_cell`. The sampling MUST use `ORDER BY RANDOM()` in SQL.

### 7. Shortfall handling without redistribution
If a cell has fewer than `n_per_cell` eligible markets, the function MUST select all available markets for that cell. The shortfall MUST be recorded in `cell_counts` (where `selected < requested`). The function MUST NOT redistribute unused quota from sparse cells to dense cells, as that would bias the sample.

### 8. Default volume tiers
When `volume_tiers` is None, the function MUST use the `VOLUME_TIERS` constant.

### 9. Custom categories
When `categories` is provided as a list, the function MUST use only those categories. The string `None` in the list SHOULD be interpreted as SQL NULL for null-category markets.

### 10. No duplicate markets
The returned market list MUST NOT contain duplicate market IDs, even if a market's volume places it at a tier boundary.

### 11. Horizon filtering
The function MUST only select markets that have at least one price history record with a timestamp at or before `end_date - horizon days`, consistent with the existing `select_markets()` horizon filter.

## Scenarios

### Scenario: Default stratified selection
- **GIVEN** the backtest DB contains markets across multiple categories and volume tiers
- **WHEN** `select_markets_stratified()` is called with defaults
- **THEN** categories are auto-discovered, `VOLUME_TIERS` are used, and up to 20 markets are selected from each cell

### Scenario: Cell with insufficient markets
- **GIVEN** the `crypto x >10M` cell contains only 5 eligible markets
- **WHEN** `select_markets_stratified(n_per_cell=20)` is called
- **THEN** all 5 markets are selected for that cell, `cell_counts[("crypto", ">10M")]` reports `{"requested": 20, "available": 5, "selected": 5}`, and no markets from other cells are added to compensate

### Scenario: Custom categories filter
- **GIVEN** categories `[None, "crypto"]` are specified
- **WHEN** `select_markets_stratified(categories=[None, "crypto"])` is called
- **THEN** only null-category and crypto markets are sampled; no politics, sports, or other categories appear

### Scenario: NULL category included in auto-discovery
- **GIVEN** the database contains markets with both named categories and NULL category
- **WHEN** categories are auto-discovered
- **THEN** NULL appears as the first category in the discovered list

### Scenario: Empty cell produces zero selections
- **GIVEN** no markets exist for `politics x >10M`
- **WHEN** `select_markets_stratified()` is called
- **THEN** `cell_counts[("politics", ">10M")]` reports `{"requested": 20, "available": 0, "selected": 0}` and the cell contributes no markets to the output

### Scenario: Custom volume tiers
- **GIVEN** only two tiers are desired: `{"high": (1_000_000, None), "low": (10_000, 1_000_000)}`
- **WHEN** `select_markets_stratified(volume_tiers={"high": (1_000_000, None), "low": (10_000, 1_000_000)})` is called
- **THEN** only those two tiers are used and cells are formed from categories x {high, low}

### Scenario: Horizon filtering excludes short-lived markets
- **GIVEN** a market has price data starting 3 days before resolution
- **WHEN** `select_markets_stratified(horizon=7)` is called
- **THEN** that market is excluded because it lacks price data at the 7-day horizon point
