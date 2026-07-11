"""Compound registry — human confirmation of new molecule identities.

Unrecognized compound codes are created as PROVISIONAL molecules (molecules.status
='candidate') so their data attaches, but they are not trusted until a human resolves
them here: register as a new molecule (with SMILES or "structure pending"), merge into
an existing molecule (recording the code as a vendor-scoped alias), or dismiss.

Mirrors the suspected-decisions confirm/dismiss pattern (engine/decisions.py). Nothing
is auto-linked here — the queue only *suggests* matches for the human to accept.
"""
from __future__ import annotations

import json

from ..config import DEMO_PROGRAM_ID
from ..state import db
from . import identity


import re as _re


def _suffix_base(norm: str) -> str:
    """Normalized key with any trailing alpha suffix stripped: 'CL|2A' -> 'CL|2'."""
    return _re.sub(r"([A-Z])$", "", norm) if "|" in norm else norm


def _suggest(conn, program_id: str, cand: dict) -> list[dict]:
    """Merge suggestions for a candidate, high-precision only: same structure
    (InChIKey), or the same code differing only by a trailing suffix (CLO-00002 vs
    CLO-00002A). Digit differences are NOT suggested — they are different compounds."""
    cnorm = identity.normalize(cand["name"] or "")
    cbase = _suffix_base(cnorm)
    ik = cand["inchi_key"]
    out = []
    # compare against known (active) molecules AND other orphans, so duplicate
    # candidates (CL0-00002 ↔ CLO-00002a) surface as linkable too.
    for m in conn.execute(
            "SELECT id,name,smiles,inchi_key,status FROM molecules WHERE program_id=? "
            "AND status IN ('active','candidate') AND id<>?",
            (program_id, cand["id"])).fetchall():
        reason = None
        if ik and m["inchi_key"] and m["inchi_key"] == ik:
            reason = "same structure (InChIKey)"
        else:
            mnorm = identity.normalize(m["name"] or "")
            if mnorm and cbase and _suffix_base(mnorm) == cbase and mnorm != cnorm:
                reason = f"same code, different suffix ({m['name']})"
        if reason:
            out.append({"molecule_id": m["id"], "name": m["name"], "reason": reason})
    out.sort(key=lambda x: 0 if "structure" in x["reason"] else 1)
    return out[:6]


def candidates(program_id: str = DEMO_PROGRAM_ID, q: str | None = None) -> list[dict]:
    """Registry = new/unannotated molecules DETECTED from comms that need sorting.
    Excludes the ChEMBL seed set (internal_ref IS NOT NULL — those are the known
    portfolio, already annotated with SMILES). By default only shows structure-less
    orphans; a search `q` also surfaces detected molecules that already have a SMILES."""
    conn = db.connect()
    try:
        where = "program_id=? AND status='candidate' AND internal_ref IS NULL"
        args: list = [program_id]
        if q and q.strip():
            like = f"%{q.strip().upper()}%"
            where += (" AND (UPPER(name) LIKE ? OR id IN (SELECT molecule_id FROM "
                      "molecule_aliases WHERE program_id=? AND UPPER(alias) LIKE ?))")
            args += [like, program_id, like]
        else:
            where += " AND smiles IS NULL"   # orphans only; known-structure shown on search
        rows = conn.execute(
            f"SELECT id,name,smiles,inchi_key,created_at FROM molecules WHERE {where} "
            "ORDER BY created_at DESC", args).fetchall()
        out = []
        for r in rows:
            cand = dict(r)
            aliases = conn.execute(
                "SELECT alias,alias_type,vendor,confidence,verified,source_document_id "
                "FROM molecule_aliases WHERE program_id=? AND molecule_id=?",
                (program_id, r["id"])).fetchall()
            docs = conn.execute(
                "SELECT DISTINCT d.id,d.subject,d.email_from,d.sent_at FROM documents d "
                "JOIN molecule_aliases a ON a.source_document_id=d.id WHERE a.molecule_id=? LIMIT 8",
                (r["id"],)).fetchall()
            n_assays = conn.execute("SELECT COUNT(*) n FROM assays WHERE molecule_id=?",
                                    (r["id"],)).fetchone()["n"]
            cand["structure_status"] = "known" if r["smiles"] else "pending"
            cand["has_structure"] = bool(r["smiles"])
            cand["aliases"] = [dict(a) for a in aliases]
            cand["vendors"] = sorted({a["vendor"] for a in aliases if a["vendor"]})
            cand["documents"] = [dict(d) for d in docs]
            cand["assay_count"] = n_assays
            cand["suggestions"] = _suggest(conn, program_id, dict(r))
            # orphan triage: has a likely existing match → 'needs_link'; else 'needs_new'
            cand["bucket"] = "needs_link" if cand["suggestions"] else "needs_new"
            out.append(cand)
        # surface the easy wins (likely links) first, then genuinely-new molecules
        out.sort(key=lambda c: (0 if c["bucket"] == "needs_link" else 1, c["name"]))
        return out
    finally:
        conn.close()


def remaining_count(program_id: str = DEMO_PROGRAM_ID) -> int:
    """How many comms-detected molecules still need registration (any structure state)."""
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT COUNT(*) n FROM molecules WHERE program_id=? AND status='candidate' "
            "AND internal_ref IS NULL", (program_id,)).fetchone()["n"]
    finally:
        conn.close()


_SMILES_ALPHABET = _re.compile(r"^[A-Za-z0-9@+\-\[\]()=#/\\%.]+$")


def _looks_like_smiles(s: str) -> bool:
    """Heuristic: a single token with structural punctuation (an attempted SMILES),
    as opposed to a text descriptor/name (which usually has spaces or no such chars)."""
    s = s.strip()
    if " " in s:
        return False
    return bool(_re.search(r"[=#\[\]()/\\%]", s)) and bool(_SMILES_ALPHABET.match(s))


_AA = set("ACDEFGHIKLMNPQRSTVWY")
_NT = set("ACGTU")


def _looks_like_sequence(s: str) -> str | None:
    """Normalized biologic sequence if `s` is one (>=10 residues, all AA or all NA)."""
    t = _re.sub(r"\s+", "", s).upper()
    if len(t) < 10 or not t.isalpha():
        return None
    letters = set(t)
    return t if (letters <= _AA or letters <= _NT) else None


def search_molecules(program_id: str, q: str, limit: int = 8) -> list[dict]:
    """Search registered/active + candidate molecules by name or alias (for the merge
    autocomplete). Returns id, name, and whether it has a structure."""
    if not q or not q.strip():
        return []
    like = f"%{q.strip().upper()}%"
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT id, name, smiles IS NOT NULL AS has_structure, status FROM molecules "
            "WHERE program_id=? AND status IN ('active','candidate') AND ("
            "  UPPER(name) LIKE ? OR id IN (SELECT molecule_id FROM molecule_aliases "
            "  WHERE program_id=? AND UPPER(alias) LIKE ?)) "
            "ORDER BY (status='active') DESC, name LIMIT ?",
            (program_id, like, program_id, like, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def confirm_new(program_id: str, molecule_id: int, *, value: str | None = None) -> dict:
    """Register a candidate as a real molecule. `value` must be a VALID SMILES, a
    biologic SEQUENCE, or a unique text DESCRIPTOR — and must be UNIQUE. If it already
    identifies another molecule, this does NOT register; it returns that molecule as a
    `duplicate` so the UI can guide a merge instead."""
    v = (value or "").strip()
    if not v:
        raise ValueError("A valid SMILES, sequence, or descriptor is required.")
    conn = db.connect()
    try:
        cand = conn.execute("SELECT id FROM molecules WHERE id=? AND program_id=? AND status='candidate'",
                            (molecule_id, program_id)).fetchone()
        if not cand:
            raise ValueError("candidate not found")
        ik = identity.inchikey(v)
        seq = _looks_like_sequence(v)
        smiles = sequence = descriptor = None
        if ik:                                   # valid SMILES → dedup on structure
            smiles = v
            dup = conn.execute("SELECT id,name FROM molecules WHERE program_id=? AND inchi_key=? "
                               "AND id<>? AND status='active'", (program_id, ik, molecule_id)).fetchone()
        elif _looks_like_smiles(v):
            raise ValueError("that looks like a SMILES but is not valid — fix it, or enter a sequence/descriptor")
        elif seq:                                # biologic sequence → dedup on sequence
            sequence = seq
            dup = conn.execute("SELECT id,name FROM molecules WHERE program_id=? AND UPPER(sequence)=? "
                               "AND id<>? AND status='active'", (program_id, seq, molecule_id)).fetchone()
        else:                                    # text descriptor → dedup on descriptor
            descriptor = v
            dup = conn.execute("SELECT id,name FROM molecules WHERE program_id=? AND UPPER(descriptor)=? "
                               "AND id<>? AND status='active'", (program_id, v.upper(), molecule_id)).fetchone()
        if dup:                                  # not unique → guide a merge, don't register
            return {"duplicate": {"molecule_id": dup["id"], "name": dup["name"]},
                    "message": f"This appears to be the same as {dup['name']}."}
        with conn:
            conn.execute(
                "UPDATE molecules SET status='active', smiles=?, inchi_key=?, sequence=?, descriptor=? "
                "WHERE id=? AND program_id=?", (smiles, ik, sequence, descriptor, molecule_id, program_id))
        kind = "smiles" if smiles else "sequence" if sequence else "descriptor"
        return {"molecule_id": molecule_id, "status": "active", "identity_kind": kind}
    finally:
        conn.close()


def merge(program_id: str, candidate_id: int, target_id: int, *, vendor: str | None = None) -> dict:
    """Merge a candidate into an existing molecule: reassign its assays + aliases,
    record its code as a (vendor-scoped) alias of the target, and mark it merged."""
    conn = db.connect()
    try:
        cand = conn.execute("SELECT name FROM molecules WHERE id=? AND program_id=?",
                            (candidate_id, program_id)).fetchone()
        tgt = conn.execute("SELECT id FROM molecules WHERE id=? AND program_id=?",
                           (target_id, program_id)).fetchone()
        if not cand or not tgt:
            raise ValueError("candidate or target not found")
        with conn:
            conn.execute("UPDATE assays SET molecule_id=? WHERE molecule_id=?",
                         (target_id, candidate_id))
            # move aliases (skip ones that would collide on the target), drop leftovers
            conn.execute("UPDATE OR IGNORE molecule_aliases SET molecule_id=? WHERE molecule_id=?",
                         (target_id, candidate_id))
            conn.execute("DELETE FROM molecule_aliases WHERE molecule_id=?", (candidate_id,))
            conn.execute("UPDATE molecules SET status='dismissed', merged_into=? WHERE id=?",
                         (target_id, candidate_id))
        # record the candidate's code as a vendor-tagged alias of the target
        identity.add_alias(program_id, target_id, cand["name"], vendor=vendor,
                           confidence=1.0, verified=True)
        return {"merged": candidate_id, "into": target_id}
    finally:
        conn.close()


def dismiss(program_id: str, molecule_id: int) -> dict:
    """Dismiss a candidate as not-a-molecule (removes its provisional aliases/assays)."""
    conn = db.connect()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE molecules SET status='dismissed' WHERE id=? AND program_id=? "
                "AND status='candidate'", (molecule_id, program_id))
            if cur.rowcount:
                conn.execute("DELETE FROM molecule_aliases WHERE molecule_id=?", (molecule_id,))
                conn.execute("DELETE FROM assays WHERE molecule_id=?", (molecule_id,))
        if cur.rowcount == 0:
            raise ValueError("candidate not found")
        return {"molecule_id": molecule_id, "status": "dismissed"}
    finally:
        conn.close()


# explicit assay-RESULT signals (keywords, not bare numbers which appear everywhere in threads)
_DATA_KW = _re.compile(
    r"ic50|ec50|gi50|kinact|k[_ ]?off|\btau\b|\bpapp\b|recovery|residence time|"
    r"% ?inhibition|\bkd\b|\bki\b|deconvolution|intact ?ms|adp-?glo|efflux", _re.I)


def _snippet(text: str, needle: str, radius: int = 130) -> str:
    i = (text or "").lower().find(needle.lower())
    if i < 0:
        return ""
    s = max(0, i - radius)
    return ("…" if s else "") + text[s:i + len(needle) + radius].strip().replace("\n", " ") + "…"


def detail(program_id: str, molecule_id: int) -> dict:
    """Everything behind a candidate: its assay rows AND the actual correspondence it
    came from — found by searching the corpus for the molecule's aliases (robust to
    re-ingest, which orphans stored source_document_ids)."""
    conn = db.connect()
    try:
        mol = conn.execute("SELECT id,name,smiles,status FROM molecules WHERE id=? AND program_id=?",
                           (molecule_id, program_id)).fetchone()
        if not mol:
            raise ValueError("molecule not found")
        aliases = conn.execute(
            "SELECT alias,alias_type,vendor FROM molecule_aliases WHERE molecule_id=?",
            (molecule_id,)).fetchall()
        assays = conn.execute(
            "SELECT modality,target,standard_type,value,units,system_type,system,species,"
            "conditions,source,assay_desc FROM assays WHERE molecule_id=? "
            "ORDER BY modality,target,standard_type", (molecule_id,)).fetchall()
        # correspondence: current documents mentioning any real alias (skip the surrogate name)
        terms = [a["alias"] for a in aliases] + ([mol["name"]] if not mol["name"].startswith("BTX-") else [])
        docs, seen = [], set()
        for term in terms:
            if not term or len(term) < 4:
                continue
            for d in conn.execute(
                    "SELECT id,subject,email_from,sent_at,doc_type,raw_text FROM documents "
                    "WHERE program_id=? AND raw_text LIKE ? ORDER BY sent_at LIMIT 12",
                    (program_id, f"%{term}%")).fetchall():
                if d["id"] in seen:
                    continue
                seen.add(d["id"])
                body = d["raw_text"] or ""
                # "with data" = a data-category email, or explicit assay results in the
                # NEWEST message (not the quoted thread history, which bleeds keywords).
                from .triage import latest_message
                latest = latest_message(body)
                has_data = (_doc_category(conn, d["id"], d["doc_type"]) == "data"
                            or bool(_DATA_KW.search(latest)))
                docs.append({"id": d["id"], "subject": d["subject"], "email_from": d["email_from"],
                             "sent_at": d["sent_at"], "doc_type": d["doc_type"], "has_data": has_data,
                             "matched": term, "snippet": _snippet(body, term)})
        docs.sort(key=lambda x: (not x["has_data"], x["sent_at"] or ""))
        return {"molecule": dict(mol), "aliases": [dict(a) for a in aliases],
                "assays": [dict(a) for a in assays], "documents": docs}
    finally:
        conn.close()


def set_canonical(program_id: str, molecule_id: int, alias: str) -> dict:
    """Promote one of a molecule's aliases to be its canonical name, rewriting every
    name-keyed reference in the system (facts, observations, decisions, quote lines,
    the molecule graph entity). The old name is preserved as an alias. Big operation —
    the caller confirms before invoking."""
    from . import graph
    conn = db.connect()
    try:
        mol = conn.execute("SELECT name FROM molecules WHERE id=? AND program_id=?",
                           (molecule_id, program_id)).fetchone()
        if not mol:
            raise ValueError("molecule not found")
        old = mol["name"]
        if alias == old:
            return {"canonical": old, "unchanged": True}
        belongs = conn.execute("SELECT 1 FROM molecule_aliases WHERE molecule_id=? AND alias=?",
                              (molecule_id, alias)).fetchone()
        if not belongs:
            raise ValueError("that alias is not registered on this molecule")
        with conn:
            conn.execute("UPDATE molecules SET name=? WHERE id=?", (alias, molecule_id))
            # preserve the old name as an alias so nothing is lost
            conn.execute(
                "INSERT OR IGNORE INTO molecule_aliases(program_id,molecule_id,alias,alias_norm,"
                "alias_type,verified) VALUES (?,?,?,?,?,1)",
                (program_id, molecule_id, old, identity.normalize(old), identity._classify_alias(old)))
            # rewrite every name-keyed reference old → new
            for tbl in ("facts", "observations", "decisions"):
                conn.execute(f"UPDATE {tbl} SET subject_key=? WHERE program_id=? "
                             "AND subject_type='molecule' AND subject_key=?", (alias, program_id, old))
            conn.execute("UPDATE quote_lines SET compound=? WHERE program_id=? AND compound=?",
                         (alias, program_id, old))
            conn.execute(
                "UPDATE OR IGNORE entities SET display_name=?, canonical_key=? WHERE program_id=? "
                "AND entity_type='molecule' AND display_name=?",
                (alias, graph.normalize_key("molecule", alias), program_id, old))
        return {"canonical": alias, "was": old}
    finally:
        conn.close()


def alias_map(program_id: str, molecule_id: int) -> dict:
    """Per-vendor alias map for a molecule (what each CRO calls it)."""
    p = identity.passport(program_id, molecule_id)
    by_vendor: dict[str, list[dict]] = {}
    for a in p["aliases"]:
        by_vendor.setdefault(a.get("vendor") or "(internal / unscoped)", []).append(a)
    return {"molecule": p["molecule"], "by_vendor": by_vendor, "documents": p["documents"]}


# doc_type → 5-way classifier category. Handles both legacy doc_types (contract,
# cro_data, …) and cases where doc_type already holds a 5-way category value.
_DT2CAT = {"quote": "quote", "invoice": "invoice", "contract": "legal", "cro_data": "data",
           "data": "data", "legal": "legal", "other": "other"}
_MOLECULE_CATEGORIES = {"quote", "invoice", "legal", "data"}


def _doc_category(conn, doc_id: int | None, doc_type: str | None) -> str:
    """Effective 5-way category for a document — a human reclassification stored in
    triage_json wins; otherwise map the doc_type."""
    if doc_id is not None:
        r = conn.execute("SELECT triage_json FROM documents WHERE id=?", (doc_id,)).fetchone()
        if r and r["triage_json"]:
            try:
                cat = json.loads(r["triage_json"]).get("category")
                if cat in ("quote", "invoice", "legal", "data", "other"):
                    return cat
            except (TypeError, ValueError):
                pass
    return _DT2CAT.get(doc_type or "", "other")


def rebuild_from_categories(program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Molecules may only be registered from emails classified quote/invoice/legal/data.
    Dismiss comms-detected candidates whose ONLY provenance is 'other' emails (found by
    searching the corpus for the molecule's aliases). Keeps anything with ≥1 allowed
    source. Reclassifying an 'other' email → allowed will re-admit it on next detection."""
    conn = db.connect()
    try:
        cands = conn.execute(
            "SELECT id,name FROM molecules WHERE program_id=? AND status='candidate' "
            "AND internal_ref IS NULL", (program_id,)).fetchall()
        removed, kept = [], 0
        for m in cands:
            aliases = [r["alias"] for r in conn.execute(
                "SELECT alias FROM molecule_aliases WHERE molecule_id=?", (m["id"],)).fetchall()]
            terms = [a for a in aliases if len(a) >= 4]
            if not terms and not m["name"].startswith("BTX-"):
                terms = [m["name"]]
            ok = False
            for t in terms:
                for d in conn.execute(
                        "SELECT id,doc_type FROM documents WHERE program_id=? AND raw_text LIKE ? LIMIT 25",
                        (program_id, f"%{t}%")).fetchall():
                    if _doc_category(conn, d["id"], d["doc_type"]) in _MOLECULE_CATEGORIES:
                        ok = True
                        break
                if ok:
                    break
            if ok:
                kept += 1
            else:
                removed.append(m["name"])
        with conn:
            for name in removed:
                mid = conn.execute("SELECT id FROM molecules WHERE program_id=? AND name=?",
                                   (program_id, name)).fetchone()["id"]
                conn.execute("DELETE FROM molecule_aliases WHERE molecule_id=?", (mid,))
                conn.execute("DELETE FROM assays WHERE molecule_id=?", (mid,))
                conn.execute("UPDATE molecules SET status='dismissed' WHERE id=?", (mid,))
        return {"kept": kept, "removed": len(removed), "removed_names": removed[:40]}
    finally:
        conn.close()


_PROTEIN_MODALITIES = ("biochemical_ic50", "intact_ms", "kinetics", "selectivity", "nanobret", "dsf")


def backfill_system(program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Derive the typed biological `system` for existing assay rows from the old
    target/cell_line encoding: cellular → cell_line system; biochemical/binding →
    protein system (=target). ADME/tox/xenograft/pk left NULL (need re-extraction)."""
    conn = db.connect()
    try:
        has_cell_line = "cell_line" in [r[1] for r in conn.execute("PRAGMA table_info(assays)").fetchall()]
        with conn:
            cell = 0
            if has_cell_line:   # legacy column, dropped after this backfill has run once
                cell = conn.execute(
                    "UPDATE assays SET system_type='cell_line', system=cell_line "
                    "WHERE program_id=? AND system IS NULL AND cell_line IS NOT NULL", (program_id,)).rowcount
            ph = ",".join("?" * len(_PROTEIN_MODALITIES))
            prot = conn.execute(
                f"UPDATE assays SET system_type='protein', system=target "
                f"WHERE program_id=? AND system IS NULL AND target IS NOT NULL "
                f"AND modality IN ({ph})", (program_id, *_PROTEIN_MODALITIES)).rowcount
        return {"cell_line_rows": cell, "protein_rows": prot}
    finally:
        conn.close()


def flag_unconfirmed(program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Reconcile the registry: (1) ChEMBL SEED molecules (internal_ref set) are never
    registry candidates — restore any to 'active'; (2) move comms-DETECTED, structure-
    less molecules (internal_ref IS NULL, smiles IS NULL) into the candidate queue."""
    conn = db.connect()
    try:
        with conn:
            restored = conn.execute(
                "UPDATE molecules SET status='active' WHERE program_id=? AND status='candidate' "
                "AND internal_ref IS NOT NULL", (program_id,)).rowcount
            flagged = conn.execute(
                "UPDATE molecules SET status='candidate' WHERE program_id=? AND status='active' "
                "AND internal_ref IS NULL AND smiles IS NULL", (program_id,)).rowcount
        return {"flagged": flagged, "restored_seed": restored}
    finally:
        conn.close()
