"""Knowledge Q&A — structured-facts-first grounded RAG (anti-hallucination).

ask(): plan the query → answer from `facts` deterministically when possible
(the LLM only phrases retrieved rows, cannot invent values) → else FTS5 over
`documents` → grounded synthesis with citations, "not found" allowed.
"""
from __future__ import annotations

import re

from ...config import DEMO_PROGRAM_ID, MODEL_ARTIFACTS
from ...state import db
from .. import llm
from ..extract import VENDOR_BY_DOMAIN

VENDORS = list(VENDOR_BY_DOMAIN.values())


def _vendor_in(q: str) -> str | None:
    for v in VENDORS:
        if v.lower() in q.lower() or v.split()[0].lower() in q.lower():
            return v
    return None


def _fts(conn, program_id: str, query: str, k: int = 6) -> list[dict]:
    # sanitize to a safe FTS OR-query of the salient words
    words = [w for w in re.findall(r"[A-Za-z0-9\-]{3,}", query) if w.lower() not in
             {"which", "what", "can", "test", "does", "the", "for", "from", "with", "who"}]
    if not words:
        return []
    match = " OR ".join(words[:8])
    try:
        rows = conn.execute(
            "SELECT d.id, d.subject, d.email_from, d.sent_at, d.doc_type, "
            "snippet(documents_fts,1,'[',']','…',12) AS snip "
            "FROM documents_fts f JOIN documents d ON d.id=f.rowid "
            "WHERE documents_fts MATCH ? AND d.program_id=? ORDER BY rank LIMIT ?",
            (match, program_id, k)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def ask(program_id: str = DEMO_PROGRAM_ID, question: str = "", api_key: str | None = None) -> dict:
    conn = db.connect()
    q = question.strip()
    facts_hit: list[dict] = []
    citations: list[dict] = []

    # --- query planning: map to a structured facts lookup when possible ---
    vendor = _vendor_in(q)
    ql = q.lower()
    predicate = None
    if re.search(r"cell ?line|cell-?line", ql):
        predicate = "tests_cell_line"
    elif re.search(r"service|assay|offer|capab|do (?:they|you) (?:run|do)", ql):
        predicate = "offers_service"
    elif re.search(r"quote|price|cost|charge", ql):
        predicate = "quoted_amount"

    if predicate:
        sql = ("SELECT f.subject_key, f.value, f.observation_id, o.source_document_id "
               "FROM facts f LEFT JOIN observations o ON o.id=f.observation_id "
               "WHERE f.program_id=? AND f.predicate=? AND f.status='current'")
        args = [program_id, predicate]
        if vendor:
            sql += " AND f.subject_key=?"
            args.append(vendor)
        facts_hit = [dict(r) for r in conn.execute(sql, args).fetchall()]

    # gather citation docs from the facts' source documents
    doc_ids = sorted({f["source_document_id"] for f in facts_hit if f.get("source_document_id")})
    for did in doc_ids[:6]:
        d = conn.execute("SELECT id,subject,email_from,sent_at FROM documents WHERE id=?",
                         (did,)).fetchone()
        if d:
            citations.append(dict(d))

    # --- build the answer ---
    if facts_hit:
        # group values by vendor
        by_v: dict[str, list[str]] = {}
        for f in facts_hit:
            by_v.setdefault(f["subject_key"], []).append(f["value"])
        lines = [f"- **{v}**: " + ", ".join(sorted(set(vals))) for v, vals in sorted(by_v.items())]
        label = {"tests_cell_line": "cell lines tested",
                 "offers_service": "services offered",
                 "quoted_amount": "quoted amounts"}[predicate]
        deterministic = f"From the corpus ({label}):\n" + "\n".join(lines)
        # optional LLM phrasing, strictly grounded in the retrieved facts
        rows_txt = "\n".join(f"{f['subject_key']} | {predicate} | {f['value']}" for f in facts_hit)
        answer, used_llm = llm.text(
            model=MODEL_ARTIFACTS,
            system=("Answer ONLY from the FACT ROWS given. Do not add any value not present. "
                    "Be concise. If the rows don't answer the question, say so."),
            user=f"Question: {question}\n\nFACT ROWS:\n{rows_txt}",
            fallback=deterministic, api_key=api_key)
        conn.close()
        return {"answer": answer, "used_llm": used_llm, "citations": citations,
                "source": "facts", "fact_count": len(facts_hit)}

    # --- fallback: document retrieval (FTS5) ---
    docs = _fts(conn, program_id, q)
    conn.close()
    if not docs:
        return {"answer": "Not found in the corpus.", "used_llm": False,
                "citations": [], "source": "none", "fact_count": 0}
    context = "\n\n".join(f"[doc {d['id']}] {d['subject']}\n{d['snip']}" for d in docs)
    answer, used_llm = llm.text(
        model=MODEL_ARTIFACTS,
        system=("Answer ONLY from the provided email excerpts, citing [doc N]. "
                "If they don't contain the answer, say 'Not found in the corpus.'"),
        user=f"Question: {question}\n\nEXCERPTS:\n{context}",
        fallback="Related emails found (no API key for synthesis):\n" +
                 "\n".join(f"- [doc {d['id']}] {d['subject']}" for d in docs))
    return {"answer": answer, "used_llm": used_llm,
            "citations": [{"id": d["id"], "subject": d["subject"],
                           "email_from": d["email_from"], "sent_at": d["sent_at"]} for d in docs],
            "source": "documents", "fact_count": 0}
