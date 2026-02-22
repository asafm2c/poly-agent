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
    event_id TEXT,
    market_type TEXT,
    domain_type TEXT
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
    duration_ms INTEGER DEFAULT 0,
    model TEXT,
    training_recency_score REAL,
    base_rate_estimate REAL,
    pass2_estimate REAL,
    pass2_blind_estimate REAL
);

CREATE TABLE IF NOT EXISTS bt_hypotheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'testing', 'confirmed', 'rejected', 'invalidated')),
    confidence_score REAL DEFAULT 0.0,
    category_filter TEXT,
    volume_min REAL,
    volume_max REAL,
    model_filter TEXT,
    temporal_filter TEXT,
    proposed_at TEXT NOT NULL,
    first_tested_at TEXT,
    confirmed_at TEXT,
    last_evaluated_at TEXT,
    invalidated_at TEXT,
    decay_half_life_days INTEGER DEFAULT 90,
    retest_threshold REAL DEFAULT 0.50,
    proposed_by TEXT DEFAULT 'user',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS bt_hypothesis_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis_id INTEGER NOT NULL REFERENCES bt_hypotheses(id),
    run_id INTEGER NOT NULL REFERENCES bt_simulation_runs(id),
    recorded_at TEXT NOT NULL,
    trial_count INTEGER NOT NULL,
    agent_brier REAL,
    market_brier REAL,
    brier_diff REAL,
    simulated_pnl REAL,
    p_value REAL,
    effect_size REAL,
    supports_hypothesis INTEGER,
    evaluation_notes TEXT
);

CREATE TABLE IF NOT EXISTS bt_hypothesis_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis_id INTEGER NOT NULL REFERENCES bt_hypotheses(id),
    action_type TEXT NOT NULL
        CHECK (action_type IN (
            'edge_override', 'category_target', 'category_avoid',
            'model_preference', 'weight_adjustment'
        )),
    config TEXT NOT NULL,
    base_strength REAL NOT NULL DEFAULT 1.0,
    active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    deactivated_at TEXT
);

CREATE TABLE IF NOT EXISTS bt_import_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL CHECK (job_type IN ('full', 'histories', 'histories_filtered')),
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'done', 'failed', 'stalled', 'cancelled')),
    params_json TEXT,
    pid INTEGER,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    markets_total INTEGER,
    markets_done INTEGER DEFAULT 0,
    histories_total INTEGER,
    histories_done INTEGER DEFAULT 0,
    histories_skipped INTEGER DEFAULT 0,
    error_msg TEXT
);

CREATE INDEX IF NOT EXISTS idx_bt_markets_category ON bt_markets(category);
CREATE INDEX IF NOT EXISTS idx_bt_markets_end_date ON bt_markets(end_date);
CREATE INDEX IF NOT EXISTS idx_bt_markets_volume ON bt_markets(volume);
CREATE INDEX IF NOT EXISTS idx_bt_markets_market_type ON bt_markets(market_type);
CREATE INDEX IF NOT EXISTS idx_bt_markets_domain_type ON bt_markets(domain_type);
CREATE INDEX IF NOT EXISTS idx_bt_price_history_market ON bt_price_history(market_id);
CREATE INDEX IF NOT EXISTS idx_bt_sim_trials_run ON bt_simulation_trials(run_id);
CREATE INDEX IF NOT EXISTS idx_bt_sim_trials_market ON bt_simulation_trials(market_id);
CREATE INDEX IF NOT EXISTS idx_bt_sim_trials_model ON bt_simulation_trials(model);
CREATE INDEX IF NOT EXISTS idx_bt_hypotheses_status ON bt_hypotheses(status);
CREATE INDEX IF NOT EXISTS idx_bt_hyp_evidence_hyp ON bt_hypothesis_evidence(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_bt_hyp_evidence_run ON bt_hypothesis_evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_bt_hyp_actions_hyp ON bt_hypothesis_actions(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_bt_hyp_actions_active ON bt_hypothesis_actions(active);
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
        # Migrate first so columns exist before index creation
        _migrate_simulation_trials(conn)
        _migrate_markets(conn)
        conn.commit()
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        _seed_regimes(conn)
        conn.commit()
    finally:
        conn.close()

    # Seed hypotheses (uses its own connection)
    try:
        from polymarket_agent.backtest.hypothesis import seed_hypotheses
        seed_hypotheses(db_path)
    except Exception:
        pass  # hypothesis module may not exist yet


def _migrate_simulation_trials(conn: sqlite3.Connection) -> None:
    """Add model and training_recency_score columns if not present."""
    # Check if table exists (may not on fresh DB — schema creation handles it)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "bt_simulation_trials" not in tables:
        return  # Fresh DB — schema creation will include the columns

    existing = {row[1] for row in conn.execute("PRAGMA table_info(bt_simulation_trials)")}
    if "model" not in existing:
        conn.execute("ALTER TABLE bt_simulation_trials ADD COLUMN model TEXT")
    if "training_recency_score" not in existing:
        conn.execute(
            "ALTER TABLE bt_simulation_trials ADD COLUMN training_recency_score REAL"
        )
    if "base_rate_estimate" not in existing:
        conn.execute("ALTER TABLE bt_simulation_trials ADD COLUMN base_rate_estimate REAL")
    if "pass2_estimate" not in existing:
        conn.execute("ALTER TABLE bt_simulation_trials ADD COLUMN pass2_estimate REAL")
    if "pass2_blind_estimate" not in existing:
        conn.execute("ALTER TABLE bt_simulation_trials ADD COLUMN pass2_blind_estimate REAL")


def _migrate_markets(conn: sqlite3.Connection) -> None:
    """Add market_type and domain_type columns to bt_markets if not present."""
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "bt_markets" not in tables:
        return  # Fresh DB — schema creation will include the columns

    existing = {row[1] for row in conn.execute("PRAGMA table_info(bt_markets)")}
    if "market_type" not in existing:
        conn.execute("ALTER TABLE bt_markets ADD COLUMN market_type TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bt_markets_market_type ON bt_markets(market_type)"
    )
    if "domain_type" not in existing:
        conn.execute("ALTER TABLE bt_markets ADD COLUMN domain_type TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bt_markets_domain_type ON bt_markets(domain_type)"
    )


def _seed_regimes(conn: sqlite3.Connection) -> None:
    """Seed bt_regimes with model release boundaries."""
    for name, start_date, end_date in REGIMES:
        conn.execute(
            """INSERT OR REPLACE INTO bt_regimes (name, start_date, end_date)
            VALUES (?, ?, ?)""",
            (name, start_date, end_date),
        )
