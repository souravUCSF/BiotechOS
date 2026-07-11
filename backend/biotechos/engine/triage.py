"""Inbox triage — read the LATEST message of an email (not the quoted thread
history) and decide what the OS should do with it.

Buckets (the user's four):
  ignore      — marketing/no-reply/newsletters/scheduling cruft, nothing to do
  knowledge   — informative: vendor capability, project/status update, contract
                status, material logistics → log to the knowledge base
  processing  — carries data/results/an attachment to extract → load to the DB
  action      — needs a human decision/response: a quote to approve, an invoice
                to pay, a question to answer, an agreement to sign

LLM-first (grounded, reads only the new message); deterministic fallback maps the
existing keyword extractor's doc_type when no API key.
"""
from __future__ import annotations

import json
import re
import types

from pydantic import BaseModel

from ..config import DEMO_PROGRAM_ID, MODEL_ARTIFACTS
from ..state import db
from . import llm
from .corpus.qa import _DOMAIN
from . import extract as X

# markers that begin quoted thread history — cut everything from the first one.
_QUOTE_MARKERS = [
    r"\nOn .{0,120}?wrote:",
    r"\n-{2,}\s*Original Message",
    r"\nFrom:\s.{0,200}?\nSent:",
    r"\nFrom:\s.{0,200}?\nTo:",
    r"\n发件人[:：]",                 # Chinese "From:"
    r"\n________________________________",
    r"\n\*\*\*\s*CAUTION",             # external-email banner
]
_QUOTE_RE = re.compile("|".join(_QUOTE_MARKERS), re.I | re.S)


def latest_message(body: str) -> str:
    """Return just the newest message — strip quoted history + leading '>' lines."""
    if not body:
        return ""
    m = _QUOTE_RE.search(body)
    top = body[:m.start()] if m else body
    # drop quoted '>' lines and collapse whitespace
    top = "\n".join(ln for ln in top.splitlines() if not ln.lstrip().startswith(">"))
    top = top.strip()
    return top if len(top) >= 15 else body[:1500]   # fall back if we over-trimmed


def classify_input(email) -> str:
    """The text a classifier should read: the NEWEST message (quoted thread history
    stripped) plus any attachment text. Thread-safe and attachment-aware, so the
    call keys on what THIS email actually delivers — not the original thread topic."""
    body = getattr(email, "body", "") or getattr(email, "full_text", "") or ""
    newest = latest_message(body)
    full = getattr(email, "full_text", "") or body
    parts = [newest]
    try:
        from .attachments import parse_attachments
        for fn, txt in parse_attachments(full):
            if txt and txt.strip():
                parts.append(f"\n\n--- attachment: {fn} ---\n{txt}")
    except Exception:
        pass
    out = "\n".join(p for p in parts if p).strip()
    return out or body[:2000]


CATEGORIES = ["ignore", "knowledge", "processing", "action"]


class TriageResult(BaseModel):
    category: str            # ignore | knowledge | processing | action
    doc_type: str            # quote|invoice|cro_data|project_update|query|vendor_capability|contract|logistics|other|noise
    next_step: str           # short imperative — what the OS should do
    reason: str              # one line, why
    needs_reply: bool = False
    confidence: float = 0.6


_SYS = (
    _DOMAIN + "\n\n"
    "You are triaging one inbound email for a drug-discovery team. You are shown "
    "only the NEWEST message (quoted history removed). Decide the single best "
    "category:\n"
    "- ignore: marketing, newsletters, no-reply, scheduling/logistics cruft, "
    "auto-replies — nothing for the team to do.\n"
    "- knowledge: informative updates (a vendor's capabilities/menu, a project or "
    "status update, contract/CDA status, material shipment/location) → log to the "
    "knowledge base.\n"
    "- processing: the email delivers DATA/results or an attachment to extract "
    "(assay results, a report, dose-response, an intact-MS/kinetics dataset) → "
    "extract and load to the database.\n"
    "- action: needs a human decision or reply — a quote to approve, an invoice to "
    "pay, a scientific/logistics question to answer, an agreement to sign.\n"
    "Judge by what THIS message actually is, not the thread's original topic (a "
    "reply that just says 'sounds good' is ignore/knowledge, not a quote). Give a "
    "short concrete next_step and a one-line reason. Be decisive.")


def _fallback(email) -> TriageResult:
    """No API key: reuse the keyword extractor's doc_type, mapped to a bucket."""
    subj = email.subject or ""
    body = latest_message(getattr(email, "body", "") or email.full_text)
    tri = X.triage(subj, body)
    dt = X.classify(subj, body, "") if tri != "noise" else "noise"
    bucket = {"noise": "ignore", "cro_data": "processing",
              "quote": "action", "invoice": "action", "query": "action",
              "contract": "action", "vendor_capability": "knowledge",
              "project_update": "knowledge", "logistics": "knowledge"}.get(dt, "action")
    return TriageResult(category=bucket, doc_type=dt,
                        next_step="review", reason="keyword fallback (no API key)",
                        needs_reply=dt == "query", confidence=0.4)


def triage(email, program_id: str = DEMO_PROGRAM_ID, api_key: str | None = None) -> TriageResult:
    """Triage one Email-like object (needs .subject, .body/.full_text, .email_from)."""
    latest = latest_message(getattr(email, "body", "") or email.full_text)
    user = (f"From: {email.email_from}\nSubject: {email.subject}\n\n"
            f"NEWEST MESSAGE:\n{latest[:3000]}")
    res, used = llm.structured(model=MODEL_ARTIFACTS, system=_SYS, user=user,
                               schema=TriageResult, fallback=_fallback(email),
                               api_key=api_key, max_tokens=400)
    if res.category not in CATEGORIES:
        res.category = "action"
    return res


def _doc_email(row):
    return types.SimpleNamespace(
        subject=row["subject"] or "", full_text=row["raw_text"] or "",
        body=row["raw_text"] or "", email_from=row["email_from"] or "")


def triage_document(conn, row, api_key: str | None = None) -> dict:
    """Triage one stored `documents` row and persist triage_json. Returns the dict."""
    t = triage(_doc_email(row), api_key=api_key)
    payload = t.model_dump()
    conn.execute("UPDATE documents SET triage_json=? WHERE id=?", (json.dumps(payload), row["id"]))
    return payload


def backfill(program_id: str = DEMO_PROGRAM_ID, since: str | None = None,
             limit: int | None = None, only_inbound: bool = True,
             redo: bool = False, api_key: str | None = None) -> dict:
    """Precompute triage for stored emails lacking it (most-recent first). Keyword
    'noise' is stored as ignore WITHOUT an LLM call to save cost."""
    conn = db.connect()
    where = "program_id=?"
    args = [program_id]
    if only_inbound:
        where += " AND direction='inbound'"
    if since:
        where += " AND date(sent_at) >= ?"; args.append(since)
    if not redo:
        where += " AND (triage_json IS NULL OR triage_json='')"
    sql = f"SELECT * FROM documents WHERE {where} ORDER BY sent_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, args).fetchall()
    n, by_cat = 0, {}
    with conn:
        for r in rows:
            if (r["triage"] or "") == "noise":     # cheap prefilter → no LLM
                payload = {"category": "ignore", "doc_type": "noise",
                           "next_step": "ignore", "reason": "marketing/no-reply/noise",
                           "needs_reply": False, "confidence": 0.5}
                conn.execute("UPDATE documents SET triage_json=? WHERE id=?",
                             (json.dumps(payload), r["id"]))
            else:
                payload = triage_document(conn, r, api_key=api_key)
            by_cat[payload["category"]] = by_cat.get(payload["category"], 0) + 1
            n += 1
    conn.close()
    return {"triaged": n, "by_category": by_cat}
