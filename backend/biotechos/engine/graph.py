"""Entity graph for the knowledge layer.

Ingestion turns each email's people / vendor / observations into typed entity
nodes (`entities`), aliases (`entity_aliases`) and edges (`edges`). Retrieval
(QueryOS) walks the graph to surface factually-connected sources. Names arrive in
many surface forms, so `normalize_key` collapses variants to one stable key used
both for entity dedupe and for grouping facts.
"""
from __future__ import annotations

import json
import re

# Legal-form / boilerplate suffixes stripped when comparing organization names.
_LEGAL_SUFFIXES = (
    "incorporated", "inc", "corporation", "corp", "company", "co",
    "limited", "ltd", "llc", "llp", "lp", "plc", "gmbh", "ag", "sa",
    "srl", "bv", "pvt", "private", "pte", "kk", "kg", "aps",
)
_LEGAL_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(s) for s in _LEGAL_SUFFIXES) + r")\b", re.IGNORECASE
)


def normalize_key(entity_type: str, name: str) -> str:
    """Stable dedupe key for an entity. Case/punctuation/legal-form insensitive:
    normalize_key('vendor','Vendor 1, Inc.') == normalize_key('vendor','vendor-1')."""
    n = (name or "").lower()
    n = _LEGAL_RE.sub(" ", n)
    n = re.sub(r"[^a-z0-9]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return f"{(entity_type or '').lower()}:{n}"


def resolve_entity(conn, program_id: str, entity_type: str, name: str, *,
                   source_document_id: int | None = None, display_name: str | None = None,
                   attrs: dict | None = None) -> int:
    """Find-or-create an entity node; returns its integer id. Dedupes on the
    normalized key. First-seen display_name/attrs are kept."""
    key = normalize_key(entity_type, name)
    row = conn.execute(
        "SELECT id FROM entities WHERE program_id=? AND entity_type=? AND canonical_key=?",
        (program_id, entity_type, key)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO entities(program_id,entity_type,canonical_key,display_name,attrs_json) "
        "VALUES (?,?,?,?,?)",
        (program_id, entity_type, key, (display_name or name),
         json.dumps(attrs) if attrs else None))
    return cur.lastrowid


def add_alias(conn, program_id: str, entity_id: int, entity_type: str, alias: str, *,
              source_document_id: int | None = None) -> None:
    """Record an alternate surface form for an entity (idempotent)."""
    if not alias:
        return
    conn.execute(
        "INSERT OR IGNORE INTO entity_aliases(program_id,entity_id,alias,alias_norm,source_document_id) "
        "VALUES (?,?,?,?,?)",
        (program_id, entity_id, alias, normalize_key(entity_type, alias), source_document_id))


def add_edge(conn, program_id: str, src_entity_id: int, predicate: str, dst_entity_id: int, *,
             observation_id: int | None = None, source_document_id: int | None = None,
             confidence: float = 0.8, props: dict | None = None,
             event_at: str | None = None) -> None:
    """Add a typed, provenance-carrying edge between two entities."""
    conn.execute(
        "INSERT INTO edges(program_id,src_entity_id,predicate,dst_entity_id,observation_id,"
        "source_document_id,confidence,props_json,valid_from) VALUES (?,?,?,?,?,?,?,?,COALESCE(?,datetime('now')))",
        (program_id, src_entity_id, predicate, dst_entity_id, observation_id,
         source_document_id, confidence, json.dumps(props) if props else None, event_at))


def sync_molecules(conn, program_id: str, program_eid: int) -> None:
    """Bridge the molecule identity system (molecules + molecule_aliases) into the
    entity graph as 'molecule' nodes so they can be mentioned/retrieved. Idempotent."""
    for m in conn.execute(
            "SELECT id, name FROM molecules WHERE program_id=? AND name IS NOT NULL",
            (program_id,)).fetchall():
        eid = resolve_entity(conn, program_id, "molecule", m["name"],
                             attrs={"molecule_id": m["id"]})
        for a in conn.execute(
                "SELECT alias FROM molecule_aliases WHERE program_id=? AND molecule_id=?",
                (program_id, m["id"])).fetchall():
            add_alias(conn, program_id, eid, "molecule", a["alias"])


def _molecule_assay_summary(conn, molecule_id: int) -> list[dict]:
    """Compact per-(modality,target,type) assay summary for a molecule (for QueryOS)."""
    rows = conn.execute(
        "SELECT modality, target, standard_type, units, COUNT(*) AS n, AVG(value) AS avg_value "
        "FROM assays WHERE molecule_id=? AND value IS NOT NULL "
        "GROUP BY modality, target, standard_type, units ORDER BY n DESC",
        (molecule_id,)).fetchall()
    return [dict(r) for r in rows]


def resolve_mentions(conn, program_id: str, text: str) -> list[int]:
    """Entity ids whose display name or a known alias appears in the text (>=4 chars,
    case-insensitive substring). Used to graph-boost retrieval by named entities."""
    tl = (text or "").lower()
    if not tl:
        return []
    ids: set[int] = set()
    for r in conn.execute(
            "SELECT id, display_name FROM entities WHERE program_id=?", (program_id,)).fetchall():
        dn = (r["display_name"] or "").lower()
        if len(dn) >= 4 and dn in tl:
            ids.add(r["id"])
    for r in conn.execute(
            "SELECT entity_id, alias FROM entity_aliases WHERE program_id=?", (program_id,)).fetchall():
        al = (r["alias"] or "").lower()
        if len(al) >= 4 and al in tl:
            ids.add(r["entity_id"])
    return list(ids)


def neighborhood_doc_ids(conn, program_id: str, entity_id: int, limit: int = 20) -> list[int]:
    """Documents behind an entity's edges — factually-connected sources for retrieval."""
    rows = conn.execute(
        "SELECT DISTINCT source_document_id FROM edges "
        "WHERE program_id=? AND (src_entity_id=? OR dst_entity_id=?) "
        "AND source_document_id IS NOT NULL LIMIT ?",
        (program_id, entity_id, entity_id, limit)).fetchall()
    return [r["source_document_id"] for r in rows]
