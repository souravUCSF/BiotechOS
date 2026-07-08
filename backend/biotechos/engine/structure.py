"""Structure + ADME layer for the Molecule Dashboard.

Two responsibilities:
  1. Predicted ADME — real RDKit physicochemical descriptors (instant, no service).
     These populate the dashboard's ADME cards today; Boltz free-ADME can augment
     them later.
  2. Boltz co-fold cache — a cache interface the dashboard reads. Folding is
     precomputed on molecule entry (later); until a structure exists, callers get
     None and the UI shows a "structure pending" state. `enqueue_fold` is the
     hook the ingest job will call once Boltz is authenticated.
"""
from __future__ import annotations

import json
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Draw, QED, rdMolDescriptors

from ..config import CACHE_DIR, DATA_DIR
from ..state import db

STRUCT_DIR = CACHE_DIR / "structures"
STRUCT_DIR.mkdir(parents=True, exist_ok=True)

# Real TGTA kinase-domain structure used as a reference placeholder until
# per-compound Boltz co-folds are computed (committed static asset).
PLACEHOLDER_PDB = DATA_DIR / "reference" / "placeholder_ref.pdb"
PLACEHOLDER_LABEL = "Reference: TGTA kinase domain (reference PDB)"


def predicted_adme(smiles: str) -> dict | None:
    """Real RDKit descriptors used as predicted ADME/physchem properties."""
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    tpsa = rdMolDescriptors.CalcTPSA(mol)
    hbd = rdMolDescriptors.CalcNumHBD(mol)
    hba = rdMolDescriptors.CalcNumHBA(mol)
    rotb = rdMolDescriptors.CalcNumRotatableBonds(mol)
    arom = rdMolDescriptors.CalcNumAromaticRings(mol)
    qed = QED.qed(mol)
    lipinski_violations = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    return {
        "MW": round(mw, 1),
        "cLogP": round(logp, 2),
        "TPSA": round(tpsa, 1),
        "HBD": hbd,
        "HBA": hba,
        "RotB": rotb,
        "AromaticRings": arom,
        "QED": round(qed, 3),
        "LipinskiViolations": lipinski_violations,
    }


def structure_svg(smiles: str, size: int = 320) -> str | None:
    """2D depiction as SVG for the molecule cards."""
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    d = Draw.rdMolDraw2D.MolDraw2DSVG(size, size)
    d.drawOptions().clearBackground = False
    Draw.rdMolDraw2D.PrepareAndDrawMolecule(d, mol)
    d.FinishDrawing()
    return d.GetDrawingText()


def compute_adme_for_program(program_id: str) -> int:
    """Populate molecules.adme_json for every molecule in a program. Returns count."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT id, smiles FROM molecules WHERE program_id=?", (program_id,)
    ).fetchall()
    n = 0
    with conn:
        for r in rows:
            adme = predicted_adme(r["smiles"])
            if adme:
                conn.execute(
                    "UPDATE molecules SET adme_json=? WHERE id=?",
                    (json.dumps(adme), r["id"]),
                )
                n += 1
    conn.close()
    return n


# --- Fold configuration (which protein / PDB to fold against) --------------
import urllib.request

from ..config import DEMO_PROGRAM_ID


def get_fold_config(program_id: str = DEMO_PROGRAM_ID) -> dict:
    conn = db.connect()
    r = conn.execute("SELECT * FROM fold_settings WHERE program_id=?", (program_id,)).fetchone()
    conn.close()
    if r is None:
        return {"program_id": program_id, "target_kind": "pdb", "target_value": "REF1",
                "pdb_id": "REF1", "constraints": ""}
    d = dict(r)
    # normalize: older rows only have pdb_id; treat that as a PDB target
    kind = d.get("target_kind") or "pdb"
    value = d.get("target_value") or d.get("pdb_id") or "REF1"
    d["target_kind"] = kind
    d["target_value"] = value
    d["pdb_id"] = value if kind == "pdb" else ""
    return d


def set_fold_config(program_id: str, target_kind: str, target_value: str,
                    constraints: str = "") -> dict:
    kind = (target_kind or "pdb").strip().lower()
    if kind not in ("pdb", "uniprot", "sequence"):
        kind = "pdb"
    value = (target_value or "").strip()
    if kind in ("pdb", "uniprot"):
        value = value.upper()
    else:  # sequence: strip whitespace/newlines, keep residues only
        value = "".join(value.split())
    pdb_id = value if kind == "pdb" else ""
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO fold_settings(program_id,pdb_id,target_kind,target_value,constraints,updated_at) "
            "VALUES (?,?,?,?,?,datetime('now')) ON CONFLICT(program_id) DO UPDATE SET "
            "pdb_id=excluded.pdb_id, target_kind=excluded.target_kind, "
            "target_value=excluded.target_value, constraints=excluded.constraints, "
            "updated_at=excluded.updated_at",
            (program_id, pdb_id, kind, value, constraints or ""),
        )
    conn.close()
    return get_fold_config(program_id)


def fetch_reference_pdb(pdb_id: str) -> Path | None:
    """Fetch a PDB structure from RCSB and cache it. REF1 ships bundled."""
    pdb_id = (pdb_id or "").strip().upper()
    if not pdb_id:
        return None
    if pdb_id == "REF1" and PLACEHOLDER_PDB.exists():
        return PLACEHOLDER_PDB
    cached = STRUCT_DIR / f"ref_{pdb_id}.pdb"
    if cached.exists():
        return cached
    try:
        req = urllib.request.Request(f"https://files.rcsb.org/download/{pdb_id}.pdb",
                                     headers={"User-Agent": "BiotechOS/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            cached.write_bytes(r.read())
        return cached
    except Exception as e:
        print(f"[structure] fetch {pdb_id} failed: {e}")
        return None


# --- Boltz co-fold cache (folding wired in later) --------------------------

def structure_path(molecule_id: int) -> Path:
    return STRUCT_DIR / f"mol_{molecule_id}.pdb"


def _cofold_label(molecule_id: int) -> str:
    """Label for a real Boltz co-fold: show the ligand ipTM if we have it."""
    import json
    conn = db.connect()
    row = conn.execute("SELECT boltz_json FROM molecules WHERE id=?", (molecule_id,)).fetchone()
    conn.close()
    if row and row["boltz_json"]:
        try:
            v = json.loads(row["boltz_json"]).get("ligand_iptm")
            if v is not None:
                return f"Boltz ligand ipTM {float(v):.2f}"
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return "Boltz co-fold"


def get_cached_structure(molecule_id: int, program_id: str = DEMO_PROGRAM_ID) -> tuple[str, bool, str, str] | None:
    """Return (text, is_placeholder, label, fmt) for a molecule's structure.

    Prefers a real per-compound Boltz co-fold (CIF, or legacy PDB); otherwise
    serves the program's configured reference PDB (default REF1) so the viewer
    always shows something real. Returns None only if nothing is available.
    """
    label = _cofold_label(molecule_id)
    p = structure_path(molecule_id)  # PDB (viewer-friendly) — preferred
    if p.exists():
        return p.read_text(), False, label, "pdb"
    cif = structure_path(molecule_id).with_suffix(".cif")
    if cif.exists():
        return cif.read_text(), False, label, "cif"
    cfg = get_fold_config(program_id)
    # only a PDB target has a structure to fetch now; UniProt/sequence targets
    # fold from sequence via Boltz (pending) — show the placeholder meanwhile.
    ref = fetch_reference_pdb(cfg.get("pdb_id") or "REF1") if cfg.get("target_kind") == "pdb" else None
    if ref and ref.exists():
        # forward-looking label; the real per-compound Boltz co-fold replaces this
        return ref.read_text(), True, "Predicted structure (co-fold pending)", "pdb"
    if PLACEHOLDER_PDB.exists():
        return PLACEHOLDER_PDB.read_text(), True, "Predicted structure (co-fold pending)", "pdb"
    return None


def store_cofold_cif(molecule_id: int, cif_path: str | Path) -> Path:
    """Convert a Boltz co-fold CIF to PDB (3Dmol parses PDB reliably; Boltz's
    minimal mmCIF lacks the symmetry records 3Dmol's CIF reader expects) and
    cache it as the molecule's structure. Returns the written PDB path."""
    import gemmi
    st = gemmi.read_structure(str(cif_path))
    st.setup_entities()
    dest = structure_path(molecule_id)
    dest.write_text(st.make_pdb_string())
    return dest


def enqueue_fold(molecule_id: int) -> None:
    """Hook the ingest job calls to precompute a Boltz co-fold. No-op until the
    boltz-api CLI is authenticated (see boltz-cli-setup). When wired, it will fold
    the configured protein (get_fold_config) + molecule SMILES with the given
    constraints, and write to structure_path(molecule_id)."""
    return None


if __name__ == "__main__":
    from ..config import DEMO_PROGRAM_ID
    print("ADME computed for", compute_adme_for_program(DEMO_PROGRAM_ID), "molecules")
