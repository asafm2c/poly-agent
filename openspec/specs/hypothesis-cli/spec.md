## Purpose

Provide CLI commands under `polymarket backtest hypothesis` for the full hypothesis workflow: listing hypotheses, proposing new ones, running targeted simulations, evaluating evidence, re-testing with recency weighting, viewing active actions, and checking for confidence decay. All commands use Rich for formatted output and integrate with the existing `backtest` CLI group.

## Requirements

1. The CLI SHALL provide a `hypothesis` subgroup under the existing `backtest` group, accessible as `polymarket backtest hypothesis`.

2. The `hypothesis list` command SHALL display all hypotheses in a Rich table with columns: ID, Name, Status, Confidence, Evidence Count, Last Evaluated, Category Filter, Volume Range. It SHALL accept an optional `--status` / `-s` flag (choices: `proposed`, `testing`, `confirmed`, `rejected`, `invalidated`, `all`; default: `all`).

3. The `hypothesis list` command SHALL color-code rows by status: green for confirmed, red for rejected, yellow for testing, dim for proposed, strikethrough for invalidated.

4. The `hypothesis propose` command SHALL accept required options `--name` / `-n` and `--description` / `-d`, plus optional options: `--category` / `-c`, `--volume-min`, `--volume-max`, `--regime` / `-r`, `--horizon`, and `--half-life` (default 90). It SHALL call `propose()` and display a Rich panel showing the created hypothesis with all parameters, its ID, and instructions for the next step.

5. The `hypothesis test` command SHALL accept a positional `HYPOTHESIS_ID` argument, optional `--count` / `-n` (default 50), and a `--dry-run` flag. It SHALL display the hypothesis being tested, delegate to the simulation progress display, and on completion show the evidence recorded and current evaluation status.

6. When `--dry-run` is specified on `hypothesis test`, the command SHALL preview the market selection (showing matching markets with question, category, volume) without invoking the LLM or recording any database records.

7. The `hypothesis evaluate` command SHALL accept a positional `HYPOTHESIS_ID` argument. It SHALL display a Rich panel containing: all evidence records (as a table), weighted metrics, status transition (if any), confidence score, and active actions (if the hypothesis is confirmed).

8. The `hypothesis retest` command SHALL accept a positional `HYPOTHESIS_ID` argument and optional `--count` / `-n` (default 50). It SHALL run a fresh simulation followed by evaluation, displaying the same output as `test` followed by `evaluate`.

9. The `hypothesis actions` command SHALL display all active hypothesis-driven actions in a Rich table with columns: Hypothesis, Action Type, Config Summary, Base Strength, Effective Strength, Active Since. Actions SHALL be grouped by hypothesis.

10. The `hypothesis decay-check` command SHALL display a Rich table showing each confirmed hypothesis with columns: Name, Original Confidence, Current (Decayed) Confidence, Days Since Evidence, Retest Threshold, Recommendation. The Recommendation column SHALL show one of: "OK", "RETEST", or "INVALIDATE".

11. All CLI commands MUST handle errors gracefully: invalid hypothesis IDs SHALL produce a user-friendly error message, not a stack trace. Database connection failures SHALL be caught and reported.

12. The `hypothesis propose` command SHOULD display the next step instruction: `polymarket backtest hypothesis test <id>`.

## Scenarios

#### Scenario: List all hypotheses
- **GIVEN** the database contains the 4 seed hypotheses (all `proposed`) and 1 user-created hypothesis (`testing`)
- **WHEN** `polymarket backtest hypothesis list` is invoked
- **THEN** a Rich table is displayed with 5 rows, showing each hypothesis's ID, name, status (color-coded), confidence, evidence count, last evaluated date, category filter, and volume range

#### Scenario: List filtered by status
- **GIVEN** 3 hypotheses exist: 1 proposed, 1 testing, 1 confirmed
- **WHEN** `polymarket backtest hypothesis list --status confirmed` is invoked
- **THEN** only the 1 confirmed hypothesis is displayed in the table

#### Scenario: Propose a new hypothesis
- **GIVEN** no hypothesis named "crypto-alpha" exists
- **WHEN** `polymarket backtest hypothesis propose --name "crypto-alpha" --description "Agent outperforms on crypto markets" --category crypto --volume-min 100000 --half-life 120` is invoked
- **THEN** a Rich panel is displayed showing: name "crypto-alpha", description, category_filter "crypto", volume_min 100000, half_life 120 days, status "proposed", and the instruction "Next: polymarket backtest hypothesis test <id>"

#### Scenario: Propose with duplicate name shows error
- **GIVEN** a hypothesis named "probable-no-alpha" already exists
- **WHEN** `polymarket backtest hypothesis propose --name "probable-no-alpha" --description "duplicate"` is invoked
- **THEN** a user-friendly error message is displayed indicating the name is already in use

#### Scenario: Test a hypothesis with simulation
- **GIVEN** a proposed hypothesis with ID 1
- **WHEN** `polymarket backtest hypothesis test 1 --count 30` is invoked
- **THEN** the hypothesis name and filters are displayed, the simulation runs with progress updates, and on completion the evidence record and evaluation status are shown

#### Scenario: Test with dry-run previews markets
- **GIVEN** a proposed hypothesis with ID 2 filtering for $100K-$1M volume
- **WHEN** `polymarket backtest hypothesis test 2 --dry-run` is invoked
- **THEN** matching markets are listed with question, category, and volume, but no LLM calls are made and no database records are created

#### Scenario: Test invalid hypothesis ID
- **GIVEN** no hypothesis with ID 999 exists
- **WHEN** `polymarket backtest hypothesis test 999` is invoked
- **THEN** a user-friendly error message is displayed: "Hypothesis 999 not found"

#### Scenario: Evaluate shows evidence and transition
- **GIVEN** a hypothesis in `testing` status with 2 evidence records and sufficient data to confirm
- **WHEN** `polymarket backtest hypothesis evaluate 1` is invoked
- **THEN** a Rich panel displays: an evidence table (run_id, trial_count, brier_diff, p_value, supports), weighted Brier diff, transition "testing -> confirmed", new confidence score, and a list of activated actions

#### Scenario: Evaluate inconclusive
- **GIVEN** a hypothesis in `testing` status with only 10 trials
- **WHEN** `polymarket backtest hypothesis evaluate 1` is invoked
- **THEN** the panel shows the evidence, notes insufficient data for a status transition, and displays `recommendation='inconclusive'`

#### Scenario: Retest runs simulation and evaluates
- **GIVEN** a confirmed hypothesis with ID 3
- **WHEN** `polymarket backtest hypothesis retest 3 --count 40` is invoked
- **THEN** a new simulation runs, new evidence is recorded, and the evaluation result is displayed (potentially showing a status change if new evidence contradicts)

#### Scenario: Actions displayed with strength scaling
- **GIVEN** a confirmed hypothesis "mid-volume-sweet-spot" at `confidence_score=0.60` with an `edge_override` (`base_strength=1.0`) and a `weight_adjustment` (`base_strength=0.8`)
- **WHEN** `polymarket backtest hypothesis actions` is invoked
- **THEN** a Rich table shows two rows grouped under "mid-volume-sweet-spot": edge_override with effective_strength 0.60, weight_adjustment with effective_strength 0.48

#### Scenario: No active actions
- **GIVEN** no hypotheses are confirmed
- **WHEN** `polymarket backtest hypothesis actions` is invoked
- **THEN** a message is displayed: "No active hypothesis actions"

#### Scenario: Decay check shows retest recommendations
- **GIVEN** a confirmed hypothesis with decayed confidence 0.40 (below retest_threshold 0.50)
- **WHEN** `polymarket backtest hypothesis decay-check` is invoked
- **THEN** a Rich table shows the hypothesis with columns: Name, Original Confidence, Current Confidence (0.40), Days Since Evidence, Retest Threshold (0.50), Recommendation ("RETEST")

#### Scenario: Decay check with healthy hypothesis
- **GIVEN** a confirmed hypothesis with recent evidence and decayed confidence 0.72 (above retest_threshold 0.50)
- **WHEN** `polymarket backtest hypothesis decay-check` is invoked
- **THEN** the table shows Recommendation "OK" for that hypothesis
