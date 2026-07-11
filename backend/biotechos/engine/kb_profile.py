"""Reusable entity profiles (address, phone, email, contact) from the knowledge base.

Vendor/company profile details get extracted into `facts` under many different
predicate names (registered_address, office_address, vendor_address, contact_name,
contact_email, ...). This module normalizes them into a small canonical field set
so surfaces like the PO maker can auto-fill "missing" info from the KB, and writes
user-entered/edited values back so they're reused next time.
"""
from __future__ import annotations

from ..config import DEMO_PROGRAM_ID
from ..state import db
from . import graph
from .corpus import store as corpus_store

# canonical field -> predicate keywords (checked in this priority order, so
# 'contact_email' maps to email, not contact)
_FIELDS = [
    ("email", ("email", "e-mail")),
    ("phone", ("phone", "tel", "fax", "mobile")),
    ("website", ("website", "url", "homepage")),
    ("address", ("address", "location", "street", "city_state")),
    ("contact", ("contact", "signatory", "attention", "requisitioner")),
]
CANONICAL = [f for f, _ in _FIELDS]


def _field_for(predicate: str) -> str | None:
    p = predicate.lower()
    for field, kws in _FIELDS:
        if any(k in p for k in kws):
            return field
    return None


def get_details(program_id: str, entity_type: str, name: str) -> dict:
    """Canonical profile fields for one entity, drawn from current facts. Each field
    carries its value + the source predicate so the UI can show it's from the KB."""
    target = graph.normalize_key(entity_type, name)
    conn = db.connect()
    try:
        # match across name variants (Vendor 1 / Vendor 1, Inc.) by normalizing the
        # subject_key the same way the entity graph dedupes vendors/companies.
        rows = conn.execute(
            "SELECT f.subject_key, f.predicate, f.value, o.source_document_id AS doc_id "
            "FROM facts f LEFT JOIN observations o ON o.id=f.observation_id "
            "WHERE f.program_id=? AND f.status='current' AND f.value IS NOT NULL",
            (program_id,)).fetchall()
    finally:
        conn.close()
    fields: dict[str, dict] = {}
    for r in rows:
        if graph.normalize_key(entity_type, r["subject_key"]) != target:
            continue
        field = _field_for(r["predicate"])
        if not field or field in fields:
            continue
        # prefer an exactly-named predicate over a prefixed one if both appear
        fields[field] = {"value": r["value"], "predicate": r["predicate"],
                         "source_document_id": r["doc_id"], "from_kb": True}
    return {"entity_type": entity_type, "name": name, "fields": fields}


def save_details(program_id: str, entity_type: str, name: str, fields: dict) -> dict:
    """Persist user-entered profile fields into the KB (entity + agreed facts under
    canonical predicates) so they auto-fill next time. Only writes changed values."""
    if not name:
        return {"saved": 0}
    conn = db.connect()
    saved = 0
    try:
        with conn:
            eid = graph.resolve_entity(conn, program_id, entity_type, name)
            for field, value in fields.items():
                if field not in CANONICAL or value is None or str(value).strip() == "":
                    continue
                value = str(value).strip()
                cur = conn.execute(
                    "SELECT value FROM facts WHERE program_id=? AND subject_type=? AND subject_key=? "
                    "AND predicate=? AND status='current'",
                    (program_id, entity_type, name, field)).fetchone()
                if cur and cur["value"] == value:
                    continue                      # unchanged
                oc = conn.execute(
                    "INSERT INTO observations(program_id,subject_type,subject_key,predicate,value,"
                    "source_document_id,decision_state,confidence) VALUES (?,?,?,?,?,NULL,'agreed',1.0)",
                    (program_id, entity_type, name, field, value))
                corpus_store._promote(conn, program_id, oc.lastrowid,
                                      {"subject_type": entity_type, "subject_key": name,
                                       "predicate": field, "value": value})
                saved += 1
        _ = eid
    finally:
        conn.close()
    return {"saved": saved, **get_details(program_id, entity_type, name)}
