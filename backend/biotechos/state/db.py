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
    conn.execute("PRAGMA busy_timeout = 3000")  # avoid hard-fail under brief write contention
    return conn


# Columns added after the initial schema — applied to existing DBs on connect
# (CREATE TABLE IF NOT EXISTS won't add columns to an existing table).
_MIGRATIONS = [
    ("molecules", "favorite", "INTEGER DEFAULT 0"),
    ("custom_metrics", "formula", "TEXT"),
    ("assays", "cell_line", "TEXT"),
    ("fold_settings", "target_kind", "TEXT"),   # 'pdb' | 'uniprot' | 'sequence'
    ("fold_settings", "target_value", "TEXT"),  # the id or raw sequence
    ("molecules", "boltz_json", "TEXT"),        # Boltz predicted props (SAB + ADME)
    ("vendors", "capabilities", "TEXT"),         # JSON: services/cell-lines/proteins offered
    ("vendors", "contacts", "TEXT"),             # JSON list of {name,email,role}
    ("vendors", "pricing_bands", "TEXT"),        # JSON: service -> price band
    ("vendors", "domain", "TEXT"),               # email domain, for credential matching
    # Inbox v2 (Phase 2): link inbox items to their source document + extraction
    ("inbox_items", "document_id", "INTEGER"),   # source documents.id
    ("inbox_items", "doc_type", "TEXT"),         # extract doc_type
    ("inbox_items", "analysis", "TEXT"),         # JSON: extract analysis/recommendation
    ("inbox_items", "extraction_json", "TEXT"),  # JSON: typed extraction result
    # Inbox v3 (mailbox): precomputed LLM triage stored per email
    ("documents", "triage_json", "TEXT"),        # JSON: {category,next_step,reason,needs_reply,confidence}
    ("documents", "seen", "INTEGER DEFAULT 0"),  # read/unread in the mailbox UI
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
