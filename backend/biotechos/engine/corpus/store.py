"""Ingestion pipeline + bitemporal world model.

ingest(): mailbox source → per email: extract → write `documents` (+ FTS) →
write `observations` → promote agreed observations to `facts`. Also stages an
`inbox_item` for actionable items (consumed by the Current Inbox in Phase 2).
"""
from __future__ import annotations

import json

from ...config import DEMO_PROGRAM_ID, org_for_program
from ...ingest.mailbox import get_source
from ...state import db
from .. import extract as X

# predicates that hold multiple simultaneous values (a vendor tests many lines)
MULTI_VALUED = {"tests_cell_line", "offers_service"}

# Inbox v2: which extract recommendations warrant a human decision in the inbox.
# review_quote / review_data / draft_reply always need a human; contract / invoice
# / logistics carry a decision even though extract emits 'acknowledge' for them.
_INBOX_RECOMMENDATIONS = {"review_quote", "review_data", "draft_reply"}
_INBOX_DOC_TYPES = {"contract", "invoice", "logistics"}

# recommendation -> proposed_action.action consumed by engine.inbox.approve()
_ACTION_FOR = {
    "review_quote": "review_quote",
    "review_data": "review_data",
    "draft_reply": "draft_reply",
    "invoice": "review_invoice",
    "contract": "review_contract",
    "logistics": "review_logistics",
}
_LABEL_FOR = {
    "review_quote": "Review quote → issue PO",
    "review_data": "Review data → load to DB",
    "draft_reply": "Review draft reply",
    "review_invoice": "Reconcile invoice",
    "review_contract": "Review agreement",
    "review_logistics": "Confirm logistics",
}


def _stage_inbox_item(conn, program_id: str, doc_id: int, em, res: dict) -> None:
    """Create an inbox_items row for an actionable doc that needs a human.
    Skips noise/fyi and pure-acknowledge items (unless a decision doc_type)."""
    dt = res["doc_type"]
    analysis = res.get("analysis", {}) or {}
    rec = analysis.get("recommendation")
    if res.get("triage") in ("noise", "fyi"):
        return
    if rec not in _INBOX_RECOMMENDATIONS and dt not in _INBOX_DOC_TYPES:
        return  # pure acknowledge with no decision doc_type

    action_key = rec if rec in _INBOX_RECOMMENDATIONS else dt
    action = _ACTION_FOR.get(action_key, "acknowledge")
    extraction = res.get("extraction", {}) or {}
    vendor = res.get("vendor")

    subject = em.subject or "(no subject)"
    title = subject
    summary = analysis.get("note") or f"{dt.replace('_', ' ')} from {vendor or em.email_from}"
    proposed = {"action": action, "label": _LABEL_FOR.get(action, "Review"),
                "note": analysis.get("note", "")}
    payload = {
        "document_id": doc_id, "doc_type": dt, "vendor": vendor,
        "email_from": em.email_from, "email_to": em.email_to,
        "subject": subject, "date": em.date, "direction": em.direction,
        "body_preview": (em.body or "")[:600],
        "attachments": [
            {"filename": a.filename, "protected": bool(a.protected),
             "mimetype": a.mimetype} for a in (em.attachments or [])
        ],
        "extraction": extraction, "analysis": analysis,
    }
    conn.execute(
        "INSERT INTO inbox_items(program_id,kind,title,summary,payload,proposed_action,"
        "document_id,doc_type,analysis,extraction_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (program_id, dt, title, summary, json.dumps(payload), json.dumps(proposed),
         doc_id, dt, json.dumps(analysis), json.dumps(extraction)),
    )


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
        # document-linked inbox items are regenerated on ingest; drop them first
        conn.execute("DELETE FROM inbox_items WHERE program_id=? AND document_id IS NOT NULL",
                     (program_id,))
        # Drop this program's FTS rows BEFORE deleting the documents (need the ids).
        # MUST be program-scoped — a blanket DELETE wiped OTHER programs' index
        # entries (their rowids survived but pointed at empty content), silently
        # breaking their document search.
        conn.execute(
            "INSERT INTO documents_fts(documents_fts, rowid, subject, raw_text) "
            "SELECT 'delete', id, subject, raw_text FROM documents WHERE program_id=?",
            (program_id,))
        for t in ("facts", "observations", "documents"):
            conn.execute(f"DELETE FROM {t} WHERE program_id=?", (program_id,))
    if own:
        conn.close()


def ingest(program_id: str = DEMO_PROGRAM_ID, source: str | None = None,
           limit: int | None = None, do_reset: bool = True) -> dict:
    conn = db.connect()
    if do_reset:
        reset(program_id, conn=conn)
    src = get_source(source, org=org_for_program(program_id))
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
            _stage_inbox_item(conn, program_id, doc_id, em, res)
            n += 1
        counts["facts"] = conn.execute(
            "SELECT COUNT(*) c FROM facts WHERE program_id=? AND status='current'",
            (program_id,)).fetchone()["c"]
    conn.close()
    return counts
