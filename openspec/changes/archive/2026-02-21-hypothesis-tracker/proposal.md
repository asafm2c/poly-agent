## Why

We are accumulating findings from backtesting -- "LLMs temper overconfidence on probable-NO markets", "agent is market-neutral on >$1M volume", "$100K-$1M tier may be the sweet spot" -- but these insights live only in MEMORY.md and human memory. There is no systematic way to formulate testable hypotheses about where the LLM has innate alpha, track which hypotheses have been tested and their results, automatically integrate confirmed findings into the live trading pipeline, or update/invalidate hypotheses as new data comes in. The gap between "backtesting reveals X" and "live trading does Y because of X" is bridged entirely by manual intuition.

## What Changes

- Add a hypothesis data model to backtest.db: `bt_hypotheses` (with filters, status lifecycle, confidence score), `bt_hypothesis_evidence` (linking simulation runs to hypotheses with statistical metrics), and `bt_hypothesis_actions` (storing confirmed-hypothesis-driven parameter adjustments like edge overrides and category targeting)
- Add an iterative hypothesis lifecycle engine: propose hypotheses with testable filters (category, volume tier, model, temporal window), run targeted simulations against those filters, evaluate evidence with statistical rigor (minimum sample sizes, significance thresholds), and transition status (proposed → testing → confirmed/rejected). Critically, hypotheses are never permanently settled — confirmed hypotheses have a `confidence_decay` mechanism where their confidence score degrades over time and with new contrary evidence. Any hypothesis can be re-tested at any time, and re-evaluation can demote a confirmed hypothesis back to testing or invalidated. This prevents stale conclusions from permanently biasing prediction quality
- Add a `load_active_hypothesis_actions()` function that returns all active actions from confirmed hypotheses, queryable at startup by strategy config (`load_strategy_config`) and edge computation (`compute_required_edge`)
- Add integration points: the scheduler's `_check_strategy_drift` can cross-reference hypothesis predictions against live calibration data, and the calibration export (`export_calibration_for_llm`) can mention relevant confirmed hypotheses in Pass 3 prompts
- Add CLI commands under `polymarket backtest hypothesis` for listing, proposing, testing, evaluating, re-testing, and viewing active actions
- Add `hypothesis retest <id>` command that runs a fresh simulation against the hypothesis filters and re-evaluates with the new evidence weighted more heavily than old evidence
- Add `hypothesis decay-check` command that identifies hypotheses whose confidence has decayed below threshold and flags them for re-testing

## Capabilities

### New Capabilities
- `hypothesis-data-model`: Schema for `bt_hypotheses`, `bt_hypothesis_evidence`, and `bt_hypothesis_actions` tables in backtest.db, with status lifecycle (proposed/testing/confirmed/rejected/invalidated) and filter columns (category, volume range, model, temporal window)
- `hypothesis-lifecycle`: Iterative engine for proposing hypotheses with testable filters, running targeted simulations that match hypothesis criteria, evaluating evidence against statistical thresholds (Brier diff < -0.02, p < 0.05, n >= 30 for confirmation), and continuously re-evaluating. Key properties: (1) confidence decay — confirmed hypotheses lose confidence over time (configurable half-life, e.g., 90 days), triggering re-test when confidence drops below threshold; (2) re-evaluation — any hypothesis can be re-tested with new simulation runs, and new evidence is weighed against old using recency weighting; (3) demotion — a confirmed hypothesis reverts to testing/invalidated if new evidence contradicts it (e.g., 2 consecutive runs show no alpha); (4) versioning — each evaluation cycle is recorded, so the full history of a hypothesis's confirmation/invalidation is visible
- `hypothesis-actions`: System for translating confirmed hypotheses into conservative parameter adjustments (edge threshold overrides, category targeting/avoidance, model preferences, weight adjustments) stored as JSON configs and loadable by the live pipeline. Actions have `strength` proportional to the hypothesis confidence score — as confidence decays, action strength decays too (e.g., a 0.6 confidence hypothesis applies 60% of its edge adjustment). Actions are automatically deactivated when their hypothesis is demoted or invalidated
- `hypothesis-cli`: CLI commands for `hypothesis list`, `hypothesis propose`, `hypothesis test`, `hypothesis evaluate`, and `hypothesis actions`

### Modified Capabilities
- `analysis-library`: Add functions to query hypothesis evidence alongside simulation results, and to compute hypothesis-specific metrics from trial data
- `simulation-runner`: Accept optional `hypothesis_id` parameter to link simulation runs to hypotheses and auto-populate evidence records on completion
- `edge-computation`: Query active hypothesis actions at threshold computation time, applying confirmed edge overrides per category/volume tier
- `strategy-config`: Merge hypothesis-driven actions into strategy config loading, so confirmed findings automatically influence market selection and edge thresholds
- `calibration-tracker`: Include relevant confirmed hypotheses in the LLM calibration prompt export, giving the estimation pipeline awareness of its own validated strengths and weaknesses

## Impact

- New tables in backtest DB (`database.py` SCHEMA_SQL): `bt_hypotheses`, `bt_hypothesis_evidence`, `bt_hypothesis_actions` with appropriate indexes
- New module: `src/polymarket_agent/backtest/hypothesis.py` -- hypothesis CRUD, evidence recording, evaluation logic, action loading
- Modified: `src/polymarket_agent/backtest/database.py` -- add new table DDL to SCHEMA_SQL
- Modified: `src/polymarket_agent/backtest/simulator.py` -- accept optional `hypothesis_id`, auto-record evidence after simulation
- Modified: `src/polymarket_agent/backtest/analysis.py` -- add hypothesis-aware aggregation functions
- Modified: `src/polymarket_agent/backtest/strategy.py` -- `load_strategy_config` merges active hypothesis actions into returned config
- Modified: `src/polymarket_agent/trading/edge.py` -- `compute_required_edge` queries hypothesis actions for per-category/tier overrides
- Modified: `src/polymarket_agent/trading/calibration.py` -- `export_calibration_for_llm` appends confirmed hypothesis summaries
- Modified: `src/polymarket_agent/cli/scheduler.py` -- `_check_strategy_drift` cross-references hypothesis predictions
- Modified: `src/polymarket_agent/cli/main.py` -- add `backtest hypothesis` CLI subcommands
- Dependencies: No new external dependencies; uses existing SQLite, Click, Rich
- Key design constraints: statistical rigor (no confirmation on small samples), conservative actions (small threshold adjustments, not radical changes), iterability (no hypothesis is ever permanently settled — all can be re-tested and demoted), confidence decay (prevents stale conclusions from perpetually biasing the pipeline), and a focus on alpha discovery rather than full experiment tracking
