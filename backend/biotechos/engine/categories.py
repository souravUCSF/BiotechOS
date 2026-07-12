"""The 5-way business classification shared across the app.

`classifier.py` produces these categories from an email (LLM); at ingest each document
also gets a finer `doc_type`. This module is the single place that folds a document into
one of the five buckets and says which are actionable. A human reclassification stored in
`documents.triage_json.category` (written by the mailbox "re-classify" action) wins over
the doc_type mapping.
"""
from __future__ import annotations

import json

CATEGORIES = ("quote", "invoice", "legal", "data", "other")
# Only these are acted upon by the system; 'other' is read-only.
ACTIONABLE = frozenset({"quote", "invoice", "legal", "data"})

# doc_type → 5-way category. Handles legacy doc_types (contract, cro_data, …) and cases
# where doc_type already holds a 5-way value.
_DT2CAT = {"quote": "quote", "invoice": "invoice", "contract": "legal", "cro_data": "data",
           "data": "data", "legal": "legal", "other": "other"}


def category_for(conn, doc_id: int | None, doc_type: str | None) -> str:
    """Effective 5-way category for a document — a human reclassification stored in
    triage_json wins; otherwise map the doc_type; unknown → 'other'."""
    if doc_id is not None:
        r = conn.execute("SELECT triage_json FROM documents WHERE id=?", (doc_id,)).fetchone()
        if r and r["triage_json"]:
            try:
                cat = json.loads(r["triage_json"]).get("category")
                if cat in CATEGORIES:
                    return cat
            except (TypeError, ValueError):
                pass
    return _DT2CAT.get(doc_type or "", "other")
