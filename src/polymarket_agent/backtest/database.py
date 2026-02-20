"""Backtest database: schema, initialization, and connection management."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from polymarket_agent.config import settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bt_markets (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    description TEXT,
    category TEXT,
    end_date TEXT,
    volume REAL DEFAULT 0,
    liquidity REAL DEFAULT 0,
    resolution_outcome TEXT,
    yes_token TEXT,
    no_token TEXT,
    has_history INTEGER DEFAULT 0,
    collected_at TEXT NOT NULL,
    event_id TEXT
);

CREATE TABLE IF NOT EXISTS bt_price_history (
    market_id TEXT NOT NULL REFERENCES bt_markets(id),
    timestamp INTEGER NOT NULL,
    price REAL NOT NULL,
    PRIMARY KEY (market_id, timestamp)
);

CREATE TABLE IF NOT EXISTS bt_regimes (
    name TEXT PRIMARY KEY,
    start_date TEXT NOT NULL,
    end_date TEXT
);

CREATE TABLE IF NOT EXISTS bt_simulation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    config TEXT,
    market_count INTEGER DEFAULT 0,
    agent_brier REAL,
    market_brier REAL,
    simulated_pnl REAL,
    total_cost REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bt_simulation_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES bt_simulation_runs(id),
    market_id TEXT NOT NULL REFERENCES bt_markets(id),
    horizon_days INTEGER NOT NULL,
    market_price_at_horizon REAL,
    agent_estimate REAL,
    confidence_low REAL,
    confidence_high REAL,
    outcome REAL,
    agent_brier REAL,
    market_brier REAL,
    edge REAL,
    simulated_trade TEXT,
    reasoning TEXT,
    llm_cost REAL DEFAULT 0,
    duration_ms INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_bt_markets_category ON bt_markets(category);
CREATE INDEX IF NOT EXISTS idx_bt_markets_end_date ON bt_markets(end_date);
CREATE INDEX IF NOT EXISTS idx_bt_markets_volume ON bt_markets(volume);
CREATE INDEX IF NOT EXISTS idx_bt_price_history_market ON bt_price_history(market_id);
CREATE INDEX IF NOT EXISTS idx_bt_sim_trials_run ON bt_simulation_trials(run_id);
CREATE INDEX IF NOT EXISTS idx_bt_sim_trials_market ON bt_simulation_trials(market_id);
"""

REGIMES = [
    ("pre-GPT4", "2020-01-01", "2023-03-14"),
    ("GPT4-era", "2023-03-14", "2024-03-04"),
    ("Claude3-era", "2024-03-04", "2024-05-13"),
    ("GPT4o-era", "2024-05-13", "2024-09-12"),
    ("o1-era", "2024-09-12", "2025-06-25"),
    ("post-Claude4", "2025-06-25", None),
]


def get_backtest_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a connection to the backtest database."""
    path = db_path or settings.backtest_db_path
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def get_backtest_db(db_path: Path | None = None):
    """Context manager for backtest database connections."""
    conn = get_backtest_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_backtest_db(db_path: Path | None = None) -> None:
    """Initialize the backtest database schema and seed regimes."""
    conn = get_backtest_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        _seed_regimes(conn)
        conn.commit()
    finally:
        conn.close()


def _seed_regimes(conn: sqlite3.Connection) -> None:
    """Seed bt_regimes with model release boundaries."""
    for name, start_date, end_date in REGIMES:
        conn.execute(
            """INSERT OR REPLACE INTO bt_regimes (name, start_date, end_date)
            VALUES (?, ?, ?)""",
            (name, start_date, end_date),
        )
