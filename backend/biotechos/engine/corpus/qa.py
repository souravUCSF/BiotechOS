"""Knowledge Q&A — structured-facts-first grounded RAG (anti-hallucination).

ask(): plan the query → answer from `facts` deterministically when possible
(the LLM only phrases retrieved rows, cannot invent values) → else FTS5 over
`documents` → grounded synthesis with citations, "not found" allowed.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from ...config import DEMO_PROGRAM_ID, MODEL_ARTIFACTS, MODEL_EXTRACTION
from ...state import db
from .. import llm
from ..extract import VENDOR_BY_DOMAIN

VENDORS = list(VENDOR_BY_DOMAIN.values())
_STOP = {"which", "what", "can", "test", "does", "the", "for", "from", "with", "who",
         "how", "much", "are", "at", "is", "of", "a", "an", "to", "do", "you", "they"}


def _vendor_in(q: str) -> str | None:
    for v in VENDORS:
        if v.lower() in q.lower() or v.split()[0].lower() in q.lower():
            return v
    return None


# --- agentic document retrieval + read (for questions facts can't answer) -----
class _Queries(BaseModel):
    queries: list[str]


class _Read(BaseModel):
    found: bool
    answer: str
    cited_docs: list[int] = []
    need_search: str | None = None


# Shared domain header — grounding rules + a tight CRO/biotech glossary. Kept
# short on purpose (a bloated header dilutes attention and induces confident errors).
_DOMAIN = (
    "Context: you are answering over a biotech CRO email/document corpus. "
    "Grounding: use ONLY the material provided; never invent values; if it isn't "
    "there, say 'not found'. "
    "Notes: units — uM means µM (micromolar), nM = nanomolar; IC50/EC50/GI50 are "
    "potency. Assays — ADP-Glo/HTRF = kinase activity; intact-MS/HRMS = covalent "
    "binding; Caco-2 = permeability/ADME. CRO quotes may be priced per-compound OR "
    "as a total; 'TAT'/'working days' = turnaround. Compound codes may be written "
    "with or without leading zeros or dashes (CLO-00003, CLO00003, CLO 3 are the SAME "
    "molecule) — treat them as equivalent and do not over-trust exact digits. "
    "Targets: TGTA (on-target), TGTB (anti-target); molecules are coded BTX-####.")


_PLANNER = (
    _DOMAIN + "\n\n"
    "Generate 3-5 short keyword search queries to find emails/attachments that "
    "answer the question. Use synonyms + likely phrasings: price→cost, quote, "
    "quotation, fee, USD, per compound; turnaround→TAT, working days, timeline, "
    "delivery; capability→services, assays, offer, can run. Always include the "
    "vendor name and the assay/technique. Return JSON {queries:[...]}, each a few keywords.")
_READER = (
    _DOMAIN + "\n\n"
    "Answer the QUESTION using ONLY the EXCERPTS (emails + attachment text). Cite "
    "INLINE: put [doc <id>] immediately after each statement, using the exact doc id "
    "numbers shown in the excerpts. Also put those ids in cited_docs. If the excerpts "
    "clearly contain the answer, set "
    "found=true and give a concise answer with the SPECIFIC values (prices, days, "
    "vendors) and units. IMPORTANT: if the excerpts contain MULTIPLE quotes/prices "
    "relevant to the question (e.g. different quote numbers, dates, or per-compound vs "
    "total pricing), list ALL of them with their identifying context (quote number, "
    "date, quantity) — do not pick just one. If the answer isn't present, set "
    "found=false and, if a different search might help, put keywords in need_search. "
    "Never invent values not in the excerpts.")


def _fts_run(conn, program_id: str, expr: str, k: int) -> list[dict]:
    try:
        rows = conn.execute(
            "SELECT d.id, d.subject, d.email_from, d.sent_at, d.doc_type, "
            "snippet(documents_fts,1,'[',']','…',16) AS snip "
            "FROM documents_fts f JOIN documents d ON d.id=f.rowid "
            "WHERE documents_fts MATCH ? AND d.program_id=? ORDER BY rank LIMIT ?",
            (expr, program_id, k)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _or_expr(query: str) -> str | None:
    words = [re.sub(r"[^A-Za-z0-9]", "", w) for w in str(query).split()]
    words = [w for w in words if len(w) >= 2 and w.lower() not in _STOP]
    return " OR ".join(words[:12]) or None


def _fts_search(conn, program_id: str, query: str, k: int = 8) -> list[dict]:
    e = _or_expr(query)
    return _fts_run(conn, program_id, e, k) if e else []


_VALUE_RE = re.compile(r"\$ ?[0-9][0-9,]*\.?[0-9]*|[0-9]+\s*(?:working days|weeks|business days)")


def _value_windows(body: str, radius: int = 160, maxw: int = 8) -> list[str]:
    """Windows around every price/timeline token, so values deep in long quote
    attachments reach the reader regardless of position."""
    out, seen = [], set()
    for m in _VALUE_RE.finditer(body or ""):
        s = max(0, m.start() - radius)
        w = body[s:m.end() + radius].strip()
        key = w[:40]
        if key not in seen:
            seen.add(key)
            out.append(w)
        if len(out) >= maxw:
            break
    return out


def _plan_queries(question: str, api_key: str | None) -> list[str]:
    qs, _ = llm.structured(model=MODEL_EXTRACTION, system=_PLANNER, user=question,
                           schema=_Queries, fallback=_Queries(queries=[question]),
                           api_key=api_key)
    out = [q for q in qs.queries if str(q).strip()]
    return out or [question]


def _retrieve(conn, program_id: str, queries: list[str], anchor: str | None = None,
              k: int = 10, cap: int = 16) -> list[dict]:
    """Union retrieval. If `anchor` (a vendor/entity token) is given, run
    vendor-anchored `anchor AND (…)` queries FIRST so the discriminating doc
    surfaces even when common terms flood a pure-OR search."""
    seen: dict[int, dict] = {}
    atok = re.sub(r"[^A-Za-z0-9]", "", anchor) if anchor else None
    if atok and len(atok) >= 2:
        for q in queries:
            e = _or_expr(q)
            if e:
                for r in _fts_run(conn, program_id, f"{atok} AND ({e})", k):
                    seen.setdefault(r["id"], r)
    for q in queries:
        for r in _fts_search(conn, program_id, q, k):
            seen.setdefault(r["id"], r)
    return list(seen.values())[:cap]


def _agentic_read(conn, program_id: str, question: str, cands: list[dict],
                  api_key: str | None, rounds: int = 2):
    """Read retrieved excerpts, optionally re-search, answer grounded + cited."""
    read = None
    for i in range(rounds):
        blocks = []
        for c in cands:
            row = conn.execute("SELECT raw_text FROM documents WHERE id=?", (c["id"],)).fetchone()
            body = (row["raw_text"] or "") if row else ""
            snip = (c.get("snip") or "").replace("[", "").replace("]", "")
            # prices/timelines/quote-numbers often sit deep in long quote PDFs (past
            # any head window), so pull a window around every such token too.
            windows = _value_windows(body)
            blocks.append(f"[doc {c['id']}] {c['subject']}\nMATCH: …{snip}…\n{body[:3000]}"
                          + ("\n…\n" + "\n…\n".join(windows) if windows else ""))
        fb = _Read(found=bool(cands),
                   answer=("Related emails:\n" + "\n".join(f"- [doc {c['id']}] {c['subject']}"
                           for c in cands[:5])) if cands else "Not found in the corpus.",
                   cited_docs=[c["id"] for c in cands[:5]])
        read, _ = llm.structured(model=MODEL_ARTIFACTS, system=_READER,
                                 user=f"QUESTION: {question}\n\nEXCERPTS:\n" + "\n\n".join(blocks),
                                 schema=_Read, fallback=fb, api_key=api_key, max_tokens=800)
        if read.found or not read.need_search or i == rounds - 1:
            break
        more = _retrieve(conn, program_id, [read.need_search], k=8)
        have = {c["id"] for c in cands}
        cands += [m for m in more if m["id"] not in have]
    return read, cands


def _number_citations(conn, answer: str, extra_ids: list[int] | None = None):
    """Remap inline `[doc <id>]` markers the LLM wrote → sequential `[1],[2]…` in
    order of first appearance, and return the ordered, numbered citation list."""
    order: list[int] = []

    def repl(m):
        did = int(m.group(1))
        if did not in order:
            order.append(did)
        return f"[{order.index(did) + 1}]"

    # match [doc 2630], (doc 2630, doc 2882), "doc 2630", "docs 2630" → [n]
    answer = re.sub(r"\[?\s*docs?\s*#?\s*(\d+)\s*\]?", repl, answer or "", flags=re.I)
    for did in extra_ids or []:      # cited-but-not-inlined sources go at the end
        if did and did not in order:
            order.append(did)
    cits = []
    for i, did in enumerate(order, 1):
        c = _cite(conn, did)
        if c:
            c["n"] = i
            cits.append(c)
    # guarantee numbered markers exist even if the LLM omitted inline citations
    if cits and not re.search(r"\[\d+\]", answer):
        answer = answer.rstrip() + " " + "".join(f"[{c['n']}]" for c in cits)
    return answer, cits


def _cite(conn, doc_id: int, snippet: str | None = None) -> dict | None:
    """Full citation payload for the clickable source panel."""
    d = conn.execute(
        "SELECT id,subject,email_from,email_to,sent_at,doc_type,raw_text FROM documents WHERE id=?",
        (doc_id,)).fetchone()
    if not d:
        return None
    body = (d["raw_text"] or "")[:6000]
    return {"id": d["id"], "subject": d["subject"], "email_from": d["email_from"],
            "email_to": d["email_to"], "sent_at": d["sent_at"], "doc_type": d["doc_type"],
            "snippet": snippet, "body": body}


def ask(program_id: str = DEMO_PROGRAM_ID, question: str = "", api_key: str | None = None) -> dict:
    conn = db.connect()
    q = question.strip()
    facts_hit: list[dict] = []
    citations: list[dict] = []

    # --- query planning: use structured facts ONLY for the precise, repeatable
    # questions they answer well; everything else (pricing, turnaround, a specific
    # assay/protein) falls through to the agentic document read below. ---
    vendor = _vendor_in(q)
    ql = q.lower()
    # pricing / timing / specific-quote questions → documents (facts are too coarse)
    price_time = re.search(r"price|cost|how much|\$|quote|quotation|fee|charge|"
                           r"turn ?around|\btat\b|working days|how long|timeline|"
                           r"when will|delivery|lead time", ql)
    predicate = None
    if not price_time:
        if re.search(r"cell ?line|cell-?line", ql):
            predicate = "tests_cell_line"
        elif re.search(r"\bservices?\b|\boffer\b|capabilit|what can .*\b(do|run|test)\b", ql):
            predicate = "offers_service"

    if predicate:
        sql = ("SELECT f.subject_key, f.value, f.observation_id, o.source_document_id "
               "FROM facts f LEFT JOIN observations o ON o.id=f.observation_id "
               "WHERE f.program_id=? AND f.predicate=? AND f.status='current'")
        args = [program_id, predicate]
        if vendor:
            sql += " AND f.subject_key=?"
            args.append(vendor)
        facts_hit = [dict(r) for r in conn.execute(sql, args).fetchall()]

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
        # LLM phrasing, strictly grounded in the retrieved facts, with inline cites
        rows_txt = "\n".join(
            f"{f['subject_key']} | {predicate} | {f['value']} | source [doc {f['source_document_id']}]"
            for f in facts_hit)
        answer, used_llm = llm.text(
            model=MODEL_ARTIFACTS,
            system=(_DOMAIN + "\n\nAnswer ONLY from the FACT ROWS given. Do not add any value "
                    "not present. Be concise. Cite INLINE: put [doc <id>] after each vendor's "
                    "values, using the source shown in the row."),
            user=f"Question: {question}\n\nFACT ROWS:\n{rows_txt}",
            fallback=deterministic, api_key=api_key)
        answer, citations = _number_citations(
            conn, answer, [f["source_document_id"] for f in facts_hit if f.get("source_document_id")])
        conn.close()
        return {"answer": answer, "used_llm": used_llm, "citations": citations,
                "source": "facts", "fact_count": len(facts_hit)}

    # --- long-tail: agentic document retrieval + grounded read ---
    # LLM query-expansion → union retrieval over emails + attachment text → read
    # the excerpts, optionally re-search once, answer with the specific values + cite.
    queries = _plan_queries(question, api_key)
    anchor = vendor.split()[0] if vendor else None   # e.g. "BPS", "Vendor 1"
    cands = _retrieve(conn, program_id, queries, anchor=anchor)
    if not cands:
        conn.close()
        return {"answer": "Not found in the corpus.", "used_llm": False,
                "citations": [], "source": "none", "fact_count": 0}
    read, cands = _agentic_read(conn, program_id, question, cands, api_key)
    answer = read.answer if (read.found and read.answer) else "Not found in the corpus."
    extra = read.cited_docs or [c["id"] for c in cands[:3]]
    answer, citations = _number_citations(conn, answer, extra if read.found else [])
    conn.close()
    return {"answer": answer, "used_llm": True, "citations": citations,
            "source": "documents", "fact_count": 0}
