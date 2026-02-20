## Purpose

Provides statistical tools for comparing agent performance across models and dimensions: bootstrap confidence intervals on Brier score differences, paired significance tests, and per-cell breakdowns with sample size warnings. Uses percentile bootstrap (no scipy dependency) to determine whether observed performance differences are statistically significant or just noise from small samples.

## Requirements

### 1. Bootstrap confidence interval function signature
`brier_confidence_interval()` in `analysis.py` MUST accept `agent_briers: list[float]`, `market_briers: list[float]`, `weights: list[float] | None = None`, `n_bootstrap: int = 10_000`, `confidence: float = 0.95`, `seed: int | None = None`.

### 2. Bootstrap return structure
`brier_confidence_interval()` MUST return a dict with keys: `"mean_diff"` (float), `"ci_low"` (float), `"ci_high"` (float), `"p_value"` (float), `"n"` (int), `"significant"` (bool).

### 3. Paired difference computation
`brier_confidence_interval()` MUST compute paired differences as `agent_brier[i] - market_brier[i]` for each trial. Negative mean_diff indicates the agent is better than the market.

### 4. Percentile bootstrap method
The function MUST use percentile bootstrap: resample indices with replacement `n_bootstrap` times, compute the weighted mean of paired differences for each resample, then extract confidence interval bounds at `alpha/2` and `1 - alpha/2` percentiles where `alpha = 1 - confidence`.

### 5. Two-sided p-value
The p-value MUST be computed as the proportion of bootstrap means on the opposite side of zero from the observed mean. If the observed mean is negative, p_value = proportion of bootstrap means >= 0. If positive, p_value = proportion of bootstrap means <= 0.

### 6. Significance determination
`"significant"` MUST be `True` when `p_value < (1 - confidence)`, i.e., `p_value < 0.05` at the default 95% confidence level.

### 7. Reproducible results with seed
When `seed` is provided, `brier_confidence_interval()` MUST produce identical results across calls with the same inputs. The function MUST use `random.Random(seed)` for resampling.

### 8. Weighted bootstrap
When `weights` is provided, each bootstrap resample MUST compute a weighted mean of the paired differences using the corresponding weights for the resampled indices.

### 9. Unweighted fallback
When `weights` is None, the function MUST use uniform weights (equivalent to simple arithmetic mean).

### 10. No external dependencies
The bootstrap implementation MUST use only Python standard library (`random.choices()`, `random.Random`). It MUST NOT require scipy, numpy, or any other external statistical package.

### 11. Cross-model comparison function signature
`cross_model_comparison()` in `analysis.py` MUST accept `run_ids: list[int]` and `db_path: Path | None = None`.

### 12. Cross-model comparison return structure
`cross_model_comparison()` MUST return a dict with keys: `"models"` (per-model summary), `"pairwise"` (pairwise CI dicts keyed by model name tuples), `"by_category"` (per-category per-model breakdown), `"by_volume_tier"` (per-tier per-model breakdown), `"by_cell"` (per category x tier per-model breakdown with sample size info).

### 13. Paired trial matching
For pairwise comparisons, `cross_model_comparison()` MUST match trials across runs by `market_id`. Only trials where both models produced a valid estimate (non-NULL `agent_estimate`) MUST be included in pairwise tests.

### 14. Unpaired trials in per-model aggregates
Trials that failed estimation for one model but not another MUST still be included in per-model aggregate Brier scores. Only pairwise comparisons require paired data.

### 15. Per-model summary contents
Each entry in `"models"` MUST include: `"agent_brier"` (unweighted), `"agent_brier_weighted"` (recency-weighted), `"market_brier"`, `"brier_diff"`, `"brier_diff_weighted"`, `"trial_count"`, `"run_id"`, and the `"model"` identifier.

### 16. Pairwise comparison contents
Each entry in `"pairwise"` MUST include the full `brier_confidence_interval()` output comparing the two models' agent Brier scores, plus a human-readable `"label"` (e.g., "Sonnet vs Haiku").

### 17. Insufficient data warning
In `"by_cell"` breakdowns, each cell MUST include `"n"` (trial count) and `"sufficient"` (bool). `"sufficient"` MUST be `False` when `n < 20`.

### 18. Minimum sample size for CI
`brier_confidence_interval()` SHOULD warn when called with fewer than 10 paired observations, as confidence intervals become unreliable at very small sample sizes.

## Scenarios

### Scenario: Agent significantly beats market
- **GIVEN** 50 paired trials where agent Brier scores are consistently lower than market Brier scores
- **WHEN** `brier_confidence_interval(agent_briers, market_briers, confidence=0.95)` is called
- **THEN** `mean_diff` is negative, `ci_high` is below zero, `p_value < 0.05`, and `significant` is `True`

### Scenario: No significant difference
- **GIVEN** 50 paired trials where agent and market Brier scores are similar
- **WHEN** `brier_confidence_interval(agent_briers, market_briers)` is called
- **THEN** the confidence interval spans zero (ci_low < 0 < ci_high), `p_value >= 0.05`, and `significant` is `False`

### Scenario: Reproducible bootstrap with seed
- **GIVEN** the same input data
- **WHEN** `brier_confidence_interval(..., seed=42)` is called twice
- **THEN** both calls return identical `mean_diff`, `ci_low`, `ci_high`, and `p_value`

### Scenario: Weighted bootstrap discounts contaminated trials
- **GIVEN** 30 trials, 10 with weight=0.2 (near training cutoff) and 20 with weight=1.0
- **WHEN** `brier_confidence_interval(agent_briers, market_briers, weights=weights)` is called
- **THEN** the result is dominated by the 20 high-weight trials; low-weight trials contribute proportionally less

### Scenario: Cross-model comparison with three models
- **GIVEN** three simulation runs (Haiku, Sonnet, Opus) on the same market set
- **WHEN** `cross_model_comparison(run_ids=[4, 5, 6])` is called
- **THEN** `"models"` has 3 entries, `"pairwise"` has 3 entries (Haiku-Sonnet, Haiku-Opus, Sonnet-Opus), and `"by_cell"` breaks down each cell by all three models

### Scenario: Cell with insufficient data flagged
- **GIVEN** the `crypto x >10M` cell has only 5 paired trials
- **WHEN** `cross_model_comparison()` computes the cell breakdown
- **THEN** `by_cell[("crypto", ">10M")]` has `"n": 5` and `"sufficient": False`

### Scenario: Unpaired trial excluded from pairwise test
- **GIVEN** Haiku succeeded on market X but Sonnet returned NULL agent_estimate for market X
- **WHEN** the pairwise Haiku-vs-Sonnet test is computed
- **THEN** market X is excluded from the pairwise comparison but Haiku's trial for market X is included in Haiku's per-model aggregate

### Scenario: Small sample warning
- **GIVEN** only 5 paired trials exist
- **WHEN** `brier_confidence_interval()` is called
- **THEN** a warning is logged about insufficient sample size for reliable confidence intervals
