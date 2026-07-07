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


# --- Boltz co-fold cache (folding wired in later) --------------------------

def structure_path(molecule_id: int) -> Path:
    return STRUCT_DIR / f"mol_{molecule_id}.pdb"


def get_cached_structure(molecule_id: int) -> tuple[str, bool] | None:
    """Return (pdb_text, is_placeholder) for a molecule's structure.

    Prefers a real per-compound Boltz co-fold; falls back to the TGTA reference
    structure (REF1) so the viewer always has something real to show. Returns
    None only if even the placeholder is missing.
    """
    p = structure_path(molecule_id)
    if p.exists():
        return p.read_text(), False
    if PLACEHOLDER_PDB.exists():
        return PLACEHOLDER_PDB.read_text(), True
    return None


def enqueue_fold(molecule_id: int) -> None:
    """Hook the ingest job calls to precompute a Boltz co-fold. No-op until the
    boltz-api CLI is authenticated (see boltz-cli-setup)."""
    # Deferred: run boltz-structure-and-binding for (TGTA seq + molecule SMILES),
    # write result to structure_path(molecule_id), update molecules.structure_cache_ref.
    return None


if __name__ == "__main__":
    from ..config import DEMO_PROGRAM_ID
    print("ADME computed for", compute_adme_for_program(DEMO_PROGRAM_ID), "molecules")
