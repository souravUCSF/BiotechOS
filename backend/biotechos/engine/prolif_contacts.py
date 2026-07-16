"""Protein–ligand interaction contact maps (ProLIF) over Boltz co-folded complexes.

Each molecule's co-fold PDB (data/cache/structures/mol_{id}.pdb) is a receptor (protein,
chain A) + the ligand (`resname LIG`, chain B). We run a ProLIF interaction fingerprint per
complex and aggregate into a molecules × pocket-residue contact map, plus a per-molecule
LigPlot-style 2D interaction diagram (ProLIF LigNetwork).
"""
from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

from .structure import structure_path

# ProLIF interaction classes we expose (a sensible default subset first).
DEFAULT_INTERACTIONS = ["Hydrophobic", "HBDonor", "HBAcceptor", "PiStacking",
                        "Cationic", "Anionic", "HBond", "VdWContact"]
# short glyphs for the heatmap cells
GLYPH = {"Hydrophobic": "◇", "HBDonor": "→H", "HBAcceptor": "H←", "HBond": "H",
         "PiStacking": "π", "PiCation": "π+", "CationPi": "+π", "Cationic": "+",
         "Anionic": "−", "HalogenBond": "X", "VdWContact": "·"}


def _prep_paths(molecule_id: int):
    base = structure_path(molecule_id)
    return base.with_name(f"mol_{molecule_id}_prot_h.pdb"), base.with_name(f"mol_{molecule_id}_lig_h.sdf")


def _prepare(molecule_id: int):
    """Protonate the co-fold's protein (→PDB) and ligand (→SDF) SEPARATELY and cache them.
    ProLIF needs explicit H; Boltz co-folds are heavy-atom only, and protonating the whole
    complex together collides the ligand/protein residue ids — so we split first."""
    import MDAnalysis as mda
    from openbabel import pybel
    import tempfile
    from pathlib import Path
    src = structure_path(molecule_id)
    if not src.exists():
        return None
    prot_h, lig_h = _prep_paths(molecule_id)
    if not (prot_h.exists() and lig_h.exists()):
        u = mda.Universe(str(src))
        prot = u.select_atoms("protein")
        lig = u.select_atoms("resname LIG or resname UNL")
        if prot.n_atoms == 0 or lig.n_atoms == 0:
            return None
        with tempfile.TemporaryDirectory() as td:
            pp, lp = f"{td}/prot.pdb", f"{td}/lig.pdb"
            prot.write(pp)
            lig.write(lp)
            pm = next(pybel.readfile("pdb", pp)); pm.OBMol.AddHydrogens(False, True, 7.4)
            pm.write("pdb", str(prot_h), overwrite=True)
            lm = next(pybel.readfile("pdb", lp)); lm.addh()
            lm.write("sdf", str(lig_h), overwrite=True)
    return prot_h, lig_h


def _load(molecule_id: int):
    """(fingerprint, ligand_prolif_mol) for a molecule's co-fold, or None if no structure."""
    import MDAnalysis as mda
    import prolif as plf
    prepared = _prepare(molecule_id)
    if prepared is None:
        return None
    prot_h, lig_h = prepared
    prot_mol = plf.Molecule.from_mda(mda.Universe(str(prot_h)).select_atoms("protein"))
    lig_mol = plf.sdf_supplier(str(lig_h))[0]
    fp = plf.Fingerprint()          # all default interactions; we filter on read
    fp.run_from_iterable([lig_mol], prot_mol, progress=False)   # single co-fold frame; populates fp.ifp
    return fp, lig_mol


def _residue_interactions(fp) -> dict[str, list[str]]:
    """{residue_label: [interaction_type, ...]} for the single co-fold frame."""
    try:
        df = fp.to_dataframe()
    except Exception:
        return {}
    out: dict[str, set] = {}
    # columns are a MultiIndex (ligand, protein_residue, interaction); one frame → one row
    for col in df.columns:
        # col = (ligand_resid, protein_resid, interaction_name)
        prot_res = str(col[1])
        inter = str(col[-1])
        if bool(df[col].any()):
            out.setdefault(prot_res, set()).add(inter)
    return {r: sorted(v) for r, v in out.items()}


def _resnum(label: str) -> int:
    import re
    m = re.search(r"(\d+)", label or "")
    return int(m.group(1)) if m else 0


def _seed_contact_map(program_id, molecule_ids, names, want):
    """Precomputed contact map for a demo program, keyed by molecule NAME (ids are
    assigned at seed time). Used when a committed seed exists — the public demo has no
    live ProLIF/OpenBabel stack. Returns None when there is no seed file."""
    import json
    from ..config import DATA_DIR
    p = DATA_DIR / "seed" / program_id / "contact_map.json"
    if not p.exists():
        return None
    by_name = json.loads(p.read_text()).get("by_name", {})
    rows, skipped, residues = [], [], {}
    for mid in molecule_ids:
        nm = names.get(mid, f"#{mid}")
        inter = by_name.get(nm)
        if not inter:
            skipped.append({"id": mid, "name": nm, "reason": "no co-fold structure"})
            continue
        if want:
            inter = {r: [i for i in t if i in want] for r, t in inter.items()}
            inter = {r: t for r, t in inter.items() if t}
        for r in inter:
            residues[r] = residues.get(r, 0) + 1
        rows.append({"id": mid, "name": nm, "interactions": inter})
    ordered = sorted(residues.keys(), key=_resnum)
    return {"residues": ordered,
            "frequency": [{"residue": r, "count": residues[r]} for r in ordered],
            "molecules": rows, "skipped": skipped, "glyphs": GLYPH, "n_cofolded": len(rows)}


def contact_map(program_id: str, molecule_ids: list[int], names: dict[int, str] | None = None,
                interactions: list[str] | None = None) -> dict:
    """Build the contact map across the co-folded molecules in the set. Returns the
    molecule × residue matrix (+ per-residue frequency); ids without a co-fold are
    reported in `skipped`."""
    names = names or {}
    want = set(interactions) if interactions else None
    seeded = _seed_contact_map(program_id, molecule_ids, names, want)
    if seeded is not None:
        return seeded
    rows, skipped, residues = [], [], {}
    for mid in molecule_ids:
        loaded = None
        try:
            loaded = _load(mid)
        except Exception as e:
            skipped.append({"id": mid, "name": names.get(mid, f"#{mid}"), "reason": str(e)[:120]})
            continue
        if loaded is None:
            skipped.append({"id": mid, "name": names.get(mid, f"#{mid}"), "reason": "no co-fold structure"})
            continue
        fp, _ = loaded
        inters = _residue_interactions(fp)
        if want:
            inters = {r: [i for i in types if i in want] for r, types in inters.items()}
            inters = {r: t for r, t in inters.items() if t}
        for r in inters:
            residues[r] = residues.get(r, 0) + 1
        rows.append({"id": mid, "name": names.get(mid, f"#{mid}"), "interactions": inters})

    ordered = sorted(residues.keys(), key=_resnum)
    return {
        "residues": ordered,
        "frequency": [{"residue": r, "count": residues[r]} for r in ordered],
        "molecules": rows,
        "skipped": skipped,
        "glyphs": GLYPH,
        "n_cofolded": len(rows),
    }


def ligplot_html(molecule_id: int) -> str | None:
    """A LigPlot-style 2D interaction diagram for one molecule's co-fold (ProLIF
    LigNetwork → standalone HTML). Returns None if the molecule has no co-fold."""
    try:
        loaded = _load(molecule_id)
    except Exception:
        return None
    if loaded is None:
        return None
    fp, lig_mol = loaded
    try:
        from prolif.plotting.network import LigNetwork
        net = LigNetwork.from_fingerprint(fp, lig_mol, kind="frame", frame=0)
        # save to a temp file and read back the HTML
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "lignetwork.html"
            net.save(str(out))
            return out.read_text()
    except Exception as e:
        return f"<html><body style='font-family:sans-serif;padding:20px'>Could not render LigNetwork: {e}</body></html>"
