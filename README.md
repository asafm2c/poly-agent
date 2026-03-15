# market-edge

An autonomous prediction market trading agent powered by LLM probability estimation. The agent scans [Polymarket](https://polymarket.com) for mispriced markets, estimates probabilities using a multi-pass Claude pipeline, sizes positions with Kelly criterion, and executes trades or paper-trades against a local portfolio.

**Status:** Research / paper trading. No confirmed out-of-sample edge yet — see [Research Findings](#research-findings).

---

## Architecture

### Three-loop agent

```
┌──────────────────────────────────────────────────────────┐
│                     Autonomous Agent                      │
│                                                           │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Research   │  │   Strategy   │  │    Tactical    │  │
│  │   (async)   │  │   (daily)    │  │   (15 min)     │  │
│  │             │  │              │  │                │  │
│  │ Web search  │  │ Scan markets │  │ Full analysis  │  │
│  │ News/dossier│  │ Haiku screen │  │ Sonnet estimate│  │
│  │ Price history│  │ Candidates   │  │ Kelly sizing   │  │
│  └─────────────┘  └──────────────┘  │ Execute trade  │  │
│                                      └────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 4-pass LLM probability pipeline

Each market estimate goes through four passes:

1. **Base Rate** — Historical/domain prior (Claude Sonnet), no market price
2. **Bayesian Update** — Incorporates web-searched research dossier
3. **Adversarial** — Stress-tests the estimate against counterarguments
4. **Calibration** — Optional Brier score correction from historical performance

Haiku handles cheap market screening; Sonnet handles full analysis.

### Two-database architecture

| Database | Purpose |
|----------|---------|
| `polymarket_agent.db` | Live portfolio, trades, positions, predictions |
| `backtest.db` | 90K+ resolved markets, simulation runs, hypothesis tracker |

Both use SQLite with WAL mode.

### Module structure

```
src/polymarket_agent/
  analyst/      # LLM probability estimation (4-pass pipeline)
  backtest/     # Historical DB, simulator, hypothesis tracker, domain classifier
  cli/          # Click CLI entry point and commands
  market/       # Gamma API, CLOB client, scanner, filter, storage
  trading/      # Live executor, paper trading, Kelly sizing, calibration
  risk/         # Kill switch, exposure limits
  research/     # Async web search + domain data gathering
  storage/      # Main DB schema, price snapshots
  config.py     # Pydantic settings (all config from .env)
  models.py     # Shared data models

src/polymarket_dashboard/
  app.py        # FastAPI app (7-tab UI, port 8050)
  db.py         # DashboardDB and BacktestDB reader classes
  routes/       # portfolio, positions, calibration, operations,
                # metrics, evaluation, hypotheses, data
```

---

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [Anthropic API key](https://console.anthropic.com) (required)
- [Tavily API key](https://tavily.com) (required — web search for research)
- Polymarket private key + funder address (only for live trading)

---

## Installation

```bash
# Clone and install core dependencies
git clone https://github.com/datori/market-edge.git
cd trading
uv sync

# Install dashboard dependencies (optional)
uv sync --extra dashboard
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...

# Live trading only
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_FUNDER_ADDRESS=0x...

# Optional: Telegram alerts
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Key defaults (configurable via `.env`):
- Screening model: `claude-haiku-4-5-20251001`
- Analysis model: `claude-sonnet-4-6`
- Kelly fraction: `0.5`, max position: `$50`, max portfolio: `$500`
- Scan interval: 900s, analysis interval: 3600s

---

## Usage

### CLI

```bash
# Show config and API key status
uv run polymarket config

# Scan for market opportunities
uv run polymarket scan

# Run the full autonomous agent loop
uv run polymarket run

# Paper trade a specific market
uv run polymarket analyze <market-id>

# Portfolio overview
uv run polymarket portfolio

# Kill switch (stops live trading)
uv run polymarket kill
```

### Dashboard

```bash
uv run polymarket-dashboard --port 8050
# Open http://localhost:8050
```

Seven tabs: Portfolio · Positions · Calibration · Operations · Costs & Ops · Evaluation · Hypotheses

### Backtesting

The backtest system requires a separate `backtest.db` populated from Polymarket's historical data.

```bash
# Collect resolved markets (requires Gamma API access)
uv run polymarket backtest collect

# Run a simulation against historical markets
uv run polymarket backtest simulate --regime post-claude4 -n 50

# Multi-model evaluation with budget gating
uv run polymarket backtest evaluate --models haiku sonnet --budget 10 --dry-run

# Domain classification (actuarial vs current_event)
uv run polymarket backtest classify-domains --stats

# Hypothesis tracker
uv run polymarket backtest hypothesis list
uv run polymarket backtest hypothesis propose --name my-hypothesis --description "..."
uv run polymarket backtest hypothesis test <id>
```

---

## Research Findings

Seven experiments run across 22+ simulation runs (hundreds of trials). Full write-up in [`ideas/when-llm-leads.md`](ideas/when-llm-leads.md) and [`THESIS.md`](THESIS.md).

### The core result

| Signal | Brier score |
|--------|-------------|
| LLM base rate (no market price) | 0.2505 — near random |
| LLM anchored final estimate | 0.0261 |
| LLM blind estimate (no anchor) | 0.0905 — 3.5× worse |
| Market price | 0.0155 |

The LLM is a calibration layer on top of the market price, not an independent forecaster. When given the current market price, it produces well-calibrated final estimates. Without it, estimates are 3.5× worse.

### Where edge appeared — and why it didn't hold

**Seismic frequency markets** showed the strongest apparent signal (+0.014 Brier, n=53 trials): the LLM correctly applies global Poisson base rates (~12–15 M7.0+ earthquakes/year) while the market appeared to underprice intermediate time windows.

However, this signal is primarily a **contamination artifact**: all 25 seismic markets in the backtest DB resolve in 2025, entirely within the LLM's training window. The edge monotonically decays and reverses past the training cutoff.

**What remains genuinely unknown:** Whether markets structurally underprice earthquake frequency due to recency bias — independent of LLM training contamination. This requires prospective collection of seismic markets resolving in 2026+.

### Hypothesis tracker

The system includes a structured experimentation framework (`backtest hypothesis`) for tracking alpha hypotheses through a lifecycle: `proposed → testing → confirmed/rejected`. Confidence decays with a 90-day half-life, triggering retests. Four seed hypotheses are pre-loaded.

---

## Tests

```bash
uv run pytest tests/                          # All 254 tests
uv run pytest tests/test_backtest.py -v       # Backtest DB, simulator, hypothesis tracker
uv run pytest tests/test_integration.py -v   # CLI, market pipeline, trading logic
```

All tests use `tmp_path` fixtures; no external services required (API calls are mocked).

---

## Linting

```bash
uv run ruff check src/
uv run ruff check --fix src/
```

---

## Disclaimer

This is an experimental research project. It does not constitute financial advice. Paper trading mode is the default and recommended for experimentation. Live trading requires explicit configuration and carries real financial risk.
