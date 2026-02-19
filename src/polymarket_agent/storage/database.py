import sqlite3
from contextlib import contextmanager
from pathlib import Path

from polymarket_agent.config import settings

SCHEMA_VERSION = 2

MIGRATIONS = [
    # Version 1: Initial schema
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS markets (
        id TEXT PRIMARY KEY,
        condition_id TEXT,
        question TEXT NOT NULL,
        description TEXT,
        category TEXT,
        end_date TEXT,
        outcome_yes_token TEXT,
        outcome_no_token TEXT,
        volume REAL DEFAULT 0,
        liquidity REAL DEFAULT 0,
        last_price_yes REAL,
        last_price_no REAL,
        active INTEGER DEFAULT 1,
        resolved INTEGER DEFAULT 0,
        resolution_outcome TEXT,
        first_seen_at TEXT,
        last_updated_at TEXT,
        event_id TEXT,
        event_title TEXT
    );

    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        market_id TEXT NOT NULL REFERENCES markets(id),
        side TEXT NOT NULL CHECK(side IN ('YES', 'NO')),
        size REAL NOT NULL,
        entry_price REAL NOT NULL,
        entry_timestamp TEXT NOT NULL,
        exit_price REAL,
        exit_timestamp TEXT,
        realized_pnl REAL,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed')),
        mode TEXT NOT NULL DEFAULT 'paper' CHECK(mode IN ('paper', 'live')),
        order_id TEXT
    );

    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        market_id TEXT NOT NULL REFERENCES markets(id),
        position_id INTEGER REFERENCES positions(id),
        side TEXT NOT NULL CHECK(side IN ('YES', 'NO')),
        action TEXT NOT NULL CHECK(action IN ('buy', 'sell')),
        size REAL NOT NULL,
        price REAL NOT NULL,
        timestamp TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'paper' CHECK(mode IN ('paper', 'live')),
        order_id TEXT,
        status TEXT NOT NULL DEFAULT 'filled' CHECK(status IN ('pending', 'filled', 'cancelled', 'failed'))
    );

    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        market_id TEXT NOT NULL REFERENCES markets(id),
        timestamp TEXT NOT NULL,
        market_price REAL NOT NULL,
        agent_estimate REAL NOT NULL,
        confidence_low REAL,
        confidence_high REAL,
        base_rate REAL,
        updated_estimate REAL,
        final_estimate REAL,
        reasoning TEXT,
        thesis TEXT,
        category TEXT,
        outcome REAL,
        prediction_error REAL,
        resolved_at TEXT
    );

    CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        cash_balance REAL NOT NULL,
        mode TEXT NOT NULL DEFAULT 'paper' CHECK(mode IN ('paper', 'live')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        market_id TEXT NOT NULL REFERENCES markets(id),
        side TEXT NOT NULL CHECK(side IN ('YES', 'NO')),
        action TEXT NOT NULL CHECK(action IN ('buy', 'sell')),
        price REAL NOT NULL,
        size REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'partial', 'filled', 'cancelled', 'expired', 'failed')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        filled_size REAL DEFAULT 0,
        filled_price REAL
    );

    CREATE TABLE IF NOT EXISTS daily_pnl (
        date TEXT PRIMARY KEY,
        realized_pnl REAL DEFAULT 0,
        unrealized_pnl REAL DEFAULT 0,
        total_pnl REAL DEFAULT 0,
        portfolio_value REAL DEFAULT 0,
        trade_count INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS kill_switch (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        active INTEGER NOT NULL DEFAULT 0,
        activated_at TEXT,
        reason TEXT
    );

    INSERT OR IGNORE INTO kill_switch (id, active) VALUES (1, 0);

    CREATE INDEX IF NOT EXISTS idx_positions_market ON positions(market_id);
    CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
    CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id);
    CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
    CREATE INDEX IF NOT EXISTS idx_predictions_market ON predictions(market_id);
    CREATE INDEX IF NOT EXISTS idx_predictions_resolved ON predictions(resolved_at);
    CREATE INDEX IF NOT EXISTS idx_markets_active ON markets(active);
    CREATE INDEX IF NOT EXISTS idx_markets_category ON markets(category);
    """,
    # Version 2: Price snapshots and adaptive feedback loop
    """
    CREATE TABLE IF NOT EXISTS price_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        market_id TEXT NOT NULL REFERENCES markets(id),
        timestamp TEXT NOT NULL,
        price_yes REAL,
        price_no REAL,
        volume REAL
    );

    CREATE INDEX IF NOT EXISTS idx_snapshots_market_time
        ON price_snapshots(market_id, timestamp);
    """,
]


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def get_db(db_path: Path | None = None):
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row["version"] if row else 0
    except sqlite3.OperationalError:
        return 0


def migrate(db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    try:
        current_version = _get_schema_version(conn)
        for i in range(current_version, len(MIGRATIONS)):
            conn.executescript(MIGRATIONS[i])
            if current_version == 0:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (i + 1,))
            else:
                conn.execute("UPDATE schema_version SET version = ?", (i + 1,))
            conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    migrate(db_path)
