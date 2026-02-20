## Purpose

Extend the strategy configuration loader to merge active hypothesis-driven actions into the returned config dict. When the strategy is loaded at startup or refresh, confirmed hypothesis actions are queried and their parameter adjustments (category targeting, category avoidance, edge overrides, weight adjustments) are merged into the appropriate config sections. User-explicit values in `strategy.yaml` always take precedence over hypothesis-driven values.

## MODIFIED Requirements

### Requirement: Hypothesis actions merged into strategy config
The `load_strategy_config()` function SHALL, after loading `strategy.yaml`, call `load_active_hypothesis_actions()` and merge the resulting actions into the config dict via a `_merge_hypothesis_actions()` helper. If hypothesis loading fails (e.g., database not initialized), the function SHALL log a warning and return the config without hypothesis actions.

#### Scenario: Strategy config includes hypothesis actions on load
- **GIVEN** a confirmed hypothesis "sports-no-alpha" with an active `category_avoid` action for "Match Winner"
- **WHEN** `load_strategy_config()` is called
- **THEN** the returned config dict has "Match Winner" in `market_selection.avoid_categories`

#### Scenario: Hypothesis loading failure is non-fatal
- **GIVEN** the backtest database does not exist or is not initialized
- **WHEN** `load_strategy_config()` attempts to load hypothesis actions
- **THEN** a warning is logged, and the config is returned with only the values from `strategy.yaml`

### Requirement: Category target actions add to target list
When a `category_target` action is active, its `config.category` SHALL be appended to `market_selection.target_categories` in the strategy config, if not already present.

#### Scenario: Category target appended
- **GIVEN** a confirmed hypothesis with a `category_target` action for category `null` (prediction markets)
- **WHEN** strategy config is merged
- **THEN** `market_selection.target_categories` includes the targeted category value

#### Scenario: Duplicate category target not re-added
- **GIVEN** `strategy.yaml` already includes "crypto" in `target_categories`, and a hypothesis action also targets "crypto"
- **WHEN** strategy config is merged
- **THEN** "crypto" appears only once in `target_categories`

### Requirement: Category avoid actions add to avoid list
When a `category_avoid` action is active, its `config.category` SHALL be appended to `market_selection.avoid_categories` in the strategy config, if not already present.

#### Scenario: Category avoid appended
- **GIVEN** a confirmed hypothesis with a `category_avoid` action for "Match Winner"
- **WHEN** strategy config is merged
- **THEN** `market_selection.avoid_categories` includes "Match Winner"

### Requirement: Edge override actions add to category overrides
When an `edge_override` action is active with `effective_strength > 0.1`, the effective threshold SHALL be inserted into `edge_thresholds.category_overrides` keyed by `config.applies_to`, only if that key is not already present (user values win).

#### Scenario: Edge override inserted for new category
- **GIVEN** a confirmed hypothesis with `edge_override` (`base_threshold=0.08`, `applies_to="100K-1M"`, `effective_strength=0.75`) and no existing "100K-1M" key in `category_overrides`
- **WHEN** strategy config is merged
- **THEN** `edge_thresholds.category_overrides["100K-1M"]` is set to `0.08 * (1.0 + (1.0 - 0.75) * 0.5) = 0.09`, rounded to 4 decimal places

#### Scenario: Edge override skipped when user value exists
- **GIVEN** `strategy.yaml` explicitly sets `edge_thresholds.category_overrides["100K-1M"]: 0.12` AND a hypothesis edge_override action also targets "100K-1M"
- **WHEN** strategy config is merged
- **THEN** the value remains 0.12 (user value preserved)

#### Scenario: Edge override skipped when strength too low
- **GIVEN** a hypothesis `edge_override` action with `effective_strength=0.05` (below the 0.1 minimum)
- **WHEN** strategy config is merged
- **THEN** the override is not applied (strength too low to justify influence)

### Requirement: All actions stored in hypothesis_actions key
All active actions (regardless of type) SHALL be appended to a `hypothesis_actions` key in the strategy config dict, making them available to downstream consumers like `build_recommendation()` for weight adjustments and logging.

#### Scenario: Hypothesis actions key populated
- **GIVEN** 3 active actions from 2 confirmed hypotheses
- **WHEN** strategy config is merged
- **THEN** `config["hypothesis_actions"]` contains all 3 action dicts with their `effective_strength` values

#### Scenario: No active actions
- **GIVEN** no confirmed hypotheses exist
- **WHEN** strategy config is merged
- **THEN** `config["hypothesis_actions"]` is an empty list

### Requirement: Strategy config merge is additive only
The merge function SHALL only add to the strategy config. It SHALL NOT remove categories from target or avoid lists, SHALL NOT lower edge thresholds below user-specified values, and SHALL NOT modify any field that was explicitly set in `strategy.yaml`.

#### Scenario: Merge does not remove existing avoid categories
- **GIVEN** `strategy.yaml` has `avoid_categories: ["politics"]` and no hypothesis action targets "politics" for removal
- **WHEN** strategy config is merged
- **THEN** "politics" remains in `avoid_categories`
