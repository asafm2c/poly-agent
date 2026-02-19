"""Read-only async SQLite access for the dashboard.

Opens the database with mode=ro URI parameter so it is physically
impossible for the dashboard to modify agent data. WAL mode (set by
the agent) enables concurrent reads while the agent writes.
"""

from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


class _Connection:
    """Thin wrapper adding execute_fetchone / execute_fetchall helpers."""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def execute_fetchone(self, sql: str, params=None):
        cursor = await self._conn.execute(sql, params or [])
        return await cursor.fetchone()

    async def execute_fetchall(self, sql: str, params=None):
        cursor = await self._conn.execute(sql, params or [])
        return await cursor.fetchall()

    async def execute(self, sql: str, params=None):
        return await self._conn.execute(sql, params or [])

    async def table_exists(self, name: str) -> bool:
        row = await self.execute_fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return row is not None


class DashboardDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

    @asynccontextmanager
    async def connection(self):
        db = await aiosqlite.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
        )
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA query_only=ON")
        await db.execute("PRAGMA busy_timeout=5000")
        try:
            yield _Connection(db)
        finally:
            await db.close()
