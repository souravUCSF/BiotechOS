"""Entity graph — first-class nodes + typed edges over the facts core.

The observation/fact store answers "what value does (subject, predicate) hold?".
This layer answers the *relational* questions it can't: "what is everything about
vendor X?", "which vendors touch molecule Y?". Every subject string that shows up
in an observation is resolved to a deduplicated `entities` row; relationships
between them are recorded as bitemporal `edges` (same supersession discipline as
`facts`).

Edge writes are append-with-dedup: a relationship is multi-valued by nature (a
vendor tests many cell lines), so re-observing a `(src, predicate, dst)` that is
already current is a no-op rather than a supersession. `props_json` is the
forward-compat hook for the Phase-2 epistemic layer (commitment force/hedge/
honored) — nothing writes it yet.
"""
from __future__ import annotations

import json
import re

from . import identity, target_names

# vendor legal suffixes to strip so "Vendor 6" == "Vendor 6s, Inc."
_LEGAL = re.compile(r"\b(inc|llc|ltd|co|corp|corporation|company|gmbh|ag|sa|sas|"
                    r"biosciences?|bioscience|biotech|pharmaceuticals?|pharma|"
                    r"laboratories|labs?|technologies|technolog)\b", re.I)


def normalize_key(entity_type: str, name: str) -> str:
    """Canonical dedup key per entity type. Reuses molecule normalization so the
    graph and the molecule identity system agree on identity."""
    raw = (name or "").strip()
    if entity_type == "molecule":
        return identity.normalize(raw)
    if entity_type == "person" and "@" in raw:
        return raw.lower().strip("<> ")
    if entity_type == "vendor":
        base = _LEGAL.sub("", raw)
        return re.sub(r"[^a-z0-9]", "", base.lower())
    # cell_line / assay / program / contract / material: casefold + strip punctuation
    return re.sub(r"[^a-z0-9]", "", raw.lower())


def resolve_entity(conn, program_id: str, entity_type: str, name: str, *,
                   attrs: dict | None = None, source_document_id: int | None = None,
                   create: bool = True) -> int | None:
    """Resolve a raw name to a canonical entity id, creating it if new.
    Returns the entity id (or None when create=False and it doesn't exist)."""
    name = (name or "").strip()
    if not name:
        return None
    key = normalize_key(entity_type, name)
    if not key:
        return None
    # 1) alias table (surface names learned earlier)
    r = conn.execute(
        "SELECT entity_id FROM entity_aliases WHERE program_id=? AND alias_norm=? "
        "AND entity_id IN (SELECT id FROM entities WHERE entity_type=?) LIMIT 1",
        (program_id, key, entity_type)).fetchone()
    if r:
        return r["entity_id"]
    # 2) canonical key
    r = conn.execute(
        "SELECT id FROM entities WHERE program_id=? AND entity_type=? AND canonical_key=?",
        (program_id, entity_type, key)).fetchone()
    if r:
        return r["id"]
    if not create:
        return None
    # 3) create
    cur = conn.execute(
        "INSERT INTO entities(program_id,entity_type,canonical_key,display_name,attrs_json) "
        "VALUES (?,?,?,?,?)",
        (program_id, entity_type, key, name, json.dumps(attrs) if attrs else None))
    eid = cur.lastrowid
    conn.execute(
        "INSERT OR IGNORE INTO entity_aliases(program_id,entity_id,alias,alias_norm,"
        "source_document_id) VALUES (?,?,?,?,?)",
        (program_id, eid, name, key, source_document_id))
    return eid


def add_alias(conn, program_id: str, entity_id: int, entity_type: str, alias: str, *,
              source_document_id: int | None = None, confidence: float = 0.9) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO entity_aliases(program_id,entity_id,alias,alias_norm,"
        "source_document_id,confidence) VALUES (?,?,?,?,?,?)",
        (program_id, entity_id, alias, normalize_key(entity_type, alias),
         source_document_id, confidence))


def add_edge(conn, program_id: str, src_id: int, predicate: str, dst_id: int, *,
             observation_id: int | None = None, source_document_id: int | None = None,
             confidence: float = 0.8, props: dict | None = None,
             event_at: str | None = None) -> None:
    """Record a current relationship. No-op if the same (src,pred,dst) is already
    current (relationships are multi-valued; re-observation isn't a change).
    `event_at` (the source email's sent_at) becomes valid_from for temporal fidelity."""
    if not (src_id and dst_id):
        return
    exists = conn.execute(
        "SELECT 1 FROM edges WHERE program_id=? AND src_entity_id=? AND predicate=? "
        "AND dst_entity_id=? AND status='current'",
        (program_id, src_id, predicate, dst_id)).fetchone()
    if exists:
        return
    conn.execute(
        "INSERT INTO edges(program_id,src_entity_id,predicate,dst_entity_id,observation_id,"
        "source_document_id,confidence,props_json,valid_from,status) "
        "VALUES (?,?,?,?,?,?,?,?, COALESCE(?, datetime('now')), 'current')",
        (program_id, src_id, predicate, dst_id, observation_id, source_document_id,
         confidence, json.dumps(props) if props else None, event_at))


def sync_molecules(conn, program_id: str, program_eid: int | None = None) -> int:
    """Bridge the molecule identity system into the entity graph: one `molecule`
    entity per molecules row (carrying molecules.id + SMILES in attrs), its learned
    aliases, and an `in_program` membership edge. Assay results are joined live in
    profile() rather than exploded into facts."""
    n = 0
    for m in conn.execute(
            "SELECT id,name,smiles FROM molecules WHERE program_id=?", (program_id,)).fetchall():
        if not m["name"]:
            continue
        eid = resolve_entity(conn, program_id, "molecule", m["name"],
                             attrs={"molecule_id": m["id"], "smiles": m["smiles"]})
        for a in conn.execute(
                "SELECT alias FROM molecule_aliases WHERE molecule_id=?", (m["id"],)).fetchall():
            add_alias(conn, program_id, eid, "molecule", a["alias"])
        if program_eid:
            add_edge(conn, program_id, eid, "in_program", program_eid, confidence=1.0)
        n += 1
    return n


def _molecule_assay_summary(conn, molecule_id: int) -> list[dict]:
    """Compact assay knowledge for a molecule: grouped by (modality, target,
    standard_type, cell_line, units) with count + value range."""
    rows = conn.execute(
        "SELECT modality, target, standard_type, cell_line, units, COUNT(*) n, "
        "AVG(value) avg_value, MIN(value) min_value, MAX(value) max_value "
        "FROM assays WHERE molecule_id=? AND value IS NOT NULL "
        "GROUP BY modality, target, standard_type, cell_line, units "
        "ORDER BY modality, target LIMIT 80", (molecule_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["target"] = target_names.pretty_target(d.get("target"))
        out.append(d)
    return out


# --- read side -------------------------------------------------------------
def neighborhood_doc_ids(conn, program_id: str, entity_id: int) -> list[int]:
    """Source documents behind an entity's current edges (both directions).
    Used to seed graph-connected docs into retrieval."""
    rows = conn.execute(
        "SELECT DISTINCT source_document_id FROM edges "
        "WHERE program_id=? AND status='current' AND source_document_id IS NOT NULL "
        "AND (src_entity_id=? OR dst_entity_id=?)",
        (program_id, entity_id, entity_id)).fetchall()
    return [r["source_document_id"] for r in rows]


def resolve_mentions(conn, program_id: str, text: str) -> list[int]:
    """Entity ids whose display_name appears in `text` (cheap substring match on
    known entities). Used to anchor a question to its graph neighborhood."""
    if not text:
        return []
    t = text.lower()
    hits = []
    for r in conn.execute(
            "SELECT id, display_name FROM entities WHERE program_id=?",
            (program_id,)).fetchall():
        dn = (r["display_name"] or "").lower()
        if len(dn) >= 3 and dn in t:
            hits.append(r["id"])
    return hits


def profile(conn, program_id: str, entity_id: int) -> dict | None:
    """Everything known about one entity: attrs, aliases, edges (in/out, current +
    superseded), and the facts whose subject resolves to it."""
    e = conn.execute(
        "SELECT id,entity_type,canonical_key,display_name,attrs_json,created_at "
        "FROM entities WHERE id=? AND program_id=?", (entity_id, program_id)).fetchone()
    if not e:
        return None
    ent = dict(e)
    ent["attrs"] = json.loads(ent.pop("attrs_json") or "{}")
    aliases = conn.execute(
        "SELECT alias,alias_norm,confidence FROM entity_aliases "
        "WHERE program_id=? AND entity_id=?", (program_id, entity_id)).fetchall()
    out_edges = conn.execute(
        "SELECT e.predicate, e.dst_entity_id AS other_id, t.display_name AS other_name, "
        "t.entity_type AS other_type, e.status, e.valid_from, e.valid_to, "
        "e.source_document_id FROM edges e JOIN entities t ON t.id=e.dst_entity_id "
        "WHERE e.program_id=? AND e.src_entity_id=? ORDER BY e.status, e.predicate",
        (program_id, entity_id)).fetchall()
    in_edges = conn.execute(
        "SELECT e.predicate, e.src_entity_id AS other_id, s.display_name AS other_name, "
        "s.entity_type AS other_type, e.status, e.valid_from, e.valid_to, "
        "e.source_document_id FROM edges e JOIN entities s ON s.id=e.src_entity_id "
        "WHERE e.program_id=? AND e.dst_entity_id=? ORDER BY e.status, e.predicate",
        (program_id, entity_id)).fetchall()
    # facts keyed by this entity's display name (the subject_key convention)
    facts = conn.execute(
        "SELECT subject_type,predicate,value,status,valid_from,valid_to,observation_id "
        "FROM facts WHERE program_id=? AND subject_key=? ORDER BY status,predicate",
        (program_id, ent["display_name"])).fetchall()
    out = {
        "entity": ent,
        "aliases": [dict(a) for a in aliases],
        "edges_out": [dict(x) for x in out_edges],
        "edges_in": [dict(x) for x in in_edges],
        "facts": [dict(f) for f in facts],
    }
    # molecules carry their identity-system record + assay results
    if ent["entity_type"] == "molecule":
        mid = ent["attrs"].get("molecule_id")
        if mid:
            mol = conn.execute(
                "SELECT id,name,smiles,inchi_key,favorite FROM molecules WHERE id=?",
                (mid,)).fetchone()
            out["molecule"] = dict(mol) if mol else None
            out["assays"] = _molecule_assay_summary(conn, mid)
    return out


def list_entities(conn, program_id: str, entity_type: str | None = None,
                  q: str | None = None, limit: int = 200) -> list[dict]:
    sql = ("SELECT e.id, e.entity_type, e.display_name, "
           "(SELECT COUNT(*) FROM edges g WHERE g.status='current' AND "
           "(g.src_entity_id=e.id OR g.dst_entity_id=e.id)) AS edge_count "
           "FROM entities e WHERE e.program_id=?")
    args: list = [program_id]
    if entity_type:
        sql += " AND e.entity_type=?"
        args.append(entity_type)
    if q:
        sql += " AND LOWER(e.display_name) LIKE ?"
        args.append(f"%{q.lower()}%")
    sql += " ORDER BY edge_count DESC, e.display_name LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args).fetchall()]
