## Context

The dashboard has 7 tabs serving live trading and backtest analysis. Two recent tabs (Evaluation, Hypotheses) read from `backtest.db` via the `BacktestDB` class with soft-fail when the DB is missing. The `bt_markets` table has 90K+ resolved markets with `category`, `volume`, `end_date`, and `has_history` columns — all the raw material needed for corpus visualization without any new data collection.

The existing pattern is: `routes/<name>.py` → registered in `app.py` → consumed by `refreshX()` in `index.html`. This change follows that pattern exactly.

## Goals / Non-Goals

**Goals:**
- Surface corpus health at a glance: how many markets, what coverage, what mix
- Show category × has_history grouped bars (the key coverage gap view)
- Show volume tier distribution with coverage
- Show resolution date histogram with regime overlays (reusing existing regime data)
- Soft-fail gracefully when `backtest.db` is missing

**Non-Goals:**
- Price candle density analysis (requires scanning `bt_price_history`, too slow for a dashboard endpoint)
- Cross-run sampling overlap (requires instrumenting which markets each run hit)
- Live agent market coverage (different DB, different concern)
- Any writes to `backtest.db`

## Decisions

### 1. New tab vs. section inside Evaluation
**Decision**: New standalone "Data" tab.
**Rationale**: Corpus health is a different concern from evaluation results — it answers "what am I running against?" rather than "how did a run perform?". A separate tab keeps both views uncluttered and makes the Data tab useful even before any simulation runs exist.

### 2. Four endpoints vs. one omnibus endpoint
**Decision**: Four separate endpoints (`/summary`, `/by-category`, `/by-volume-tier`, `/temporal`).
**Rationale**: Matches the existing pattern (Evaluation has 6 separate endpoints). Allows parallel fetching via `Promise.all()`. Each query is independently cacheable. Avoids one large slow query.

### 3. SQL aggregations at query time vs. precomputed
**Decision**: Aggregate at query time (no caching layer).
**Rationale**: `bt_markets` is append-only and infrequently updated. 90K rows with simple GROUP BY queries will complete in <100ms on SQLite. Precomputation would add complexity with no meaningful benefit.

### 4. Grouped bars (total + has_history) vs. single bars
**Decision**: Grouped bars showing both `total` and `with_history` per category/tier.
**Rationale**: The user's primary question is coverage gaps — "which categories have sparse price history?" A single bar chart can't answer this. The grouped view makes the gap immediately visible.

### 5. Regime overlays on temporal chart
**Decision**: Reuse `bt_regimes` data (already fetched in Evaluation temporal chart) as vertical band overlays on the resolution date histogram.
**Rationale**: The temporal context of which LLM era markets resolve in is exactly what the Evaluation temporal chart shows. Using the same regime data creates visual consistency across tabs.

### 6. Volume tiers
**Decision**: Five tiers: `<$10K`, `$10K–$100K`, `$100K–$1M`, `$1M–$10M`, `>$10M`.
**Rationale**: The $100K threshold is the price history collection cutoff — adding `<$10K` and `$10K–$100K` tiers makes it clear which markets can never have price history, explaining some coverage gaps.

## Risks / Trade-offs

- **Slow query on large DB** → Mitigated: all queries are simple COUNT/SUM GROUP BY on indexed columns (`category`, `volume`, `end_date`). No joins except to `bt_regimes` (tiny table).
- **Missing `backtest.db`** → Mitigated: same soft-fail pattern as Evaluation/Hypotheses tabs — returns `{"available": false}`, frontend shows empty state.
- **category = NULL markets** → Use `COALESCE(category, 'unknown')` to bucket uncategorized markets visibly rather than silently dropping them.
- **Date histogram sparsity** → Some months may have 0 markets. Frontend handles gracefully with Plotly's bar chart (just no bar for that month).

## Migration Plan

No migration needed. This is purely additive:
1. Add `routes/data.py`
2. Register router in `app.py`
3. Add tab to `index.html`

Rollback: remove the three additions. No DB changes, no schema changes.

## Open Questions

None — design is fully specified.
