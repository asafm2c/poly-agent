# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync                          # Core dependencies
uv sync --extra dashboard        # Include FastAPI dashboard

# Run the CLI
uv run polymarket [COMMAND]

# Run the dashboard
uv run polymarket-dashboard --port 8050

# Run all tests
uv run pytest tests/

# Run a single test
uv run pytest tests/test_backtest.py::TestBacktestDatabase::test_init_creates_tables -v

# Lint
uv run ruff check src/
uv run ruff check --fix src/
```

## Architecture

### Three-Loop Agent
The agent runs three concurrent loops:
1. **Research** (async): Gathers dossiers, news, price history per market
2. **Strategy** (daily): Scans markets, screens with Haiku, selects candidates
3. **Tactical** (15 min): Full analysis with Sonnet, calculates edge, executes trades

### LLM Probability Pipeline (4-pass)
Located in `src/polymarket_agent/analyst/estimator.py`:
1. **Base Rate** – Historical/domain baseline (Sonnet)
2. **Bayesian Update** – Incorporates research evidence (Sonnet)
3. **Adversarial** – Stress-tests the estimate (Sonnet)
4. **Calibration** – Applies historical Brier correction (optional)

Haiku is used for cheap market screening; Sonnet for full analysis.

### Two-Database Architecture
- **`polymarket_agent.db`** – Live portfolio, trades, positions, predictions (WAL mode)
- **`backtest.db`** – 90K+ resolved markets, simulation runs, hypothesis tracking (separate, soft failure if missing)

Both use SQLite with WAL mode. `BacktestDB` in `src/polymarket_dashboard/db.py` handles missing backtest.db gracefully.

### Module Structure
```
src/polymarket_agent/
  analyst/          # LLM probability estimation (estimator.py, llm_client.py, prompts/)
  backtest/         # Historical analysis: database.py, simulator.py, hypothesis.py, analysis.py
  cli/              # Click CLI (main.py entry point, commands/, scheduler.py)
  market/           # Gamma API, CLOB client, scanner, filter, storage
  trading/          # executor.py (live), paper.py (simulation), edge.py (Kelly sizing), calibration.py
  risk/             # manager.py: kill switch and exposure limits
  research/         # gatherer.py: async web search + domain data
  storage/          # database.py (main DB schema), snapshots.py
  config.py         # Pydantic BaseSettings (all config from .env)
  models.py         # Shared data models: Market, Trade, Position, ProbabilityEstimate

src/polymarket_dashboard/
  app.py            # FastAPI factory, 7-tab UI served at port 8050
  db.py             # DashboardDB and BacktestDB reader classes
  routes/           # One file per tab: portfolio, positions, calibration, operations,
                    # metrics, evaluation (6 endpoints), hypotheses (3 endpoints), data
```

### Hypothesis Tracker
`src/polymarket_agent/backtest/hypothesis.py` — structured experimentation system:
- Lifecycle: `proposed → testing → confirmed/rejected` (never permanently settled)
- Confidence decays exponentially (90-day half-life), triggering retests
- Actions (edge_override, category_target/avoid, model_preference, weight_adjustment) scale with confidence
- Strategy config and calibration prompts automatically incorporate active hypothesis actions

### Systematic Evaluation
`backtest evaluate` runs stratified sampling (category × volume tier), executes progressive Haiku → Sonnet evaluation, and computes per-model Brier scores with 10K-bootstrap confidence intervals and paired t-tests (no scipy dependency).

## Configuration
All settings live in `src/polymarket_agent/config.py` as a Pydantic `BaseSettings` class, sourced from `.env`. Key defaults:
- Screening model: `claude-haiku-4-5-20251001`
- Analysis model: `claude-sonnet-4-6`
- Kelly fraction: `0.5`, max position: `$50`, max portfolio: `$500`
- Scan interval: 900s (15 min), analysis: 3600s (1 hr)
- Simulation concurrency: 5

Required `.env` keys: `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`. Live trading additionally requires `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_FUNDER_ADDRESS`.

## Tests
- `tests/test_backtest.py` — 98 tests covering backtest DB, simulator, hypothesis tracker, evaluation
- `tests/test_integration.py` — 62 tests covering CLI, market pipeline, trading logic
- `tests/test_import_jobs.py` — import job tracking tests
- All tests use `tmp_path` fixtures; no external services required (API calls are mocked)

## OpenSpec Workflow
Structured changes follow: proposal → design → specs → tasks → implement → archive.
Active change artifacts live in `openspec/`. Specs for 16 capabilities are in `openspec/specs/`.
