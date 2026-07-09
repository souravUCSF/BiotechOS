"""Suspected-decisions confirmation queue.

Every decision-shaped claim ingested from comms lands in `decisions` as `suspected`
(see `corpus.store._suspect_decision`). Human confirmation — not a keyword heuristic
— is the gate that promotes it into the `facts` world model and the Decision Log
(`ledger_entries`). This module is the read/confirm/dismiss surface over that queue.

An optional LLM pass (`extract_decisions`) can propose decisions the deterministic
regex extractor misses; it is NOT wired into ingest by default (per-email cost) —
callers opt in.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..config import DEMO_PROGRAM_ID, MODEL_ARTIFACTS
from ..state import db
from . import llm
from .corpus import store as corpus_store


def queue(program_id: str = DEMO_PROGRAM_ID, status: str = "suspected",
          limit: int = 200) -> list[dict]:
    """The confirmation queue, highest-confidence first, each with its source citation."""
    from .corpus.qa import _cite
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE program_id=? AND status=? "
            "ORDER BY confidence DESC, created_at DESC LIMIT ?",
            (program_id, status, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["source"] = _cite(conn, r["source_document_id"]) if r["source_document_id"] else None
            out.append(d)
        return out
    finally:
        conn.close()


def confirm(decision_id: int, program_id: str = DEMO_PROGRAM_ID,
            decided_by: str = "founder") -> dict:
    """Confirm a suspected decision: promote it into `facts`, log it to the Decision
    Log, and supersede any prior confirmed decision for the same subject/predicate."""
    conn = db.connect()
    try:
        d = conn.execute("SELECT * FROM decisions WHERE id=? AND program_id=?",
                         (decision_id, program_id)).fetchone()
        if d is None:
            raise ValueError("decision not found")
        d = dict(d)
        if d["status"] != "suspected":
            return {"decision_id": decision_id, "status": d["status"], "noop": True}
        o = {"subject_type": d["subject_type"], "subject_key": d["subject_key"],
             "predicate": d["predicate"], "value": d["value"]}
        with conn:
            # single-valued: a newly confirmed decision supersedes the prior one
            conn.execute(
                "UPDATE decisions SET status='superseded' WHERE program_id=? AND subject_key=? "
                "AND predicate=? AND status='confirmed' AND id<>?",
                (program_id, d["subject_key"], d["predicate"], decision_id))
            corpus_store._promote(conn, program_id, d["observation_id"], o)  # valid_from = now
            title = f"{d['kind']}: {d['subject_key']} — {d['predicate']} = {d['value']}"
            led = conn.execute(
                "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by) "
                "VALUES (?,?,?,?,?)",
                (program_id, "decision", title, d.get("rationale") or "", decided_by)).lastrowid
            conn.execute(
                "UPDATE decisions SET status='confirmed', decided_by=?, "
                "decided_at=datetime('now'), ledger_entry_id=? WHERE id=?",
                (decided_by, led, decision_id))
        return {"decision_id": decision_id, "status": "confirmed", "ledger_entry_id": led,
                "fact": o}
    finally:
        conn.close()


def dismiss(decision_id: int, program_id: str = DEMO_PROGRAM_ID,
            decided_by: str = "founder") -> dict:
    conn = db.connect()
    try:
        with conn:
            n = conn.execute(
                "UPDATE decisions SET status='dismissed', decided_by=?, decided_at=datetime('now') "
                "WHERE id=? AND program_id=? AND status='suspected'",
                (decided_by, decision_id, program_id)).rowcount
        if not n:
            raise ValueError("decision not found or not in 'suspected' state")
        return {"decision_id": decision_id, "status": "dismissed"}
    finally:
        conn.close()


# --- optional LLM decision extractor (opt-in; not wired into ingest by default) ---
class _Candidate(BaseModel):
    kind: str = "other"
    subject_type: str = "vendor"
    subject_key: str
    predicate: str
    value: str | None = None
    rationale: str = ""
    confidence: float = 0.6


class _Candidates(BaseModel):
    decisions: list[_Candidate] = []


_SYS = (
    "You read one biotech-CRO email and extract DECISIONS the sender/recipient are making or "
    "committing to — vendor selections, agreed prices, timeline commitments, scope/plan changes, "
    "go/no-go calls, contract terms. Do NOT extract mere capabilities or FYI facts. For each, give "
    "kind (price_agreement|vendor_selection|scope_change|timeline_commitment|go_no_go|contract_term|"
    "other), a subject (the vendor/program the decision is about), a predicate + value describing the "
    "change, a one-line rationale (quote the trigger), and confidence 0-1. Return JSON {decisions:[...]}; "
    "empty list if none.")


def extract_decisions(email, api_key: str | None = None) -> list[dict]:
    """Propose decision candidates from one email's latest message (LLM; [] without a key)."""
    from .triage import latest_message
    body = latest_message(getattr(email, "body", "") or email.full_text)
    user = f"From: {email.email_from}\nSubject: {email.subject}\n\n{body[:3000]}"
    res, _ = llm.structured(model=MODEL_ARTIFACTS, system=_SYS, user=user,
                            schema=_Candidates, fallback=_Candidates(), api_key=api_key,
                            max_tokens=600)
    return [c.model_dump() for c in res.decisions if c.subject_key and c.predicate]


def insert_suspected(conn, program_id: str, cand: dict, doc_id: int,
                     event_at: str | None = None) -> bool:
    """Insert one LLM-proposed decision as suspected (dedup on subject/pred/value/doc).
    Returns True if inserted. observation_id is NULL — these come from free text, not
    a deterministic observation row."""
    sk, pred, val = cand["subject_key"], cand["predicate"], cand.get("value")
    dup = conn.execute(
        "SELECT 1 FROM decisions WHERE program_id=? AND subject_key=? AND predicate=? "
        "AND IFNULL(value,'')=IFNULL(?,'') AND source_document_id=?",
        (program_id, sk, pred, val, doc_id)).fetchone()
    if dup:
        return False
    conn.execute(
        "INSERT INTO decisions(program_id,kind,subject_type,subject_key,predicate,value,"
        "source_document_id,observation_id,status,confidence,rationale,created_at) "
        "VALUES (?,?,?,?,?,?,?,NULL,'suspected',?,?, COALESCE(?, datetime('now')))",
        (program_id, cand.get("kind", "other"), cand.get("subject_type", "vendor"), sk, pred,
         val, doc_id, cand.get("confidence", 0.6), cand.get("rationale", ""), event_at))
    return True


def backfill_decisions(program_id: str = DEMO_PROGRAM_ID, limit: int | None = None,
                       only_inbound: bool = False, api_key: str | None = None) -> dict:
    """Run the LLM decision extractor over ALREADY-INGESTED documents (no re-ingest, so
    the mailbox/graph are untouched). Skips noise. Most-recent first."""
    from .triage import _doc_email
    conn = db.connect()
    where = "program_id=? AND IFNULL(triage,'')<>'noise'"
    args: list = [program_id]
    if only_inbound:
        where += " AND direction='inbound'"
    sql = f"SELECT * FROM documents WHERE {where} ORDER BY sent_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, args).fetchall()
    n, added, by_kind = 0, 0, {}
    with conn:
        for r in rows:
            for c in extract_decisions(_doc_email(r), api_key=api_key):
                if insert_suspected(conn, program_id, c, r["id"], r["sent_at"]):
                    added += 1
                    by_kind[c.get("kind", "other")] = by_kind.get(c.get("kind", "other"), 0) + 1
            n += 1
    conn.close()
    return {"documents_scanned": n, "decisions_added": added, "by_kind": by_kind}
