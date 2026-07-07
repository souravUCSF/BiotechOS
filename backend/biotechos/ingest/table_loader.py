"""Curate the TGTA demo set from the long-format activity export and load state.

Two-pass over the gzipped 2M-row export (memory-safe, chunked):
  Pass 1  -> per-molecule summary (smiles, TGTA potency, modality coverage, row count)
             to choose the 50-molecule demo set by data richness.
  Pass 2  -> pull every activity row for the chosen molecules, classify modality,
             pivot long->wide, compute selectivity + pChEMBL.

Selection is purely by data richness (breadth of modalities, then row count) —
not by clinical stage. Every demo molecule is assigned a proprietary compound
code (e.g. BTX-1007); the source dataset's identifiers and real compound names
are kept only in an internal, API-hidden column for our own provenance/debugging.

Active molecules' assays go into the DB. The 25 held-out molecules' assays are
staged to data/curated/held_out_cro/<code>.json to become the Day-4
"incoming CRO dataset" inbox payloads.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

import numpy as np
import pandas as pd

from ..config import (
    CURATED_DIR,
    DEMO_SET_SIZE,
    TGTB_ANTITARGET_CHEMBL,
    HELD_OUT_COUNT,
    DEMO_PROGRAM_ID,
    PRIMARY_TARGET_CHEMBL,
    RAW_DEMO,
)
from ..state import db

POTENCY_TYPES = {"IC50", "Ki", "Kd", "EC50", "AC50", "Potency"}
USECOLS = [
    "molecule_chembl_id", "molecule_name", "canonical_smiles",
    "standard_inchi_key", "target_chembl_id", "assay_type", "assay_description",
    "assay_cell_type", "standard_type", "standard_relation", "standard_value",
    "standard_units", "pchembl_value", "data_validity_comment",
]
CHUNK = 200_000
CODE_PREFIX = "BTX"


def classify_modality(row) -> tuple[str, str]:
    """Return (modality, target_label) for an activity row."""
    tgt = row["target_chembl_id"]
    atype = (row["assay_type"] or "")
    stype = (row["standard_type"] or "")
    desc = (row["assay_description"] or "").lower()
    cell = row.get("assay_cell_type")

    target_label = {PRIMARY_TARGET_CHEMBL: "TGTA", TGTB_ANTITARGET_CHEMBL: "TGTB"}.get(tgt, tgt)

    if any(k in desc for k in ("xenograft", "tumor growth", "tumour growth", "in vivo")):
        return "xenograft", target_label
    if stype in ("kon", "koff", "k_off", "Kinact") or "residence" in desc:
        return "kinetics", target_label
    if atype == "A":
        return "adme", target_label
    if atype == "T":
        return "tox", target_label
    if atype == "F" and (cell or "proliferation" in desc or stype in ("GI50", "GI", "TGI", "Growth Rate")):
        return "cellular_antiprolif", target_label
    if stype in POTENCY_TYPES:
        return "biochemical_ic50", target_label
    return "other", target_label


def _to_float(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def pass1_choose_molecules(path=RAW_DEMO) -> pd.DataFrame:
    """Scan once; return a per-molecule summary frame, then pick the demo set."""
    agg: dict[str, dict] = {}
    for chunk in pd.read_csv(path, usecols=USECOLS, chunksize=CHUNK, low_memory=False):
        for row in chunk.itertuples(index=False):
            r = row._asdict()
            m = r["molecule_chembl_id"]
            s = agg.setdefault(m, {
                "ref_name": r["molecule_name"], "smiles": r["canonical_smiles"],
                "inchi_key": r["standard_inchi_key"],
                "tgta_pchembl": [], "modalities": set(), "n_rows": 0,
            })
            s["n_rows"] += 1
            if not s["smiles"] and r["canonical_smiles"]:
                s["smiles"] = r["canonical_smiles"]
            mod, _ = classify_modality(r)
            s["modalities"].add(mod)
            if r["target_chembl_id"] == PRIMARY_TARGET_CHEMBL and r["standard_type"] in POTENCY_TYPES:
                p = _to_float(r["pchembl_value"])
                if p is not None:
                    s["tgta_pchembl"].append(p)

    recs = []
    for m, s in agg.items():
        if not s["smiles"] or not s["tgta_pchembl"]:
            continue  # demo molecules must have a structure and TGTA potency
        recs.append({
            "source_ref": m, "ref_name": s["ref_name"], "smiles": s["smiles"],
            "inchi_key": s["inchi_key"],
            "tgta_pchembl_median": float(np.median(s["tgta_pchembl"])),
            "n_modalities": len(s["modalities"] - {"other"}),
            "n_rows": s["n_rows"],
        })
    return pd.DataFrame(recs)


def select_demo_set(summary: pd.DataFrame, n=DEMO_SET_SIZE) -> pd.DataFrame:
    """Rank purely by data richness: breadth of modalities first, then row volume."""
    ranked = summary.sort_values(["n_modalities", "n_rows"], ascending=False)
    picks = ranked.head(n).reset_index(drop=True)
    # assign proprietary compound codes in richness-rank order (BTX-1000 = richest)
    picks["code"] = [f"{CODE_PREFIX}-{1000 + i}" for i in range(len(picks))]
    return picks


def pass2_collect_assays(source_refs: set[str], path=RAW_DEMO) -> dict[str, list[dict]]:
    """Return {source_ref: [assay dicts]} for the chosen molecules."""
    out: dict[str, list[dict]] = defaultdict(list)
    for chunk in pd.read_csv(path, usecols=USECOLS, chunksize=CHUNK, low_memory=False):
        sub = chunk[chunk.molecule_chembl_id.isin(source_refs)]
        for row in sub.itertuples(index=False):
            r = row._asdict()
            mod, tgt = classify_modality(r)
            if mod == "other":
                continue
            val = _to_float(r["standard_value"])
            if val is None:
                continue
            out[r["molecule_chembl_id"]].append({
                "modality": mod, "target": tgt,
                "standard_type": r["standard_type"], "value": val,
                "units": r["standard_units"], "relation": r["standard_relation"],
                "pchembl": _to_float(r["pchembl_value"]),
                "assay_desc": r["assay_description"],
                "flags": r["data_validity_comment"],
                "source": "internal_dataset",
            })
    return out


def _median_potency(assays, modality, target=None) -> float | None:
    vals = [a["value"] for a in assays
            if a["modality"] == modality and (target is None or a["target"] == target)]
    return float(np.median(vals)) if vals else None


MAX_PER_MODALITY = 8  # cap for held-out CRO payload: a real CRO report is a handful of assays, not thousands


def _sample_for_cro(assays: list[dict]) -> list[dict]:
    """A believable CRO deliverable: a handful of representative rows per modality,
    not the full off-target panel dump."""
    by_mod: dict[str, list[dict]] = defaultdict(list)
    for a in assays:
        by_mod[a["modality"]].append(a)
    sampled = []
    for mod, rows in by_mod.items():
        rows_sorted = sorted(rows, key=lambda a: a["target"] not in ("TGTA", "TGTB"))
        sampled.extend(rows_sorted[:MAX_PER_MODALITY])
    return sampled


def load(reset: bool = True) -> dict:
    """Full Day-1 ingest. Returns a summary dict."""
    db.init_db(reset=reset)
    conn = db.connect()

    print("Pass 1: scanning export for molecule summary ...")
    summary = pass1_choose_molecules()
    print(f"  {len(summary)} candidate molecules with SMILES + TGTA potency")
    picks = select_demo_set(summary)
    print(f"  selected {len(picks)} demo molecules by data richness "
          f"(median n_modalities={picks.n_modalities.median():.0f}, "
          f"median n_rows={picks.n_rows.median():.0f})")

    chosen = set(picks.source_ref)
    print("Pass 2: collecting assays for chosen molecules ...")
    assays_by_mol = pass2_collect_assays(chosen)

    # Deterministic held-out choice: hold out the 25 sparsest-potency of the chosen set
    order = picks.sort_values("tgta_pchembl_median", ascending=True).source_ref.tolist()
    held_out = set(order[:HELD_OUT_COUNT])

    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO programs(id,name,target,anti_target,indication,status)"
            " VALUES (?,?,?,?,?,?)",
            (DEMO_PROGRAM_ID, "TGTA Kinase Inhibitor Program", "TGTA", "TGTB",
             "TGTA-amplified solid tumors", "active"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO budget(program_id,total,committed,actual,monthly_burn)"
            " VALUES (?,?,?,?,?)",
            (DEMO_PROGRAM_ID, 5_000_000, 0, 0, 180_000),
        )

    held_dir = CURATED_DIR / "held_out_cro"
    if held_dir.exists():
        for f in held_dir.glob("*.json"):
            f.unlink()
    held_dir.mkdir(exist_ok=True)

    curated_rows = []
    for row in picks.itertuples(index=False):
        ref = row.source_ref
        code = row.code
        is_held = ref in held_out
        assays = assays_by_mol.get(ref, [])
        demo = _median_potency(assays, "biochemical_ic50", "TGTA")
        egfr = _median_potency(assays, "biochemical_ic50", "TGTB")
        selectivity = (egfr / demo) if (demo and egfr and demo > 0) else None

        with conn:
            cur = conn.execute(
                "INSERT INTO molecules(program_id,internal_ref,name,smiles,inchi_key,"
                "held_out) VALUES (?,?,?,?,?,?)",
                (DEMO_PROGRAM_ID, f"{ref}:{row.ref_name}", code, row.smiles,
                 row.inchi_key, int(is_held)),
            )
            mol_id = cur.lastrowid

            if is_held:
                # stage a believable CRO deliverable (sampled, not the full off-target dump)
                (held_dir / f"{code}.json").write_text(json.dumps({
                    "code": code, "smiles": row.smiles,
                    "selectivity": selectivity, "assays": _sample_for_cro(assays),
                }, indent=2))
            else:
                for a in assays:
                    conn.execute(
                        "INSERT INTO assays(program_id,molecule_id,modality,target,"
                        "standard_type,value,units,relation,pchembl,source,assay_desc,flags)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (DEMO_PROGRAM_ID, mol_id, a["modality"], a["target"],
                         a["standard_type"], a["value"], a["units"], a["relation"],
                         a["pchembl"], a["source"], a["assay_desc"],
                         json.dumps([a["flags"]]) if a["flags"] else None),
                    )
                if selectivity is not None:
                    conn.execute(
                        "INSERT INTO assays(program_id,molecule_id,modality,target,"
                        "standard_type,value,units,source) VALUES (?,?,?,?,?,?,?,?)",
                        (DEMO_PROGRAM_ID, mol_id, "selectivity", "TGTA/TGTB",
                         "Fold selectivity", selectivity, "x", "derived"),
                    )

        curated_rows.append({
            "code": code, "held_out": int(is_held), "tgta_ic50_nM": demo,
            "tgtb_ic50_nM": egfr, "selectivity_fold": selectivity, "n_assays": len(assays),
        })

    pd.DataFrame(curated_rows).to_csv(CURATED_DIR / "demo_set.csv", index=False)
    conn.close()

    n_active = sum(1 for r in curated_rows if not r["held_out"])
    return {
        "molecules": len(curated_rows), "active": n_active,
        "held_out": len(held_out), "with_selectivity":
        sum(1 for r in curated_rows if r["selectivity_fold"] is not None),
    }


if __name__ == "__main__":
    print(json.dumps(load(), indent=2))
