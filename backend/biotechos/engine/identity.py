"""Molecule identity & alias resolution — the join key across the whole system.

One molecule keeps a single canonical `molecules.id`; every name it goes by
(internal code, request id, CRO project code, vendor code, common name) is an
alias resolving to that id. Aliases are learned only from the ingested corpus
(inline declarations) + structure (InChIKey) + human confirmations — never from
an external mapping sheet.
"""
from __future__ import annotations

import re

from ..config import DEMO_PROGRAM_ID
from ..state import db

# compound-code-ish token: 2+ letters, optional sep, 2+ digits, optional suffix,
# or a multi-segment CRO project code (PH-PGMA-L2-2026-08B-7-0).
_CODE_RE = re.compile(r"\b([A-Z]{2,}[-_ ]?\d{2,}[A-Za-z]?|[A-Z]{2,}(?:-[A-Za-z0-9]+){2,})\b")
# prefix + (optional dash) + zero-padded number (+ optional alpha suffix)
_SIMPLE_RE = re.compile(r"^([A-Z]+)-?0*(\d+)([A-Z]?)$")


def normalize(token: str) -> str:
    """Canonical key that collapses common compound-code drift/misspellings:
    dash/underscore/space, zero-padding (00 vs 000), and letter-O vs zero (a
    frequent OCR/typo confusion, e.g. CL0-00002 vs CLO-00002). All of
    CLO-00003 / CL0-00003 / CLO00003 / clo_3 -> 'CL|3'; BTX-1050 -> 'BTX|1050'.
    Multi-segment CRO project codes collapse to a stripped exact key (no fuzzy split)."""
    t = re.sub(r"[\s_\-]+", "", (token or "").upper())
    t = t.replace("O", "0")   # unify letter-O and zero
    m = re.match(r"^([A-Z]+)0*(\d+)([A-Z]?)$", t)
    if m:
        return f"{m.group(1)}|{int(m.group(2))}{m.group(3)}"
    return t


def inchikey(smiles: str | None) -> str | None:
    if not smiles:
        return None
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles(smiles)
        return Chem.MolToInchiKey(m) if m else None
    except Exception:
        return None


def _classify_alias(token: str) -> str:
    t = token.upper()
    if "RQ" in t and re.search(r"RQ[-_]?\d", t):
        return "request_id"
    if re.match(r"^[A-Z]{2,}(-[A-Za-z0-9]+){2,}$", t.replace("_", "-")):
        return "cro_project_code"
    if re.match(r"^(BTX|CLO)", t):
        return "internal"
    return "vendor_code"


def add_alias(program_id: str, molecule_id: int, alias: str, *, alias_type: str | None = None,
              vendor: str | None = None, source_document_id: int | None = None,
              confidence: float = 1.0, verified: bool = False, conn=None) -> None:
    own = conn is None
    conn = conn or db.connect()
    norm = normalize(alias)
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO molecule_aliases(program_id,molecule_id,alias,alias_norm,"
                "alias_type,vendor,source_document_id,confidence,verified) VALUES (?,?,?,?,?,?,?,?,?)",
                (program_id, molecule_id, alias, norm, alias_type or _classify_alias(alias),
                 vendor, source_document_id, confidence, int(verified)),
            )
    finally:
        if own:
            conn.close()


def _lookup_norm(conn, program_id: str, norm: str) -> int | None:
    r = conn.execute(
        "SELECT molecule_id FROM molecule_aliases WHERE program_id=? AND alias_norm=? "
        "ORDER BY verified DESC, confidence DESC LIMIT 1", (program_id, norm)).fetchone()
    if r:
        return r["molecule_id"]
    # canonical molecule names are implicit aliases too (e.g. BTX-1050)
    r = conn.execute(
        "SELECT id FROM molecules WHERE program_id=? AND UPPER(REPLACE(REPLACE(name,'-',''),'_',''))=? ",
        (program_id, norm.replace("|", ""))).fetchone()
    return r["id"] if r else None


def resolve_molecule(program_id: str, token: str, smiles: str | None = None, *,
                     source_document_id: int | None = None, create: bool = False,
                     conn=None) -> dict:
    """Resolve a molecule token to a canonical id.
    Returns {molecule_id, status, ...}. status ∈ resolved | inchikey_merge |
    created | merge_candidate | unresolved."""
    own = conn is None
    conn = conn or db.connect()
    try:
        norm = normalize(token)
        # 1) exact normalized alias / canonical name
        mid = _lookup_norm(conn, program_id, norm)
        if mid:
            return {"molecule_id": mid, "status": "resolved", "norm": norm}
        # 2) structure identity (InChIKey)
        ik = inchikey(smiles)
        if ik:
            r = conn.execute(
                "SELECT id FROM molecules WHERE program_id=? AND inchi_key=?",
                (program_id, ik)).fetchone()
            if r:
                add_alias(program_id, r["id"], token, source_document_id=source_document_id,
                          confidence=1.0, verified=True, conn=conn)
                return {"molecule_id": r["id"], "status": "inchikey_merge", "norm": norm}
        # 3) create a new molecule (used by anonymized import / provisional)
        if create:
            with conn:
                cur = conn.execute(
                    "INSERT INTO molecules(program_id,name,smiles,inchi_key,held_out) "
                    "VALUES (?,?,?,?,0)", (program_id, token, smiles, ik))
                mid = cur.lastrowid
            add_alias(program_id, mid, token, source_document_id=source_document_id,
                      confidence=1.0, verified=True, conn=conn)
            return {"molecule_id": mid, "status": "created", "norm": norm}
        return {"molecule_id": None, "status": "unresolved", "norm": norm}
    finally:
        if own:
            conn.close()


def learn_inline_aliases(program_id: str, text: str, *, source_document_id: int | None = None,
                         conn=None) -> list[tuple[str, str]]:
    """Find inline alias declarations in free text and link them.
    Patterns: 'A (B)', 'A = B', 'A / B', 'A aka B' where both are compound codes and
    at least one already resolves. Returns list of (linked_alias, canonical_token)."""
    own = conn is None
    conn = conn or db.connect()
    linked: list[tuple[str, str]] = []
    try:
        pairs = re.findall(
            r"([A-Za-z0-9][\w-]+)\s*(?:\(|=|/|\baka\b|,)\s*([A-Za-z0-9][\w-]+)", text or "")
        for a, b in pairs:
            if not (_CODE_RE.search(a.upper()) and _CODE_RE.search(b.upper())):
                continue
            ra = resolve_molecule(program_id, a, conn=conn)
            rb = resolve_molecule(program_id, b, conn=conn)
            if ra["molecule_id"] and not rb["molecule_id"]:
                add_alias(program_id, ra["molecule_id"], b, source_document_id=source_document_id,
                          confidence=0.9, conn=conn)
                linked.append((b, a))
            elif rb["molecule_id"] and not ra["molecule_id"]:
                add_alias(program_id, rb["molecule_id"], a, source_document_id=source_document_id,
                          confidence=0.9, conn=conn)
                linked.append((a, b))
        return linked
    finally:
        if own:
            conn.close()


def passport(program_id: str, molecule_id: int) -> dict:
    """Everything known about a molecule across its identities."""
    conn = db.connect()
    try:
        mol = conn.execute("SELECT id,name,smiles,inchi_key FROM molecules WHERE id=?",
                           (molecule_id,)).fetchone()
        aliases = conn.execute(
            "SELECT alias,alias_type,vendor,confidence,verified FROM molecule_aliases "
            "WHERE program_id=? AND molecule_id=?", (program_id, molecule_id)).fetchall()
        docs = conn.execute(
            "SELECT DISTINCT d.id,d.subject,d.doc_type,d.sent_at FROM documents d "
            "JOIN molecule_aliases a ON a.source_document_id=d.id WHERE a.molecule_id=?",
            (molecule_id,)).fetchall()
        return {
            "molecule": dict(mol) if mol else None,
            "aliases": [dict(a) for a in aliases],
            "documents": [dict(d) for d in docs],
        }
    finally:
        conn.close()
