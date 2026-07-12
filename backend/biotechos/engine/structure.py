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

from ..config import CACHE_DIR, DATA_DIR, DEMO_PROGRAM_ID
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


def _run_cofold_job(molecule_id: int, program_id: str) -> None:
    """Background worker: Boltz co-fold the molecule's SMILES against the program's
    folding-target sequence, then cache the structure + boltz_json."""
    from . import boltz
    try:
        conn = db.connect()
        m = conn.execute("SELECT smiles FROM molecules WHERE id=? AND program_id=?",
                         (molecule_id, program_id)).fetchone()
        conn.close()
        smiles = m["smiles"] if m else None
        cfg = get_fold_config(program_id)
        seq = cfg.get("target_value") if cfg.get("target_kind") == "sequence" else None
        if not (smiles and seq):
            return
        res = boltz.cofold(seq, smiles, name=f"cofold_{program_id}_{molecule_id}")
        if res.get("cif_path"):
            store_cofold_cif(molecule_id, res["cif_path"])
        conn = db.connect()
        with conn:
            conn.execute("UPDATE molecules SET boltz_json=? WHERE id=?",
                         (json.dumps({"ligand_iptm": res.get("ligand_iptm"),
                                      "affinity": res.get("affinity"), **(res.get("scores") or {})}),
                          molecule_id))
        conn.close()
    except Exception as e:
        print(f"[boltz cofold] molecule {molecule_id} failed: {e}")


def enqueue_fold(molecule_id: int, kind: str = "cofold", program_id: str = DEMO_PROGRAM_ID) -> None:
    """Precompute a Boltz structure for a molecule (fire-and-forget background job so the
    request returns immediately). `cofold` = target sequence + molecule SMILES ligand →
    co-fold + Boltz scores. Requires BOLTZ_API_KEY; no-op (skipped) otherwise."""
    from . import boltz
    if kind != "cofold" or not boltz.available():
        return
    import threading
    threading.Thread(target=_run_cofold_job, args=(molecule_id, program_id), daemon=True).start()


def on_structure_detected(molecule_id: int, program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Called whenever a compound's structure is first known. SMILES → compute RDKit
    ADME now (stored to adme_json) + enqueue a Boltz CO-FOLD with the folding target.
    Sequence-only → enqueue a Boltz sequence FOLD. Boltz itself is deferred until
    boltz-api is authenticated; the RDKit ADME runs immediately."""
    conn = db.connect()
    try:
        r = conn.execute("SELECT smiles, sequence FROM molecules WHERE id=? AND program_id=?",
                         (molecule_id, program_id)).fetchone()
        if not r:
            return {"molecule_id": molecule_id, "action": "none"}
        smiles = r["smiles"]
        sequence = r["sequence"] if "sequence" in r.keys() else None
        if smiles:
            adme = predicted_adme(smiles)
            if adme:
                with conn:
                    conn.execute("UPDATE molecules SET adme_json=? WHERE id=?",
                                 (json.dumps(adme), molecule_id))
            enqueue_fold(molecule_id, kind="cofold", program_id=program_id)
            return {"molecule_id": molecule_id, "action": "cofold", "adme": bool(adme)}
        if sequence:
            enqueue_fold(molecule_id, kind="fold", program_id=program_id)
            return {"molecule_id": molecule_id, "action": "fold"}
        return {"molecule_id": molecule_id, "action": "none"}
    finally:
        conn.close()


# ---- fold backlog / reconciler -------------------------------------------
# Co-folding is event-driven (on_structure_detected). Molecules that acquired a
# SMILES/sequence before Boltz was authenticated never got folded and are never
# revisited. These helpers find that backlog and (on demand or on a timer) fold it.

def find_fold_backlog(program_id: str | None = None) -> list[dict]:
    """Active molecules with a SMILES or sequence but no stored Boltz co-fold."""
    conn = db.connect()
    try:
        q = ("SELECT id, program_id, name, smiles, sequence FROM molecules "
             "WHERE status='active' AND boltz_json IS NULL "
             "AND (smiles IS NOT NULL OR sequence IS NOT NULL)")
        args: tuple = ()
        if program_id:
            q += " AND program_id=?"
            args = (program_id,)
        return [dict(r) for r in conn.execute(q, args).fetchall()]
    finally:
        conn.close()


def fold_backlog_summary(program_id: str | None = None) -> dict:
    """Count + live per-co-fold cost estimate for the un-folded backlog."""
    from . import boltz
    rows = find_fold_backlog(program_id)
    n = len(rows)
    per_usd = None
    total_usd = None
    if n and boltz.available():
        sample = next((r for r in rows if r.get("smiles")), None)
        if sample:
            try:
                cfg = get_fold_config(sample["program_id"])
                seq = cfg.get("target_value") if cfg.get("target_kind") == "sequence" else None
                if seq:
                    est = boltz.estimate_cofold_cost(seq, sample["smiles"])
                    per_usd = est.get("usd")
                    if per_usd is not None:
                        total_usd = f"{float(per_usd) * n:.4f}"
            except Exception as e:
                print(f"[fold backlog] cost estimate failed: {e}")
    return {"count": n, "per_cofold_usd": per_usd, "total_usd": total_usd,
            "boltz_available": boltz.available(), "molecule_ids": [r["id"] for r in rows]}


_BACKLOG_RUNNING = False
_BACKLOG_DELAY_S = 8  # spacing between co-folds so we don't trip Boltz rate limits


def run_fold_backlog(program_id: str | None = None, limit: int | None = None) -> dict:
    """Co-fold the un-folded backlog in ONE serialized background worker, spaced out to
    respect Boltz rate limits (firing all N at once trips 429). Idempotent: only one
    worker at a time; each molecule is re-checked (skipped if it got folded meanwhile)."""
    global _BACKLOG_RUNNING
    from . import boltz
    if not boltz.available():
        return {"enqueued": 0, "reason": "boltz_unavailable"}
    if _BACKLOG_RUNNING:
        return {"enqueued": 0, "reason": "already_running"}
    rows = find_fold_backlog(program_id)
    if limit:
        rows = rows[:limit]
    if not rows:
        return {"enqueued": 0, "reason": "backlog_empty"}
    _BACKLOG_RUNNING = True
    import threading, time

    def _worker():
        global _BACKLOG_RUNNING
        try:
            for r in rows:
                # skip if folded since the scan (e.g. by the event trigger)
                conn = db.connect()
                still = conn.execute("SELECT boltz_json IS NULL FROM molecules WHERE id=?",
                                     (r["id"],)).fetchone()
                conn.close()
                if not still or not still[0]:
                    continue
                _run_cofold_job(r["id"], r["program_id"])
                time.sleep(_BACKLOG_DELAY_S)
        finally:
            _BACKLOG_RUNNING = False

    threading.Thread(target=_worker, daemon=True).start()
    return {"enqueued": len(rows), "molecule_ids": [r["id"] for r in rows]}


_SWEEP_STARTED = False


def start_backlog_sweep(interval_seconds: int = 1800) -> None:
    """Background reconciler: periodically fold any molecule that slipped through the
    event-driven trigger. Idempotent — only one sweeper per process."""
    global _SWEEP_STARTED
    from . import boltz
    if _SWEEP_STARTED or not boltz.available():
        return
    _SWEEP_STARTED = True
    import threading, time

    def _loop():
        while True:
            time.sleep(interval_seconds)  # grace period before the first pass (button is primary)
            try:
                res = run_fold_backlog()
                if res.get("enqueued"):
                    print(f"[fold sweep] enqueued {res['enqueued']} co-folds")
            except Exception as e:
                print(f"[fold sweep] failed: {e}")

    threading.Thread(target=_loop, daemon=True).start()


if __name__ == "__main__":
    from ..config import DEMO_PROGRAM_ID
    print("ADME computed for", compute_adme_for_program(DEMO_PROGRAM_ID), "molecules")
