"""Hosted Boltz API client (api.boltz.bio via the official `boltz-api` SDK).

Three capabilities used by the Modeling page:
  - cofold(sequence, smiles)  → structure + binding prediction (Boltz-2.1) of a protein
    receptor + a small-molecule ligand; returns the co-fold structure + ligand ipTM/affinity.
  - generate(sequence, n, ...) → small-molecule design: novel SMILES for the target pocket.
  - estimate_cost_*           → the SDK's built-in cost estimate for the current params.

Auth is the existing BOLTZ_API_KEY. The SDK's `experiments.run_*` helpers start a job, poll,
and download results to a local dir; we parse the co-fold structure + scores out of it. Exact
result-file layout is discovered defensively (glob for cif/pdb + score json).
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

from ..config import CACHE_DIR

BOLTZ_MODEL = "boltz-2.1"
_RUN_ROOT = CACHE_DIR / "boltz"
_RUN_ROOT.mkdir(parents=True, exist_ok=True)


def available() -> bool:
    return bool(os.environ.get("BOLTZ_API_KEY"))


def _client():
    import boltz_api
    key = os.environ.get("BOLTZ_API_KEY")
    if not key:
        raise RuntimeError("BOLTZ_API_KEY is not set (backend/secrets.env)")
    base = os.environ.get("BOLTZ_API_BASE")
    return boltz_api.Boltz(api_key=key, base_url=base) if base else boltz_api.Boltz(api_key=key)


def _protein_entity(sequence: str, chain: str = "A") -> dict:
    return {"type": "protein", "chain_ids": [chain], "value": sequence, "msa": {"type": "empty"}}


def _ligand_entity(smiles: str, chain: str = "B") -> dict:
    return {"type": "ligand_smiles", "chain_ids": [chain], "value": smiles}


def _design_target(sequence: str, chain: str = "A", pocket_residues: list[int] | None = None) -> dict:
    """Small-molecule design target — protein entity WITHOUT an msa block (unlike co-fold);
    optional 0-indexed binding-pocket residues guide generation."""
    t: dict = {"entities": [{"type": "protein", "chain_ids": [chain], "value": sequence}]}
    if pocket_residues:
        t["pocket_residues"] = {chain: list(pocket_residues)}
    return t


# ---- cost estimates (cheap; safe to call live) ----------------------------

def estimate_cofold_cost(sequence: str, smiles: str, num_samples: int = 1) -> dict:
    c = _client()
    r = c.predictions.structure_and_binding.estimate_cost(
        input={"entities": [_protein_entity(sequence), _ligand_entity(smiles)]},
        model=BOLTZ_MODEL)
    return {"usd": getattr(r, "estimated_cost_usd", None), "raw": _to_dict(r)}


def estimate_generate_cost(sequence: str, num_molecules: int, pocket_residues: list[int] | None = None) -> dict:
    c = _client()
    r = c.small_molecule.design.estimate_cost(
        target=_design_target(sequence, pocket_residues=pocket_residues), num_molecules=num_molecules)
    return {"usd": getattr(r, "estimated_cost_usd", None), "raw": _to_dict(r)}


def _to_dict(obj):
    for attr in ("model_dump", "to_dict", "dict"):
        if hasattr(obj, attr):
            try:
                return getattr(obj, attr)()
            except Exception:
                pass
    return getattr(obj, "__dict__", {})


# ---- co-fold (structure + binding) ----------------------------------------

def cofold(sequence: str, smiles: str, name: str) -> dict:
    """Run a Boltz-2.1 structure+binding co-fold; returns {cif_path, ligand_iptm, affinity}."""
    c = _client()
    run_dir = c.experiments.run_structure_and_binding(
        entities=[_protein_entity(sequence), _ligand_entity(smiles)],
        model=BOLTZ_MODEL, num_samples=1, root_dir=str(_RUN_ROOT), name=name, quiet=True)
    run_dir = Path(run_dir)
    cif = _first(run_dir, ("*.cif", "*.pdb"))
    scores = _read_scores(run_dir)
    return {"run_dir": str(run_dir), "cif_path": str(cif) if cif else None,
            "ligand_iptm": scores.get("ligand_iptm") or scores.get("iptm"),
            "affinity": scores.get("affinity_pred_value") or scores.get("affinity"),
            "scores": scores}


def _first(run_dir: Path, patterns) -> Path | None:
    for pat in patterns:
        hits = sorted(run_dir.rglob(pat))
        if hits:
            return hits[0]
    return None


def _read_scores(run_dir: Path) -> dict:
    """Merge any confidence/affinity JSON in the results dir."""
    out: dict = {}
    for jf in run_dir.rglob("*.json"):
        try:
            d = json.loads(jf.read_text())
            if isinstance(d, dict):
                out.update({k: v for k, v in d.items() if not isinstance(v, (dict, list))})
        except Exception:
            continue
    return out


# ---- small-molecule generation --------------------------------------------

def generate(sequence: str, num_molecules: int = 20, molecule_filters: dict | None = None,
             chemical_space: str = "enamine_real", name: str = "gen") -> list[dict]:
    """Generate novel small molecules for the pocket; returns [{smiles, iptm, affinity, ...}]."""
    c = _client()
    kwargs = dict(num_molecules=num_molecules, target=_design_target(sequence),
                  chemical_space=chemical_space, root_dir=str(_RUN_ROOT), name=name, quiet=True)
    if molecule_filters:
        kwargs["molecule_filters"] = molecule_filters
    run_dir = Path(c.experiments.run_small_molecule_design(**kwargs))
    return _read_generated(run_dir)


def latest_generated() -> dict:
    """Return the most recently completed small-molecule design run's parsed molecules,
    read from disk — no new job, no cost. Used to iterate on the UI without re-running."""
    runs = sorted(_RUN_ROOT.glob("gen_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for run_dir in runs:
        mols = _read_generated(run_dir)
        if mols:
            return {"job_id": run_dir.name.replace("gen_", ""),
                    "run_dir": str(run_dir), "molecules": mols,
                    "created": run_dir.stat().st_mtime}
    seeded = _seed_generated()   # committed demo candidates (public demo has no runs on disk)
    if seeded:
        return seeded
    return {"job_id": None, "molecules": []}


def _seed_generated() -> dict | None:
    """Precomputed 'last generate' results for the demo, from a committed seed file, so
    'Load last results' works on a fresh deploy with no runs on disk. None if absent."""
    from ..config import DATA_DIR
    p = DATA_DIR / "seed" / "kras" / "generated.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    mols = [_flatten_generated(r) for r in data.get("molecules", []) if r.get("smiles")]
    if not mols:
        return None
    return {"job_id": data.get("job_id") or "seed", "run_dir": None,
            "molecules": mols, "created": None}


def generated_structure_path(job_id: str, pres_id: str) -> Path | None:
    """Locate the predicted co-fold CIF for one generated molecule."""
    run_dir = _RUN_ROOT / f"gen_{job_id}"
    cif = run_dir / "results" / pres_id / "files" / "result" / f"{pres_id}_predicted.cif"
    if cif.exists():
        return cif
    # fallback: any predicted cif under that prediction dir
    hits = sorted((run_dir / "results" / pres_id).rglob("*_predicted.cif"))
    return hits[0] if hits else None


# columns exported to Excel, in order (label → molecule key)
_EXPORT_COLS = [
    ("id", "id"), ("smiles", "smiles"), ("iptm", "iptm"),
    ("binding_confidence", "binding_confidence"), ("ptm", "ptm"),
    ("complex_plddt", "complex_plddt"), ("complex_iplddt", "complex_iplddt"),
    ("structure_confidence", "structure_confidence"), ("optimization_score", "optimization_score"),
]


def export_generated(job_id: str, ids: list[str] | None = None) -> bytes:
    """Build a ZIP: molecules.xlsx (SMILES + metrics + ADME) + each selected molecule's
    predicted co-fold CIF under structures/."""
    import io, zipfile
    import openpyxl
    result = latest_generated() if job_id in (None, "latest") else None
    run_dir = _RUN_ROOT / f"gen_{(result['job_id'] if result else job_id)}"
    mols = _read_generated(run_dir)
    if ids:
        want = set(ids)
        mols = [m for m in mols if m.get("id") in want]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "generated"
    headers = [c[0] for c in _EXPORT_COLS] + ["lipophilicity", "permeability", "solubility"]
    ws.append(headers)
    for m in mols:
        adme = m.get("adme") or {}
        row = [m.get(k) for _, k in _EXPORT_COLS]
        row += [adme.get("lipophilicity"), adme.get("permeability"), adme.get("solubility")]
        ws.append(row)
    xbuf = io.BytesIO()
    wb.save(xbuf)

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("molecules.xlsx", xbuf.getvalue())
        for m in mols:
            cif = generated_structure_path(run_dir.name.replace("gen_", ""), m.get("id"))
            if cif:
                z.writestr(f"structures/{m['id']}.cif", cif.read_text())
    return zbuf.getvalue()


def _flatten_generated(rec: dict) -> dict:
    """Normalize one design record → {smiles, iptm, binding_confidence, ..., adme}."""
    smi = rec.get("smiles") or rec.get("SMILES")
    metrics = rec.get("metrics") or {}
    out = {"smiles": smi, "id": rec.get("id")}
    out.update({k: v for k, v in metrics.items()})  # iptm, binding_confidence, plddt, etc.
    if rec.get("adme"):
        out["adme"] = rec["adme"]
    # convenience alias so existing UI keys still resolve
    out.setdefault("affinity", metrics.get("binding_confidence"))
    return out


def _read_generated(run_dir: Path) -> list[dict]:
    """Parse generated molecules from the design results dir. The authoritative output is
    `results/index.jsonl` (one JSON object per line: {id, smiles, metrics{iptm,...}, adme}).
    Falls back to per-prediction metadata.json / CSV if the index is absent."""
    mols: list[dict] = []
    index = run_dir / "results" / "index.jsonl"
    if index.exists():
        for line in index.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("smiles") or rec.get("SMILES"):
                    mols.append(_flatten_generated(rec))
            except Exception:
                continue
    if not mols:  # fallback: per-prediction metadata.json
        for jf in run_dir.rglob("metadata.json"):
            try:
                rec = json.loads(jf.read_text())
                if rec.get("smiles") or rec.get("SMILES"):
                    mols.append(_flatten_generated(rec))
            except Exception:
                continue
    if not mols:  # last resort: CSV
        import csv as _csv
        for csv in run_dir.rglob("*.csv"):
            try:
                for row in _csv.DictReader(csv.open()):
                    smi = row.get("smiles") or row.get("SMILES")
                    if smi:
                        mols.append({"smiles": smi, **{k: v for k, v in row.items() if k.lower() != "smiles"}})
            except Exception:
                continue
    return mols
