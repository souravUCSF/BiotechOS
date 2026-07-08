"""Ingestion pipeline + bitemporal world model.

ingest(): mailbox source → per email: extract → write `documents` (+ FTS) →
write `observations` → promote agreed observations to `facts`. Also stages an
`inbox_item` for actionable items (consumed by the Current Inbox in Phase 2).
"""
from __future__ import annotations

import json

from ...config import DEMO_PROGRAM_ID
from ...ingest.mailbox import get_source
from ...state import db
from .. import extract as X

# predicates that hold multiple simultaneous values (a vendor tests many lines)
MULTI_VALUED = {"tests_cell_line", "offers_service"}


def _promote(conn, program_id: str, obs_id: int, o: dict) -> None:
    """Promote an 'agreed' observation into the current-facts world model."""
    st, sk, pred, val = o["subject_type"], o["subject_key"], o["predicate"], o["value"]
    if pred in MULTI_VALUED:
        exists = conn.execute(
            "SELECT 1 FROM facts WHERE program_id=? AND subject_type=? AND subject_key=? "
            "AND predicate=? AND value=? AND status='current'",
            (program_id, st, sk, pred, val)).fetchone()
        if exists:
            return
    else:
        # single-valued: supersede any current fact with a different value
        conn.execute(
            "UPDATE facts SET status='superseded', valid_to=datetime('now') "
            "WHERE program_id=? AND subject_type=? AND subject_key=? AND predicate=? "
            "AND status='current' AND value<>?", (program_id, st, sk, pred, val))
        if conn.execute(
                "SELECT 1 FROM facts WHERE program_id=? AND subject_type=? AND subject_key=? "
                "AND predicate=? AND value=? AND status='current'",
                (program_id, st, sk, pred, val)).fetchone():
            return
    conn.execute(
        "INSERT INTO facts(program_id,subject_type,subject_key,predicate,value,observation_id,status) "
        "VALUES (?,?,?,?,?,?, 'current')", (program_id, st, sk, pred, val, obs_id))


def reset(program_id: str = DEMO_PROGRAM_ID, conn=None) -> None:
    own = conn is None
    conn = conn or db.connect()
    with conn:
        # children before parents (facts→observations→documents)
        for t in ("facts", "observations", "documents"):
            conn.execute(f"DELETE FROM {t} WHERE program_id=?", (program_id,))
        conn.execute("DELETE FROM documents_fts")  # content-external; rebuilt on ingest
    if own:
        conn.close()


def ingest(program_id: str = DEMO_PROGRAM_ID, source: str | None = None,
           limit: int | None = None, do_reset: bool = True) -> dict:
    conn = db.connect()
    if do_reset:
        reset(program_id, conn=conn)
    src = get_source(source)
    counts = {"documents": 0, "observations": 0, "facts": 0, "by_type": {}}
    n = 0
    with conn:
        for em in src.emails():
            if limit and n >= limit:
                break
            res = X.extract(program_id, em, conn=conn)
            dt = res["doc_type"]
            counts["by_type"][dt] = counts["by_type"].get(dt, 0) + 1
            cur = conn.execute(
                "INSERT INTO documents(program_id,source_ref,org,direction,email_from,email_to,"
                "subject,sent_at,doc_type,triage,raw_text,extraction_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (program_id, em.source_ref, "corpus", em.direction, em.email_from,
                 em.email_to, em.subject, em.date, dt, res["triage"],
                 em.full_text, json.dumps(res.get("extraction", {}))))
            doc_id = cur.lastrowid
            conn.execute("INSERT INTO documents_fts(rowid,subject,raw_text) VALUES (?,?,?)",
                         (doc_id, em.subject or "", em.full_text))
            counts["documents"] += 1
            for o in res.get("observations", []):
                oc = conn.execute(
                    "INSERT INTO observations(program_id,subject_type,subject_key,predicate,"
                    "value,source_document_id,decision_state,confidence) VALUES (?,?,?,?,?,?,?,?)",
                    (program_id, o["subject_type"], o["subject_key"], o["predicate"],
                     o["value"], doc_id, o.get("decision_state", "proposed"),
                     o.get("confidence", 0.7)))
                counts["observations"] += 1
                if o.get("decision_state") == "agreed":
                    _promote(conn, program_id, oc.lastrowid, o)
            n += 1
        counts["facts"] = conn.execute(
            "SELECT COUNT(*) c FROM facts WHERE program_id=? AND status='current'",
            (program_id,)).fetchone()["c"]
    conn.close()
    return counts
