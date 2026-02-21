## Purpose

Delta spec for the existing backtest-cli capability. Adds a `backtest evaluate` subcommand that plans a budget-aware multi-model evaluation, executes it with stratified sampling and progressive gate checks, and produces a statistical comparison report. Existing `backtest simulate` and `backtest results` commands are unchanged.

## ADDED Requirements

### Requirement: Evaluate subcommand registration
The CLI MUST register a `backtest evaluate` command via Click under the existing `backtest` group. The command MUST be accessible as `polymarket backtest evaluate`.

#### Scenario: Command is discoverable
- **WHEN** `polymarket backtest --help` is invoked
- **THEN** `evaluate` appears in the list of subcommands with a brief description

### Requirement: Evaluate command options
The `evaluate` command MUST accept the following Click options:
- `--models / -m` (multiple=True): Model names to evaluate. Accepts short names (`haiku`, `sonnet`, `opus`). Default: `["haiku", "sonnet"]`.
- `--trials-per-cell` (int, default 20): Minimum trials per category x volume tier cell.
- `--categories` (multiple=True): Categories to include. `"null"` means NULL category. Default: auto-discover.
- `--horizon` (int, default 7): Days before resolution.
- `--budget` (float, optional): Maximum total LLM cost in USD.
- `--all-at-once` (flag): Run all models without intermediate prompts.
- `--dry-run` (flag): Preview selection and cost estimate without running.

#### Scenario: Short model names resolved
- **GIVEN** `--models haiku --models opus`
- **WHEN** the command processes options
- **THEN** `"haiku"` is resolved to `"claude-haiku-4-5-20251001"` and `"opus"` to `"claude-opus-4-6"` via `MODEL_ALIASES`

#### Scenario: Default models when none specified
- **GIVEN** no `--models` flag is provided
- **WHEN** the command runs
- **THEN** Haiku and Sonnet are used (Opus is opt-in due to cost)

### Requirement: Model alias resolution
`MODEL_ALIASES` dict in `cli/main.py` MUST map short names to full model IDs: `"haiku"` to `"claude-haiku-4-5-20251001"`, `"sonnet"` to `"claude-sonnet-4-6"`, `"opus"` to `"claude-opus-4-6"`. Unrecognized model names MUST be passed through as-is (assumed to be full model IDs).

#### Scenario: Unknown model name passed through
- **GIVEN** `--models claude-custom-model-1`
- **WHEN** the alias resolver processes it
- **THEN** `"claude-custom-model-1"` is used as-is

### Requirement: Evaluation plan display
Before executing, the command MUST display an evaluation plan showing: discovered/specified categories, volume tiers, trials per cell, total cells (categories x tiers), and horizon.

#### Scenario: Plan shows auto-discovered categories
- **GIVEN** no `--categories` flag and the database contains null, crypto, and politics markets
- **WHEN** the evaluation plan is displayed
- **THEN** categories are listed as `(null), crypto, politics`

### Requirement: Market selection summary display
After stratified selection, the command MUST display a table showing each (category, tier) cell with the number of markets available and selected. Cells with fewer than `trials-per-cell` markets MUST be flagged with `[!]`.

#### Scenario: Shortfall flagged
- **GIVEN** the `crypto x >10M` cell has 5 available markets and 20 requested
- **WHEN** the selection summary is displayed
- **THEN** the row shows `5 available, 5 selected [!]`

### Requirement: Cost estimate display
After market selection, the command MUST display a cost estimate table showing each model with its cost per trial, total trial count, and estimated total cost. If `--budget` is set, it MUST show whether each model fits within the remaining budget.

#### Scenario: All models fit budget
- **GIVEN** `--budget 50` and estimated total cost of $31.08
- **WHEN** the cost estimate is displayed
- **THEN** the output shows "Budget: $50.00 -- all models fit within budget."

#### Scenario: Budget insufficient for last model
- **GIVEN** `--budget 7` with Haiku at $1.05 and Sonnet at $4.83 and Opus at $25.20
- **WHEN** the cost estimate is displayed
- **THEN** the output warns that Opus would exceed the budget

### Requirement: Confirmation prompt
In progressive mode (default), the command MUST prompt `Proceed with evaluation? [Y/n]` before starting the first model. If the user declines, the command MUST exit without making any LLM calls.

#### Scenario: User declines
- **GIVEN** the user responds `n` to the confirmation prompt
- **WHEN** the command processes the response
- **THEN** no simulation runs are started and the command exits cleanly

### Requirement: Dry run mode
When `--dry-run` is specified, the command MUST run `select_markets_stratified()`, display the evaluation plan, market selection summary, and cost estimate, then exit without invoking any LLM calls or persisting any simulation results.

#### Scenario: Dry run output
- **GIVEN** `--dry-run` is specified
- **WHEN** the command runs
- **THEN** the plan, selection, and cost estimate are displayed, and the command exits with message "Dry run complete -- no LLM calls made"

### Requirement: Progressive stage execution
In progressive mode, after each model completes, the command MUST display that model's intermediate results (agent Brier, market Brier, weighted Brier, 95% CI, actual cost, remaining budget) and prompt `Continue to {next_model} (~${estimated_cost})? [Y/n]`.

#### Scenario: User stops after Sonnet
- **GIVEN** progressive mode with models [haiku, sonnet, opus]
- **WHEN** the user responds `n` after Sonnet completes
- **THEN** Opus is not run, and the final report covers only Haiku and Sonnet

#### Scenario: Intermediate comparison shown
- **GIVEN** Haiku and Sonnet have both completed
- **WHEN** the Sonnet intermediate results are displayed
- **THEN** a pairwise comparison "Sonnet vs Haiku" with CI and significance is shown

### Requirement: All-at-once mode
When `--all-at-once` is specified, the command MUST run all models in sequence without interactive prompts between stages. Budget enforcement still applies (models that would exceed budget are skipped with a warning).

#### Scenario: Batch execution
- **GIVEN** `--all-at-once` with 3 models and sufficient budget
- **WHEN** the command runs
- **THEN** all 3 models run without any interactive prompts and the final report is displayed at the end

### Requirement: Final comparison report
After all models complete (or the user stops), the command MUST display a final comparison report using Rich tables. The report MUST include: a model comparison table (Brier, weighted Brier, vs market, 95% CI, significance), a pairwise model comparison table, and a per-category-x-model breakdown with cells below n=20 marked with `*`.

#### Scenario: Full report with three models
- **GIVEN** Haiku, Sonnet, and Opus all completed
- **WHEN** the final report is displayed
- **THEN** three Rich tables are rendered: model comparison (3 rows), pairwise comparison (3 rows: H-S, H-O, S-O), and category breakdown with per-model columns

### Requirement: Categories "null" string handling
When `--categories null` is specified on the CLI, the command MUST interpret the string `"null"` as SQL NULL (None in Python) for null-category market selection.

#### Scenario: Null category specified
- **GIVEN** `--categories null --categories crypto`
- **WHEN** the categories are passed to `select_markets_stratified()`
- **THEN** the categories list is `[None, "crypto"]`

## MODIFIED Requirements

(None. Existing `backtest simulate` and `backtest results` commands are unchanged.)

## Backward Compatibility

### Requirement: Existing commands unchanged
The `backtest simulate` and `backtest results` commands MUST continue to work with their existing flags and produce identical output to before this change.

#### Scenario: Existing simulate command
- **WHEN** `polymarket backtest simulate --count 20 --min-volume 1000000 --horizon 7` is invoked
- **THEN** it runs identically to before, with no reference to the new evaluate functionality

#### Scenario: Existing results command
- **WHEN** `polymarket backtest results --run-id 3` is invoked
- **THEN** it displays the same output as before, even though the trials table now has additional columns
