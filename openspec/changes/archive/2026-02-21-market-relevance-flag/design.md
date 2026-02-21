## Context

The backtest DB holds 90,496 resolved markets, all above $10K volume. Analysis of the
null-category slice ($10K–$500K, post-April 2025) shows 83% are "Bitcoin Up or Down"
15-minute tick markets — high-frequency crypto directional bets that LLMs cannot
meaningfully price. Sports matchups and economic indicator bucket markets account for
most of the rest. Legitimate LLM-tractable prediction markets are a small fraction of
the total.

Currently no query knows what kind of market it's looking at. Simulation, evaluation,
and hypothesis testing all draw from the full pool or rely on caller-supplied ad-hoc
WHERE clauses that duplicate the same fragile exclusion logic. The gap between "what
the thesis targets" and "what backtests actually run on" is the central validity
problem for the entire evaluation pipeline.

## Goals / Non-Goals

**Goals:**
- Add a persistent `market_type` column to `bt_markets`, computed once, queryable everywhere
- Implement a deterministic rule-based classifier requiring no LLM calls or external data
- Backfill all 90K existing rows in a single migration pass
- Make `market_type = 'prediction'` the default filter in `select_markets()` and `select_markets_stratified()`
- Expose `--market-type` CLI option on `simulate` and `evaluate` to override the default

**Non-Goals:**
- LLM-based classification (adds cost and latency; rule-based is sufficient)
- Classifying live trading markets (separate pipeline; out of scope)
- Sub-classifying `prediction` into politics/science/crypto/etc (future work)
- Changing what gets *collected* — imports remain unfiltered; classification happens post-collection

## Decisions

### 1. Rule-based classifier, no LLM

**Chosen:** Pure keyword + category string matching in Python.
**Alternative:** Haiku classification pass (~$3–5 for 90K markets, ~2 hrs).
**Rationale:** The distinguishing signals are unambiguous patterns — "Up or Down" in
the question, spread/O/U in the category — that don't require semantic understanding.
Rule-based is instant, free, reproducible, and testable without API keys.

### 2. TEXT enum over boolean

**Chosen:** `market_type TEXT` with values `prediction | tick | sports | economic-range | unknown`.
**Alternative:** `is_relevant INTEGER` (0/1 boolean).
**Rationale:** The enum preserves the classification basis for future sliced analysis
(e.g., "does agent have any edge on economic-range markets?"). A boolean collapses
that information permanently. Querying `market_type = 'prediction'` is equally clean.

### 3. Classification priority order

Rules applied in this order; first match wins:

1. **tick** — `question LIKE '%Up or Down%'`
   Catches all 15-min and hourly crypto direction markets.

2. **sports** — category in known sports set OR `question LIKE '% vs.%'`
   Known sports categories: `Match Winner`, `Game N Winner`, `Map N Winner`,
   `Both Teams to Score`, and any category matching `Spread*` or `O/U*`.
   The `vs.` question pattern catches tennis/cricket/esports with null category.

3. **economic-range** — category matches numeric bucket pattern
   Regex: `^\d[\d,.\- ]*$` (starts with digit, contains only digits/commas/hyphens/spaces).
   Catches "3,400", "88,000-90,000", "December 31" range markets.

4. **prediction** — everything else
   Default for null-category markets not caught above.

5. **unknown** — should not occur with rules above; defensive fallback.

**Rationale:** Tick is the highest-volume false positive and must be excluded first.
Sports and economic-range are excluded by category when possible; question-text
fallback catches cases where sports leaked into null-category.

### 4. Schema migration via ALTER TABLE + single-pass UPDATE

SQLite supports `ALTER TABLE ... ADD COLUMN` without locking. Backfill runs as a
Python loop (batch CASE WHEN UPDATE) or a sequence of targeted UPDATE statements.
At 90K rows with pure string matching, this completes in seconds.

Index on `market_type` added post-backfill for efficient WHERE filtering.

### 5. Default filter in select_markets() and select_markets_stratified()

Both functions gain `market_types: list[str] | None = None` parameter. When `None`,
the default is `['prediction']`. Passing `market_types=['prediction', 'sports']` or
`market_types=None` (explicit override to disable) is supported via CLI.

**Rationale:** Opt-in to non-prediction types is safer than opt-out. Existing callers
that don't pass `market_types` automatically get the correct filtered behavior.

## Risks / Trade-offs

**Rule gaps → misclassification** → Mitigation: `backtest backfill --stats` reports
counts per type after classification; spot-check `unknown` rows to find gaps. Rules
can be tightened without re-migration (just re-run backfill).

**Sports bleed through vs. pattern** → The `vs.` pattern will match some non-sports
questions (rare). These will be typed `sports` and excluded from `prediction` pool.
Acceptable: false positives (excluding real prediction markets) are less harmful than
false negatives (including sports in the prediction pool).

**Schema migration on live DB** → `backtest.db` is local-only, not shared. No
migration coordination needed. Backfill is idempotent; re-running overwrites existing
classifications.

**Classifier drift** → New market patterns may emerge not covered by initial rules.
Mitigation: `unknown` count in `--stats` surfaces unclassified markets; rules are
centralized in one module.

## Migration Plan

1. `ALTER TABLE bt_markets ADD COLUMN market_type TEXT`
2. Add index: `CREATE INDEX idx_bt_markets_market_type ON bt_markets(market_type)`
3. Run `polymarket backtest backfill` — applies classification rules to all rows
4. Verify with `backtest backfill --stats`: confirm expected distribution
   (~28K tick, ~8K sports, ~5K economic-range, ~49K prediction, <1K unknown)
5. No rollback needed — column addition is additive; old queries still work (column is nullable until backfill)

## Open Questions

None — classification rules are deterministic and validated against known DB samples.
