"""SQLite connection + schema init helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import DB_PATH

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added after the initial schema — applied to existing DBs on connect
# (CREATE TABLE IF NOT EXISTS won't add columns to an existing table).
_MIGRATIONS = [
    ("molecules", "favorite", "INTEGER DEFAULT 0"),
]


def _apply_migrations(conn: sqlite3.Connection) -> None:
    for table, col, decl in _MIGRATIONS:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass


def init_db(db_path: Path | str = DB_PATH, *, reset: bool = False) -> None:
    db_path = Path(db_path)
    if reset and db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    with conn:
        conn.executescript(SCHEMA_PATH.read_text())
        _apply_migrations(conn)
    conn.close()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]
