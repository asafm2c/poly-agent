## Why

Run #3 showed the agent beats the market on Brier score (-0.0113) across 20 trials with >$1M null-category markets at a 7-day horizon. But that's one model (Sonnet), one category slice, one volume tier, and only 20 trials. We don't know if Haiku's speed/cost ratio makes it viable for screening-quality estimation, whether Opus adds enough signal to justify 5x the cost, whether the agent has genuine alpha in politics vs crypto vs geopolitics, or how much of the "alpha" is training data contamination (the LLM may have memorized market outcomes that appeared in its training data). We need a systematic evaluation framework that varies model, category, volume tier, and temporal distance from training cutoffs -- then tests whether observed differences are statistically significant or just noise from small samples.

## What Changes

- Extend `run_simulation()` to accept a model override and store the model used per trial in `bt_simulation_trials`
- Add stratified market selection: instead of random sampling from one pool, sample N markets per category and N per volume tier to guarantee balanced coverage across dimensions
- Add temporal confidence weighting using `bt_regimes`: markets that resolved after a model's training cutoff get full weight, markets within the training window get discounted weight. Compute a `training_recency_score` per trial based on distance from the relevant model's cutoff date
- Add progressive multi-model orchestration: run the same market set through models in cost order (Haiku first, then Sonnet, then optionally Opus), with gate checks between stages. After each model completes, report intermediate results so the operator can decide whether to proceed to the next (more expensive) model. This avoids wasting $38 on Opus if Haiku already shows no signal in a category. The CLI supports `--progressive` (default) for staged execution with prompts, and `--all-at-once` for batch mode
- Add statistical analysis functions: confidence intervals on Brier score differences, paired t-tests or bootstrap tests for model-vs-model and model-vs-market comparisons, per-cell (category x volume x model) breakdowns with sample size warnings
- Add `polymarket backtest evaluate` CLI command that plans a budget-aware evaluation run, executes it across models, and produces a comparison report

## Capabilities

### New Capabilities
- `progressive-multi-model-evaluation`: Orchestrates running the same market set through LLM models in cost order (Haiku → Sonnet → Opus), with intermediate result reporting and gate checks between stages. Operator can stop early if a cheaper model already answers the question, or proceed to more expensive models for confirmation. Supports both progressive (interactive) and batch modes
- `stratified-market-selection`: Extends `select_markets()` with stratified sampling by category and volume tier, ensuring minimum trial counts per cell for statistical validity
- `temporal-confidence-weighting`: Computes per-trial training recency scores using `bt_regimes` boundaries and model-specific training cutoff dates, so aggregate metrics can down-weight potentially contaminated trials
- `statistical-comparison`: Confidence intervals on Brier differences, paired significance tests across models and dimensions, and per-cell breakdowns with "insufficient data" warnings when N < 20

### Modified Capabilities
- `simulation-runner`: Accept model override parameter, store model identifier per trial, support running against a pre-selected market set (for paired comparisons)
- `analysis-library`: Add cross-model comparison functions, training-recency-weighted aggregation, and statistical significance helpers
- `backtest-cli`: Add `evaluate` subcommand for multi-factor evaluation runs with budget planning

## Impact

- Modified: `src/polymarket_agent/backtest/simulator.py` -- model override parameter in `run_simulation()`, new `run_multi_model_evaluation()` orchestrator, stratified `select_markets_stratified()`
- Modified: `src/polymarket_agent/backtest/analysis.py` -- new functions: `cross_model_comparison()`, `training_recency_weights()`, `brier_confidence_interval()`, `stratified_breakdown()`
- Modified: `src/polymarket_agent/backtest/database.py` -- add `model` column to `bt_simulation_trials` if not present, add `training_recency_score` column
- Modified: `src/polymarket_agent/cli/main.py` -- add `backtest evaluate` command with `--models`, `--budget`, `--trials-per-cell` options
- Modified: `src/polymarket_agent/analyst/llm_client.py` -- add Opus to `MODEL_COSTS` dict
- Dependencies: `scipy` (for statistical tests) or pure-Python bootstrap -- prefer bootstrap to avoid adding a heavy dependency
- Cost estimate: Full 3-model evaluation with 20 trials/cell across 4 volume tiers and ~4 categories = ~320 trials per model, ~960 total. At $0.023/trial (Sonnet), $0.005/trial (Haiku), $0.12/trial (Opus): ~$7.36 Sonnet + $1.60 Haiku + $38.40 Opus = ~$47 total. Budget-aware mode can skip Opus or reduce trial counts to stay under a cap.

## Key Design Decisions

**Progressive execution with paired comparisons.** Running models in cost order (Haiku ~$1.60, Sonnet ~$7.36, Opus ~$38.40) lets us stop early when a cheaper model answers the question. After each model completes, intermediate results are printed (Brier by category/volume, comparison with prior models). The operator can decide: "Haiku shows no alpha in sports — skip Sonnet/Opus for that category." The same market set is used across all models for paired statistical tests, which are far more powerful than unpaired tests at the same sample size.

**Bootstrap over scipy.** A simple percentile bootstrap for confidence intervals avoids adding scipy as a dependency. 10K bootstrap resamples of Brier score differences gives reliable 95% CIs.

**Training cutoff as a continuous score, not a binary.** A market that resolved 1 day after a model's training cutoff is still suspicious. The `training_recency_score` scales from 0.0 (resolved during training window) to 1.0 (resolved 6+ months after cutoff), with linear interpolation. Weighted Brier scores use these as weights.

**Budget-aware planning.** Before running, the CLI prints expected cost by model and asks for confirmation. `--budget` flag sets a hard cap — if the next model would blow the budget, it gets skipped with a warning. In progressive mode, remaining budget is recalculated after each stage. Haiku always runs first (it's cheap enough to be the baseline and provides early signal).

**Minimum 20 trials per cell.** Below 20, confidence intervals are too wide to be actionable. The stratified sampler warns if any cell has fewer than 20 eligible markets and adjusts counts accordingly. The report flags cells below threshold as "insufficient data" rather than showing unreliable point estimates.
