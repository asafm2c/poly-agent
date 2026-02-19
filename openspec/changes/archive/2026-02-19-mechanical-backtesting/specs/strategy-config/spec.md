## ADDED Requirements

### Requirement: Strategy configuration file defines trading directives
The system SHALL use a `strategy.yaml` file to capture research-derived trading directives. The file SHALL include sections for market selection rules, per-category edge thresholds, regime awareness, and accumulated insights.

#### Scenario: Default strategy config created
- **WHEN** no `strategy.yaml` exists and the system starts
- **THEN** a default strategy config is created with conservative defaults: no category targeting (all categories), default edge thresholds, regime set to "unvalidated", and empty insights list

#### Scenario: Strategy config structure
- **WHEN** `strategy.yaml` is loaded
- **THEN** it contains sections: `version` (integer), `updated_at` (ISO date), `updated_by` (string describing source), `market_selection` (target/avoid categories, volume range, days-to-resolution range), `edge_thresholds` (per-category overrides, default, floor, ceiling), `regime_awareness` (current regime, efficiency trend, agent confidence), and `insights` (list of dated findings with confidence and implication)

### Requirement: Strategy config is human-reviewable and version-controllable
The strategy config SHALL be a plain YAML file that can be reviewed in git diffs, edited by hand, or updated programmatically. Updates SHALL increment the version number and record the source of the update.

#### Scenario: Research session updates strategy
- **WHEN** an LLM agent or human produces a strategy update from backtest analysis
- **THEN** the update is written to `strategy.yaml` with incremented version, current date in `updated_at`, description of source in `updated_by`, and the specific fields changed

#### Scenario: Strategy diff is reviewable
- **WHEN** a strategy update is proposed
- **THEN** the human can review the diff (via `git diff strategy.yaml`) before committing the change

### Requirement: Analysis library can propose strategy updates
The analysis library SHALL provide an `update_strategy_config()` function that modifies specific fields in `strategy.yaml` based on analysis findings. The function SHALL add an insight entry documenting what was changed and why.

#### Scenario: Category threshold updated from backtest
- **WHEN** backtest analysis shows crypto markets have 8% systematic bias and `update_strategy_config(category_overrides={"crypto": 0.12}, insight="Crypto 8% bullish bias across regimes")` is called
- **THEN** `strategy.yaml` is updated with the new crypto edge threshold, an insight entry is appended, version is incremented, and `updated_by` records the source

#### Scenario: Market selection updated from efficiency analysis
- **WHEN** efficiency analysis shows politics markets are highly efficient and `update_strategy_config(avoid_categories=["politics"])` is called
- **THEN** `strategy.yaml` adds "politics" to the avoid list and records the insight

### Requirement: Tactical layer reads strategy config at startup
The scheduler SHALL load `strategy.yaml` at startup and apply its directives to market selection, edge threshold computation, and logging. If the file does not exist, the scheduler SHALL use default behavior (no category filtering, existing threshold logic).

#### Scenario: Category filtering applied
- **WHEN** `strategy.yaml` specifies `target_categories: ["crypto", "science"]` and `avoid_categories: ["politics"]`
- **THEN** the scanner filters candidates to include only targeted categories and exclude avoided categories

#### Scenario: Edge threshold overrides applied
- **WHEN** `strategy.yaml` specifies `edge_thresholds.category_overrides.crypto: 0.12`
- **THEN** `compute_required_edge()` uses 0.12 as the base threshold for crypto markets instead of the default

#### Scenario: Missing strategy config uses defaults
- **WHEN** `strategy.yaml` does not exist
- **THEN** the scheduler operates with existing default behavior — no category filtering, standard threshold logic

#### Scenario: Strategy config logged at startup
- **WHEN** the scheduler starts and loads a strategy config
- **THEN** the active strategy is logged: targeted categories, avoided categories, override thresholds, current regime assessment, and config version

### Requirement: Strategy drift monitoring in daily report
The daily report SHALL compare actual predict-mode performance against strategy expectations and flag significant divergence.

#### Scenario: Performance matches expectations
- **WHEN** the daily report runs and the agent's rolling Brier score per category is within 0.05 of the strategy's expected efficiency level
- **THEN** the report notes "Strategy aligned" for that category

#### Scenario: Performance diverges from expectations
- **WHEN** the agent's Brier score in a category is more than 0.05 worse than expected based on strategy config
- **THEN** the daily report flags "Strategy drift: {category} underperforming. Brier {actual} vs expected {expected}. Research review recommended."

#### Scenario: Insufficient data for monitoring
- **WHEN** fewer than 10 predictions have resolved in a category
- **THEN** the report notes "Insufficient data for strategy monitoring in {category}"
