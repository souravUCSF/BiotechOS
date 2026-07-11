"""Structured quote-line query surface + backfill.

Each priced line of a vendor quote is stored as a row in `quote_lines` with the
numeric amount and parsed quantity/unit/turnaround in real columns, so aggregate
and comparison queries ("cheapest 50 mg option", "price vs turnaround across
vendors") are precise — not dependent on reading free text.
"""
from __future__ import annotations

from ..config import DEMO_PROGRAM_ID
from ..state import db

_SORTS = {"amount": "amount ASC", "amount_desc": "amount DESC",
          # NULL turnaround sorts LAST so "fastest" returns lines with real data first
          "turnaround": "turnaround_days_max IS NULL, turnaround_days_max ASC",
          "recent": "sent_at DESC"}


def list_quote_lines(program_id: str = DEMO_PROGRAM_ID, *, vendor: str | None = None,
                     document_id: int | None = None,
                     service: str | None = None, compound: str | None = None, unit: str | None = None,
                     quantity: float | None = None, min_amount: float | None = None,
                     max_amount: float | None = None, max_turnaround_days: int | None = None,
                     status: str | None = None, flagged: bool | None = None,
                     as_of: str | None = None, order: str = "amount", limit: int = 200) -> list[dict]:
    """Filtered/sorted quote lines. All filters optional; combine freely for
    comparison queries (e.g. unit='mg', quantity=50, order='amount')."""
    where = ["program_id=?"]
    args: list = [program_id]
    if vendor:
        where.append("vendor=?"); args.append(vendor)
    if document_id is not None:
        where.append("document_id=?"); args.append(document_id)
    if service:
        where.append("LOWER(service) LIKE ?"); args.append(f"%{service.lower()}%")
    if compound:
        where.append("UPPER(compound)=?"); args.append(compound.upper())
    if unit:
        where.append("LOWER(unit)=?"); args.append(unit.lower())
    if quantity is not None:
        where.append("quantity=?"); args.append(quantity)
    if min_amount is not None:
        where.append("amount>=?"); args.append(min_amount)
    if max_amount is not None:
        where.append("amount<=?"); args.append(max_amount)
    if max_turnaround_days is not None:
        where.append("turnaround_days_max IS NOT NULL AND turnaround_days_max<=?")
        args.append(max_turnaround_days)
    if status:
        where.append("status=?"); args.append(status)
    if flagged is not None:
        where.append("flagged=?"); args.append(int(flagged))
    if as_of:
        where.append("date(sent_at)<=?"); args.append(as_of)
    sql = (f"SELECT * FROM quote_lines WHERE {' AND '.join(where)} "
           f"ORDER BY {_SORTS.get(order, 'amount ASC')} LIMIT ?")
    args.append(limit)
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def recompute_flags(program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Re-run the deterministic grounding checks over stored quote lines (no LLM) —
    used after tuning a check, so flags reflect the new logic without re-extracting."""
    import types
    from .processors import quote as Q
    conn = db.connect()
    rows = conn.execute(
        "SELECT ql.id, ql.amount, ql.compound, ql.quantity, ql.source_span, d.raw_text "
        "FROM quote_lines ql JOIN documents d ON d.id=ql.document_id "
        "WHERE ql.program_id=? AND ql.method='llm'", (program_id,)).fetchall()
    updated, flagged = 0, 0
    with conn:
        for r in rows:
            text = r["raw_text"] or ""
            ln = types.SimpleNamespace(amount=r["amount"], source_span=r["source_span"],
                                       compound=r["compound"], quantity=r["quantity"], unit=None)
            _, flags = Q._verify(ln, text, Q._norm_ws(text), Q._numeric_tokens(text))
            conn.execute("UPDATE quote_lines SET flagged=?, flag_reasons=? WHERE id=?",
                         (int(bool(flags)), ",".join(flags) or None, r["id"]))
            updated += 1
            flagged += 1 if flags else 0
    conn.close()
    return {"updated": updated, "flagged": flagged}


def backfill_quote_lines(program_id: str = DEMO_PROGRAM_ID, api_key: str | None = None) -> dict:
    """Re-extract every quote document and (re)build its quoted_amount observations +
    suspected decisions + structured quote_lines. With `api_key`, uses the LLM quote
    extractor (format-agnostic); without, the deterministic parser. Leaves any human-
    CONFIRMED quote decision untouched. Idempotent."""
    from .triage import _doc_email
    from . import extract as EX
    from .corpus import store as S
    conn = db.connect()
    docs = conn.execute(
        "SELECT * FROM documents WHERE program_id=? AND doc_type='quote' ORDER BY sent_at",
        (program_id,)).fetchall()
    stats = {"documents": 0, "quote_lines": 0, "decisions": 0, "flagged": 0, "llm": 0, "regex": 0}
    for r in docs:
        doc_id = r["id"]
        res = EX.extract(program_id, _doc_email(r), conn=conn, api_key=api_key)  # LLM call OUTSIDE txn
        with conn:   # commit per document → short lock windows, resilient to interruption
            # keep confirmed quote decisions + their observations; wipe only suspects
            confirmed_obs = [row["observation_id"] for row in conn.execute(
                "SELECT observation_id FROM decisions WHERE source_document_id=? "
                "AND predicate='quoted_amount' AND status='confirmed'", (doc_id,)).fetchall()]
            conn.execute("DELETE FROM quote_lines WHERE document_id=? AND status!='confirmed'",
                         (doc_id,))
            conn.execute("DELETE FROM decisions WHERE source_document_id=? "
                         "AND predicate='quoted_amount' AND status='suspected'", (doc_id,))
            keep = ",".join("?" * len(confirmed_obs)) or "NULL"
            conn.execute(f"DELETE FROM observations WHERE source_document_id=? "
                         f"AND predicate='quoted_amount' AND id NOT IN ({keep})",
                         (doc_id, *confirmed_obs))
            for o in res.get("observations", []):
                if o["predicate"] != "quoted_amount":
                    continue
                ql = o.get("quote_line", {})
                stats[ql.get("method", "regex")] += 1
                if ql.get("flagged"):
                    stats["flagged"] += 1
                oc = conn.execute(
                    "INSERT INTO observations(program_id,subject_type,subject_key,predicate,"
                    "value,source_document_id,decision_state,confidence) VALUES (?,?,?,?,?,?,?,?)",
                    (program_id, o["subject_type"], o["subject_key"], "quoted_amount",
                     o["value"], doc_id, o.get("decision_state", "proposed"),
                     o.get("confidence", 0.8)))
                dec_id = S._suspect_decision(conn, program_id, doc_id, oc.lastrowid, o, r["sent_at"])
                if dec_id is not None:
                    stats["decisions"] += 1
                if ql:
                    S._insert_quote_line(conn, program_id, doc_id, oc.lastrowid, dec_id,
                                         o["subject_key"], ql, r["sent_at"])
                    stats["quote_lines"] += 1
            stats["documents"] += 1
    conn.close()
    return stats
