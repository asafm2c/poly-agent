## MODIFIED Requirements

### Requirement: Analysis functions callable from any context
All analysis functions SHALL work when called from Python scripts, CLI commands, Jupyter notebooks, or by LLM agents via bash tool calls. Functions SHALL accept standard Python arguments and return structured dictionaries or lists, not print to stdout. `run_simulation()` and `run_multi_model_evaluation()` SHALL internally use async concurrency but their public signatures SHALL remain synchronous — callers do not need to manage an event loop.

#### Scenario: LLM agent runs ad-hoc analysis
- **WHEN** an LLM agent executes `python3 -c "from polymarket_agent.backtest.analysis import *; print(category_calibration(load_markets(regime='o1-era')))"`
- **THEN** the analysis runs and returns structured results to stdout

#### Scenario: Human uses in notebook
- **WHEN** a human imports analysis functions in a Jupyter notebook
- **THEN** the functions return data structures suitable for further manipulation, plotting, or tabulation

#### Scenario: run_simulation called synchronously
- **WHEN** `run_simulation(markets, model="claude-sonnet-4-6")` is called from a synchronous context
- **THEN** the function blocks until all trials complete and returns the run_id, with no asyncio boilerplate required from the caller
