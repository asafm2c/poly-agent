## Context

The Polymarket trading agent is a fully implemented scan-analyze-trade pipeline, but it currently operates as a feedforward system with no functioning feedback loops. Predictions are never reconciled with outcomes, positions are never re-evaluated for exits, price history is overwritten on every scan, and the `daily_pnl` table is never written. The calibration system (Pass 3) is fully coded but permanently disabled because `update_prediction_outcome()` is never called by the scheduler.

The system persists to a single SQLite database (WAL mode, 30s busy timeout). The scheduler uses APScheduler with four jobs: scan (15min), analysis (1hr), re-evaluation (4hr, stub), daily report (18:00 UTC).

## Goals / Non-Goals

**Goals:**
- Record price time-series so the system can observe its own performance
- Automatically detect market resolutions and close the calibration + position loops
- Replace the re-evaluation stub with real exit signal logic
- Activate the daily P&L circuit breaker (currently dead code)
- Keep LLM cost for re-evaluation under control (~$0.50/day)

**Non-Goals:**
- LLM self-reflection / meta-analysis (Level 4 — wait for data volume)
- Hypothesis-driven trading framework (Level 5 — future work)
- Cross-market memory within analysis cycles (Level 3 — marginal value now)
- Sell/exit order execution on the CLOB (paper mode only for now — sell logic is exit price mark, not live order)
- Persisting LLM cost data (stays ephemeral per session)

## Decisions

### D1: Price snapshots as a new table, not a time-series extension of markets

**Choice:** New `price_snapshots` table with `(market_id, timestamp, price_yes, price_no, volume)`. Append-only, one row per tracked market per scan cycle.
**Alternatives:** (a) Keep price history in the `markets` table as additional columns (breaks normalization, unbounded column growth), (b) Use a separate time-series database like TimescaleDB (overkill for our volume), (c) Snapshot all ~4700 markets every scan (450K rows/day — excessive for early-stage agent).
**Rationale:** Append-only table is simple, queryable, and doesn't change the existing `markets` schema. We snapshot only tracked markets (open positions + unresolved predictions) to keep storage bounded. All-market snapshots can be enabled later if pre-trade price context proves valuable. Add index on `(market_id, timestamp)`. Add a configurable retention period (default 30 days) with periodic cleanup.

### D2: Resolution detection piggybacks on the scan job

**Choice:** After `upsert_markets()` in `_scan_job`, iterate markets where `resolved=True` and check if we have open positions or unresolved predictions. Call `update_prediction_outcome()` and `resolve_positions()` for matches.
**Alternatives:** (a) Separate resolution check job (more scheduler complexity), (b) Poll Gamma API specifically for resolved markets (extra API call), (c) Check resolution only during re-evaluation (too slow — 4hr delay).
**Rationale:** The scan already fetches all market data including `resolved` and `resolution_outcome` fields. The Gamma API parser already populates these. Checking for resolutions after the scan adds ~1 DB query and is the natural place to detect state changes. Zero additional API cost.

### D3: Tiered re-evaluation — cheap edge check first, expensive LLM re-analysis only when needed

**Choice:** Two-tier re-evaluation:
- **Tier 1 (free):** For each open position, compute remaining edge as `original_estimate - current_market_price`. If edge is clearly positive (> threshold) or clearly gone (< 0), decide immediately: HOLD or EXIT.
- **Tier 2 (LLM, ~$0.025):** Only when the signal is ambiguous (edge between 0 and threshold, or position held > N days, or price moved dramatically against us). Run fresh research + 3-pass estimation. Compare new estimate to old.

**Alternatives:** (a) Full LLM re-analysis on every position every cycle (expensive — 10 positions * $0.025 * 6 cycles/day = $1.50/day), (b) Never re-analyze, only check edge mechanically (misses thesis-level changes), (c) Re-analyze on a fixed schedule regardless of edge state (wasteful).
**Rationale:** Most positions have clear edge state — either the market moved toward our estimate (edge shrinking) or away (edge growing). Only the ambiguous middle zone needs LLM intelligence. This keeps cost at ~$0.075-0.15/day while still catching thesis-level changes.

**Configurable parameters:**
- `reeval_edge_exit_threshold`: Below this remaining edge, exit without re-analysis (default: 0.0 — edge reversed)
- `reeval_reanalysis_threshold`: Below this remaining edge, trigger LLM re-analysis (default: `min_edge_threshold` / 2 = 0.05)
- `max_reanalyses_per_cycle`: Cap on LLM re-analysis calls per re-evaluation cycle (default: 3)

### D4: Paper exit trades are recorded as sell trades in the trades table

**Choice:** When a position is closed (by resolution or exit signal), record a corresponding `action='sell'` trade in the `trades` table. The `trades` schema already has the `sell` CHECK constraint but it's never used.
**Alternatives:** (a) Only update positions, don't record sell trades (incomplete audit trail), (b) Create a separate `exits` table (unnecessary complexity).
**Rationale:** The trade ledger should be a complete record of all activity. The schema already supports sells. This makes the daily report and trade history accurate.

### D5: Daily P&L computed and written by the daily report job

**Choice:** The `_daily_report_job` computes today's realized P&L (from positions closed today), unrealized P&L (mark-to-market of open positions using latest prices from `price_snapshots`), total P&L, portfolio value, and trade count. Writes to `daily_pnl` table via INSERT OR REPLACE.
**Alternatives:** (a) Write P&L on every trade (complex, doesn't capture unrealized), (b) Compute P&L in the risk manager on-demand (expensive repeated computation), (c) Write P&L at end of analysis job (wrong timing — should be end-of-day snapshot).
**Rationale:** Daily P&L is a daily concept. Computing it once at report time is clean and gives the risk manager fresh data for the next day's trading. The `_check_daily_loss()` function already reads from `daily_pnl` — it just needs data.

### D6: Schema migration via version 2

**Choice:** Add a second migration to `MIGRATIONS` list in `database.py` that creates the `price_snapshots` table and adds the index. Bump `SCHEMA_VERSION` to 2.
**Alternatives:** (a) Modify the existing migration (breaks existing databases), (b) Use a migration framework like Alembic (overkill for SQLite).
**Rationale:** The existing migration system supports sequential migrations. Adding version 2 is clean and doesn't require any new infrastructure. Existing databases will auto-migrate on next startup.

## Risks / Trade-offs

**[Price snapshot table grows large]** → Only tracked markets are snapshotted (typically a small fraction of ~4700 total), so growth is modest. Mitigate with a retention policy (default 30 days) and periodic cleanup in the daily report job. Add composite index `(market_id, timestamp)` for query performance. Can expand to all markets later if pre-trade price context proves valuable for analysis.

**[Resolution detection misses a resolution]** → If a market resolves between scans (15 min window), we catch it on the next scan. If the Gamma API doesn't report `resolved=True` reliably, positions stay open. Mitigate: also check `resolution_outcome IS NOT NULL` as an alternative signal. Worst case: manual resolution via CLI command.

**[Re-evaluation exit signals fire too aggressively]** → If the agent exits positions on small price movements, it could churn and lose to spreads. Mitigate: exit threshold is configurable, and paper mode has no spread cost. Set default exit threshold at edge < 0 (only exit when edge has fully reversed), not at some positive threshold.

**[LLM re-analysis produces different estimate than original]** → This is expected and desired — new information should update estimates. But if the LLM is noisy (estimates vary by 10% between identical calls), re-analysis could trigger false exits. Mitigate: only exit on re-analysis if the new estimate agrees with the market (both say our position is wrong), not just if the new estimate differs from the old one.

**[Daily P&L table only populated once per day]** → The risk manager's `_check_daily_loss()` reads today's P&L, but it's only written at the daily report time (18:00 UTC). Trades before that time won't see updated P&L. Acceptable for now — the daily loss limit is a safety net, not a real-time control. Can add intra-day P&L updates later if needed.
