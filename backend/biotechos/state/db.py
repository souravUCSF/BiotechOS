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


def init_db(db_path: Path | str = DB_PATH, *, reset: bool = False) -> None:
    db_path = Path(db_path)
    if reset and db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    with conn:
        conn.executescript(SCHEMA_PATH.read_text())
    conn.close()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]
