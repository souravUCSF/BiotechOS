"""Related-quote FYI — group priced quote lines by the task they cover.

Reads the structured `quote_lines` table (built by engine/quotes.py in a parallel
workstream) and clusters lines into task buckets (kinase IC50, intact-MS, ADME, PK,
synthesis, ...) so that when the user is looking at one quote, the system can say
"you already have N related quotes for the same task" and show them side by side.

Read-only; no schema changes. Categorization uses the line's service text first,
falling back to the parent email body when the line text alone is ambiguous.
"""
from __future__ import annotations

import re

from ..config import DEMO_PROGRAM_ID
from ..state import db

# task bucket -> (label, signal). Order = priority when a line matches several.
_BUCKETS = [
    ("kinase_ic50", "Kinase IC50 / activity", r"ic50|hotspot|kinase|adp-?glo|activity assay|htrf"),
    ("intact_ms", "Intact-MS (covalent binding)", r"intact|covalent|mass spec|\bhrms\b|labeling|deconvolution"),
    ("kinetics", "Binding kinetics", r"kinact|residence time|k[_ ]?off|k[_ ]?on|binding kinetic"),
    ("cell_prolif", "Cell proliferation", r"prolifer|gi50|cell (?:panel|viability|line)|anti-?prolif|ctg"),
    ("adme", "ADME", r"\badme\b|caco-?2|microsom|permeab|solubility|stability|ppb|clearance|metabol"),
    ("pk", "PK / in vivo", r"\bpk\b|pharmacokinet|in.?vivo|xenograft|\bcdx\b|\bpdx\b|mouse|rat|efficacy"),
    ("synthesis", "Compound synthesis", r"synthesis|resynth|scale.?up|custom synth|medchem|\bmg\b|building block"),
    ("protein", "Protein production", r"protein (?:express|prod|purif)|construct|his-?tag|recombinant"),
    ("structure", "Structural biology", r"crystal|co-?crystal|x-?ray|structure determination"),
]
_BUCKETS = [(k, lbl, re.compile(p, re.I)) for k, lbl, p in _BUCKETS]
_LABEL = {k: lbl for k, lbl, _ in _BUCKETS}


def _categorize(service_text: str, doc_body: str | None) -> str:
    for k, _lbl, pat in _BUCKETS:
        if pat.search(service_text or ""):
            return k
    for k, _lbl, pat in _BUCKETS:          # fallback: the parent email's content
        if doc_body and pat.search(doc_body):
            return k
    return "other"


def _lines(conn, program_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT ql.id, ql.document_id, ql.vendor, ql.service, ql.compound, ql.quantity, "
        "ql.unit, ql.amount, ql.currency, ql.turnaround_days_max, ql.status, ql.flagged, "
        "ql.sent_at, d.subject, substr(d.raw_text,1,4000) AS body "
        "FROM quote_lines ql JOIN documents d ON d.id=ql.document_id "
        "WHERE ql.program_id=? AND ql.amount IS NOT NULL AND ql.amount>0 "
        # exclude our own outbound RFQs (no identified CRO vendor) — not comparable offers
        "AND ql.vendor IS NOT NULL AND ql.vendor NOT IN ('Unknown vendor','Unknown')",
        (program_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["bucket"] = _categorize(d["service"], d.pop("body"))
        out.append(d)
    return out


def _fmt_line(d: dict) -> dict:
    return {"line_id": d["id"], "document_id": d["document_id"], "vendor": d["vendor"],
            "service": (d["service"] or "").strip()[:140], "compound": d["compound"],
            "quantity": d["quantity"], "unit": d["unit"], "amount": d["amount"],
            "currency": d["currency"] or "USD", "turnaround_days": d["turnaround_days_max"],
            "flagged": bool(d["flagged"]), "status": d["status"], "date": d["sent_at"],
            "subject": d["subject"]}


def quote_groups(program_id: str = DEMO_PROGRAM_ID, min_vendors: int = 2) -> list[dict]:
    """Quote lines grouped by task bucket, each listing the priced lines across vendors
    so related offers compare side by side. Only buckets with >= min_vendors distinct
    vendors are returned (there must be something to compare)."""
    conn = db.connect()
    try:
        lines = _lines(conn, program_id)
    finally:
        conn.close()
    by: dict[str, list[dict]] = {}
    for d in lines:
        by.setdefault(d["bucket"], []).append(d)
    groups = []
    for bucket, items in by.items():
        if bucket == "other":
            continue
        vendors = {i["vendor"] for i in items}
        if len(vendors) < min_vendors:
            continue
        items = sorted(items, key=lambda d: d["amount"])
        amounts = [i["amount"] for i in items]
        groups.append({
            "bucket": bucket, "label": _LABEL[bucket],
            "line_count": len(items), "vendor_count": len(vendors),
            "min_amount": min(amounts), "max_amount": max(amounts),
            "vendors": sorted(vendors),
            "lines": [_fmt_line(d) for d in items],
        })
    groups.sort(key=lambda g: (g["vendor_count"], g["line_count"]), reverse=True)
    return groups


def related_to_document(program_id: str, document_id: int, limit: int = 8) -> dict:
    """For one quote email, the related quote lines from OTHER vendors/emails in the
    same task bucket(s) — the per-quote FYI ('you already have N related quotes')."""
    conn = db.connect()
    try:
        lines = _lines(conn, program_id)
    finally:
        conn.close()
    mine = [d for d in lines if d["document_id"] == document_id]
    if not mine:
        return {"document_id": document_id, "buckets": [], "related": []}
    buckets = {d["bucket"] for d in mine if d["bucket"] != "other"}
    my_vendor = mine[0]["vendor"]
    related = [d for d in lines
               if d["document_id"] != document_id and d["bucket"] in buckets]
    # cheapest first, prefer other vendors
    related.sort(key=lambda d: (d["vendor"] == my_vendor, d["amount"]))
    return {
        "document_id": document_id, "vendor": my_vendor,
        "buckets": [_LABEL[b] for b in sorted(buckets)],
        "this_quote": [_fmt_line(d) for d in mine],
        "related": [_fmt_line(d) for d in related[:limit]],
    }
