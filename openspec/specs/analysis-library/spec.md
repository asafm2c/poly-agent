## ADDED Requirements

### Requirement: Composable market loading with filtering
The analysis library SHALL provide a `load_markets()` function that queries the backtest database and returns market records with their price histories. The function SHALL accept optional filters for category, regime, volume range, resolution outcome, and date range.

#### Scenario: Load all markets
- **WHEN** `load_markets()` is called with no filters
- **THEN** all markets with price history in the backtest DB are returned with their metadata and daily candles

#### Scenario: Load by category and regime
- **WHEN** `load_markets(category="crypto", regime="o1-era")` is called
- **THEN** only crypto markets that resolved during the o1-era regime period are returned

#### Scenario: Load by volume range
- **WHEN** `load_markets(volume_min=5000, volume_max=500000)` is called
- **THEN** only markets within that volume range are returned

### Requirement: Market efficiency index measures pricing accuracy
The analysis library SHALL provide an `efficiency_index()` function that computes the average absolute deviation between market price and resolution outcome at specified time horizons before resolution. Lower values indicate more efficient markets.

#### Scenario: Efficiency at multiple horizons
- **WHEN** `efficiency_index(markets, horizons=[30, 7, 1])` is called
- **THEN** the function returns the mean |price - outcome| at 30 days, 7 days, and 1 day before resolution for each market set

#### Scenario: Efficiency compared across regimes
- **WHEN** efficiency is computed per regime
- **THEN** the results show whether markets became more efficiently priced in later regimes (evidence of improving prediction quality, potentially from LLM agents)

#### Scenario: Efficiency compared across categories within a regime
- **WHEN** efficiency is computed per category within a single regime
- **THEN** the results show which categories are most and least efficiently priced, identifying where mispricings are plausible

### Requirement: Category calibration measures systematic bias
The analysis library SHALL provide a `category_calibration()` function that computes per-category calibration: average market price vs average resolution outcome. Non-zero bias indicates systematic over- or under-pricing.

#### Scenario: Category with bullish bias
- **WHEN** markets in category "crypto" have an average final price of 0.55 but average resolution of 0.40
- **THEN** `category_calibration()` returns a bias of +0.15 for crypto (market overestimates YES)

#### Scenario: Well-calibrated category
- **WHEN** markets in a category have average price within 0.02 of average resolution
- **THEN** the calibration function reports near-zero bias for that category

#### Scenario: Calibration by regime
- **WHEN** `category_calibration(regime="o1-era")` is called
- **THEN** only markets from that regime are included, enabling tracking of whether biases persist or correct over time

### Requirement: Price momentum signal detects directional trends
The analysis library SHALL provide a `price_momentum()` function that computes directional price movement over a configurable lookback window relative to a measurement point.

#### Scenario: Upward momentum computed
- **WHEN** a market's price increased by more than 0.05 over 7 days before a measurement point
- **THEN** the momentum function returns a positive value for that market

#### Scenario: Momentum validated against outcomes
- **WHEN** momentum is computed across all markets at 7 days before resolution
- **THEN** the results can be compared against actual outcomes to determine whether momentum predicts resolution direction

### Requirement: Cross-market arbitrage detects event-level inconsistencies
The analysis library SHALL provide a `cross_market_arbitrage()` function that detects when markets within the same event have YES prices summing to significantly more or less than 1.0 for mutually exclusive outcomes.

#### Scenario: Overpriced event detected
- **WHEN** an event has 3 mutually exclusive markets whose YES prices sum to 1.15
- **THEN** the function flags this event with a +0.15 deviation

#### Scenario: Single-market events skipped
- **WHEN** an event has only one market
- **THEN** the function returns no signal (not applicable)

### Requirement: Market baseline Brier score as null hypothesis
The analysis library SHALL provide a `market_baseline_brier()` function that computes the Brier score of using the market price at a specified horizon as the prediction. This serves as the baseline that any analysis must beat to demonstrate value.

#### Scenario: Baseline at 7 days before resolution
- **WHEN** `market_baseline_brier(markets, horizon=7)` is called
- **THEN** the function returns mean((price_at_7d - outcome)^2) across all markets with price data at that horizon

#### Scenario: Baseline compared to signal
- **WHEN** a signal's Brier score is lower than the market baseline
- **THEN** the signal demonstrates positive alpha (better predictive accuracy than the market price)

### Requirement: Regime comparison function
The analysis library SHALL provide a `regime_comparison()` function that runs any analysis function across all regimes and returns a side-by-side comparison, enabling trend detection.

#### Scenario: Efficiency trend across regimes
- **WHEN** `regime_comparison(efficiency_index, horizons=[7])` is called
- **THEN** the efficiency index is computed for each regime and returned in chronological order, making efficiency trends visible

#### Scenario: Category calibration evolution
- **WHEN** `regime_comparison(category_calibration)` is called
- **THEN** category biases are shown per regime, revealing whether biases are correcting over time

### Requirement: Analysis functions callable from any context
All analysis functions SHALL work when called from Python scripts, CLI commands, Jupyter notebooks, or by LLM agents via bash tool calls. Functions SHALL accept standard Python arguments and return structured dictionaries or lists, not print to stdout.

#### Scenario: LLM agent runs ad-hoc analysis
- **WHEN** an LLM agent executes `python3 -c "from polymarket_agent.backtest.analysis import *; print(category_calibration(load_markets(regime='o1-era')))"`
- **THEN** the analysis runs and returns structured results to stdout

#### Scenario: Human uses in notebook
- **WHEN** a human imports analysis functions in a Jupyter notebook
- **THEN** the functions return data structures suitable for further manipulation, plotting, or tabulation
