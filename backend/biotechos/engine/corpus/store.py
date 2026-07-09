"""Ingestion pipeline + bitemporal world model.

ingest(): mailbox source → per email: extract → write `documents` (+ FTS) →
write `observations` → promote agreed observations to `facts`. Also stages an
`inbox_item` for actionable items (consumed by the Current Inbox in Phase 2).
"""
from __future__ import annotations

import json
import re

from ...config import DEMO_PROGRAM_ID, org_for_program
from ...ingest.mailbox import get_source
from ...state import db
from .. import extract as X
from .. import graph

# predicates that hold multiple simultaneous values (a vendor tests many lines)
MULTI_VALUED = {"tests_cell_line", "offers_service"}

# Capability predicates are facts-about-the-world (a vendor CAN test a line), not
# decisions — they keep auto-promoting to `facts`. Every other observation is a
# decision-shaped claim and is routed to the suspected-decisions queue instead.
CAPABILITY_PREDICATES = {"tests_cell_line", "offers_service"}

# decision-bearing predicate → decision `kind` (fallback 'other').
_DECISION_KIND = {
    "quoted_amount": "price_agreement",
    "agreed_price": "price_agreement",
    "selected_vendor": "vendor_selection",
    "timeline": "timeline_commitment",
    "delivery_date": "timeline_commitment",
    "go_no_go": "go_no_go",
    "contract_term": "contract_term",
}

# observation predicate → (edge predicate, destination entity_type). Turns a
# vendor's flat claims into typed edges in the graph.
_OBS_EDGE = {
    "tests_cell_line": ("tests", "cell_line"),
    "offers_service": ("offers_service", "assay"),
    "quoted_amount": ("quoted", "program"),  # dst is the program itself
}

_ADDR_RE = re.compile(r"^\s*(?:\"?([^\"<]*?)\"?\s*)?<?([\w.+\-]+@[\w.\-]+)>?\s*$")


def _parse_addr(addr: str) -> tuple[str, str] | None:
    """('Jane Doe', 'jane@x.com') from a From/To header value; name may be ''."""
    m = _ADDR_RE.match(addr or "")
    if not m:
        return None
    email = m.group(2)
    return (m.group(1).strip() or email, email)

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


def _promote(conn, program_id: str, obs_id: int, o: dict, event_at: str | None = None) -> None:
    """Promote an observation into the current-facts world model. `event_at` (the
    source email's sent_at) is the fact's valid_from / the prior fact's valid_to,
    so the world model accrues in true chronological order."""
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
            "UPDATE facts SET status='superseded', valid_to=COALESCE(?, datetime('now')) "
            "WHERE program_id=? AND subject_type=? AND subject_key=? AND predicate=? "
            "AND status='current' AND value<>?", (event_at, program_id, st, sk, pred, val))
        if conn.execute(
                "SELECT 1 FROM facts WHERE program_id=? AND subject_type=? AND subject_key=? "
                "AND predicate=? AND value=? AND status='current'",
                (program_id, st, sk, pred, val)).fetchone():
            return
    conn.execute(
        "INSERT INTO facts(program_id,subject_type,subject_key,predicate,value,observation_id,"
        "valid_from,status) VALUES (?,?,?,?,?,?, COALESCE(?, datetime('now')), 'current')",
        (program_id, st, sk, pred, val, obs_id, event_at))


def _suspect_decision(conn, program_id: str, doc_id: int, obs_id: int, o: dict,
                      event_at: str | None) -> None:
    """Record a non-capability observation as a suspected decision awaiting human
    confirm (dedup on subject/predicate/value/document)."""
    sk, pred, val = o["subject_key"], o["predicate"], o["value"]
    dup = conn.execute(
        "SELECT 1 FROM decisions WHERE program_id=? AND subject_key=? AND predicate=? "
        "AND IFNULL(value,'')=IFNULL(?,'') AND source_document_id=?",
        (program_id, sk, pred, val, doc_id)).fetchone()
    if dup:
        return
    kind = _DECISION_KIND.get(pred, "other")
    rationale = f"{o.get('decision_state', 'proposed')} in source; predicate '{pred}'"
    conn.execute(
        "INSERT INTO decisions(program_id,kind,subject_type,subject_key,predicate,value,"
        "source_document_id,observation_id,status,confidence,rationale,created_at) "
        "VALUES (?,?,?,?,?,?,?,?, 'suspected', ?, ?, COALESCE(?, datetime('now')))",
        (program_id, kind, o["subject_type"], sk, pred, val, doc_id, obs_id,
         o.get("confidence", 0.6), rationale, event_at))


def _wire_graph(conn, program_id: str, doc_id: int, em, res: dict, program_eid: int,
                obs_rows: list[tuple[int, dict]], event_at: str | None = None) -> None:
    """Turn one email's people + vendor + observations into graph nodes/edges."""
    vendor_name = res.get("vendor")
    vendor_eid = None
    if vendor_name and vendor_name != "Unknown vendor":
        vendor_eid = graph.resolve_entity(conn, program_id, "vendor", vendor_name,
                                          source_document_id=doc_id)
    # people: sender + recipients → person nodes; sender at a vendor domain works_at it
    sender = _parse_addr(em.email_from)
    if sender:
        name, email = sender
        pid = graph.resolve_entity(conn, program_id, "person", email,
                                   attrs={"name": name, "email": email},
                                   source_document_id=doc_id)
        if name != email:
            graph.add_alias(conn, program_id, pid, "person", name, source_document_id=doc_id)
        if vendor_eid and em.direction == "inbound":
            graph.add_edge(conn, program_id, pid, "works_at", vendor_eid,
                           source_document_id=doc_id, confidence=0.7, event_at=event_at)
    # observation-derived edges (vendor → cell line / assay / program)
    if vendor_eid:
        for obs_id, o in obs_rows:
            spec = _OBS_EDGE.get(o["predicate"])
            if not spec:
                continue
            pred, dst_type = spec
            dst_eid = (program_eid if dst_type == "program"
                       else graph.resolve_entity(conn, program_id, dst_type, o["value"],
                                                 source_document_id=doc_id))
            props = {"amount": o["value"]} if o["predicate"] == "quoted_amount" else None
            graph.add_edge(conn, program_id, vendor_eid, pred, dst_eid,
                           observation_id=obs_id, source_document_id=doc_id,
                           confidence=o.get("confidence", 0.8), props=props, event_at=event_at)


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
        # graph children before entities; decisions/facts/observations before documents
        for t in ("decisions", "edges", "entity_aliases", "entities",
                  "facts", "observations", "documents"):
            conn.execute(f"DELETE FROM {t} WHERE program_id=?", (program_id,))
    if own:
        conn.close()


def ingest(program_id: str = DEMO_PROGRAM_ID, source: str | None = None,
           limit: int | None = None, do_reset: bool = True,
           use_llm: bool = False, extract_attachments: bool = False,
           api_key: str | None = None) -> dict:
    """Build the corpus + world model. With use_llm=True, an LLM decision extractor
    runs on each non-noise email. With extract_attachments=True, data-bearing
    attachments are LLM-extracted into review_data approval items (fluff skipped
    free). Both add per-item LLM cost, so off by default for programmatic callers."""
    from ...ingest.mailbox import parse_dt
    conn = db.connect()
    # Snapshot precomputed triage BEFORE reset so re-ingest doesn't empty the mailbox
    # (documents are rebuilt from the same stable source_ref slugs).
    triage_snap = {}
    if do_reset:
        triage_snap = {r["source_ref"]: (r["triage_json"], r["seen"]) for r in conn.execute(
            "SELECT source_ref,triage_json,seen FROM documents "
            "WHERE program_id=? AND triage_json IS NOT NULL", (program_id,)).fetchall()}
        reset(program_id, conn=conn)
    src = get_source(source, org=org_for_program(program_id))
    counts = {"documents": 0, "observations": 0, "facts": 0, "entities": 0,
              "edges": 0, "decisions": 0, "by_type": {}}
    n = 0
    with conn:
        prow = conn.execute("SELECT name FROM programs WHERE id=?", (program_id,)).fetchone()
        program_eid = graph.resolve_entity(
            conn, program_id, "program", (prow["name"] if prow else program_id))
        # bridge the molecule identity system (molecules/aliases/assays) into the graph
        graph.sync_molecules(conn, program_id, program_eid)
        # Process in true chronological order so the world model accrues over time
        # (unparseable dates sort last, keeping their original relative order).
        from datetime import datetime, timezone
        _MAX = datetime.max.replace(tzinfo=timezone.utc)
        emails = sorted(src.emails(), key=lambda e: parse_dt(e.date) or _MAX)
        for em in emails:
            if limit and n >= limit:
                break
            event_at = em.date  # ISO-8601 sent_at → event time for facts/edges/decisions
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
            obs_rows: list[tuple[int, dict]] = []
            for o in res.get("observations", []):
                oc = conn.execute(
                    "INSERT INTO observations(program_id,subject_type,subject_key,predicate,"
                    "value,source_document_id,decision_state,confidence) VALUES (?,?,?,?,?,?,?,?)",
                    (program_id, o["subject_type"], o["subject_key"], o["predicate"],
                     o["value"], doc_id, o.get("decision_state", "proposed"),
                     o.get("confidence", 0.7)))
                obs_rows.append((oc.lastrowid, o))
                counts["observations"] += 1
                # Capability claims are facts about the world → auto-promote (as before).
                # Everything else is a decision-shaped claim → suspected-decisions queue,
                # promoted to facts only on human confirmation (see engine/decisions.py).
                if o["predicate"] in CAPABILITY_PREDICATES:
                    if o.get("decision_state") == "agreed":
                        _promote(conn, program_id, oc.lastrowid, o, event_at)
                else:
                    _suspect_decision(conn, program_id, doc_id, oc.lastrowid, o, event_at)
                    counts["decisions"] += 1
            _wire_graph(conn, program_id, doc_id, em, res, program_eid, obs_rows, event_at)
            # LLM decision extraction (free-text decisions the regex misses)
            if use_llm and res["triage"] != "noise":
                from .. import decisions as D
                for cand in D.extract_decisions(em, api_key=api_key):
                    if D.insert_suspected(conn, program_id, cand, doc_id, event_at):
                        counts["decisions"] += 1
            # attachment data extraction → review_data approval items
            if extract_attachments and "--- attachment:" in (em.full_text or ""):
                from .. import attachments as ATT
                counts["attachment_rows"] = counts.get("attachment_rows", 0) + ATT.stage_document(
                    conn, program_id, doc_id, em.subject or "", em.email_from or "",
                    em.full_text or "", api_key=api_key)
            _stage_inbox_item(conn, program_id, doc_id, em, res)
            # restore precomputed triage for this rebuilt document, if we had it
            snap = triage_snap.get(em.source_ref)
            if snap:
                conn.execute("UPDATE documents SET triage_json=?, seen=? WHERE id=?",
                             (snap[0], snap[1], doc_id))
            n += 1
        counts["facts"] = conn.execute(
            "SELECT COUNT(*) c FROM facts WHERE program_id=? AND status='current'",
            (program_id,)).fetchone()["c"]
        counts["entities"] = conn.execute(
            "SELECT COUNT(*) c FROM entities WHERE program_id=?", (program_id,)).fetchone()["c"]
        counts["edges"] = conn.execute(
            "SELECT COUNT(*) c FROM edges WHERE program_id=? AND status='current'",
            (program_id,)).fetchone()["c"]
        counts["suspected_decisions"] = conn.execute(
            "SELECT COUNT(*) c FROM decisions WHERE program_id=? AND status='suspected'",
            (program_id,)).fetchone()["c"]
    conn.close()
    return counts
