"""Data-driven metric catalog.

A metric is any comparable molecule property. Instead of a fixed list, the
catalog is discovered from the data plus user-defined additions:

  - ADME descriptors       key = "adme:<field>"        (MW, cLogP, TPSA, QED, ...)
  - assay-derived metrics  key = "assay:<modality>:<target>"  (median of matching assays)
  - custom (user-defined)  stored in custom_metrics; may have no data yet

resolve() turns any key + molecule into a scalar (median for assays). This is the
single source of truth the TPP engine, histograms, and Molecule Database all read.
"""
from __future__ import annotations

import json
import re
import statistics

from ..config import DEMO_PROGRAM_ID
from ..state import db

# assay modalities whose values span decades -> log axis, lower-is-better by default
LOG_MODALITIES = {"biochemical_ic50", "cellular_antiprolif", "kinetics", "selectivity"}
HIGHER_BETTER_MODALITIES = {"selectivity", "xenograft"}

ADME_META = {  # field -> (label, units, higher_is_better)
    "MW": ("Molecular weight", "", False),
    "cLogP": ("cLogP", "", False),
    "TPSA": ("TPSA", "Å²", False),
    "QED": ("QED (drug-likeness)", "", True),
    "HBD": ("H-bond donors", "", False),
    "HBA": ("H-bond acceptors", "", False),
    "RotB": ("Rotatable bonds", "", False),
    "AromaticRings": ("Aromatic rings", "", False),
    "LipinskiViolations": ("Lipinski violations", "", False),
}

_MOD_LABEL = {
    "biochemical_ic50": "biochemical IC50",
    "cellular_antiprolif": "cellular anti-prolif",
    "selectivity": "selectivity",
    "kinetics": "binding kinetics",
    "adme": "ADME assay",
    "tox": "toxicity",
    "xenograft": "xenograft TGI",
}


def _pretty_assay_label(modality: str, target: str | None) -> str:
    m = _MOD_LABEL.get(modality, modality.replace("_", " "))
    return f"{target} {m}" if target and target not in ("None", "") else m


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _adme_metrics() -> list[dict]:
    out = []
    for field, (label, units, hib) in ADME_META.items():
        out.append({"key": f"adme:{field}", "label": label, "kind": "adme",
                    "modality": None, "target": None, "units": units,
                    "log": False, "higher_is_better": hib})
    return out


# Curated, meaningful assay metrics. Off-target panels carry raw external target
# IDs and would explode into thousands of junk metrics — instead we expose the
# on/anti-target axes explicitly and aggregate the panel modalities across targets
# (target "*" = median over every assay of that modality). Never surface raw IDs.
# spec: (modality, target, label, units, log, higher_is_better)
ASSAY_SPEC = [
    ("biochemical_ic50", "TGTA", "TGTA biochemical IC50", "nM", True, False),
    ("biochemical_ic50", "TGTB", "TGTB biochemical IC50 (anti-target)", "nM", True, False),
    ("cellular_antiprolif", "TGTA", "Cellular anti-proliferation (TGTA+ lines)", "nM", True, False),
    ("selectivity", "TGTA/TGTB", "TGTA vs TGTB selectivity", "x", True, True),
    ("kinetics", "*", "Binding kinetics / residence time", "", True, True),
    ("xenograft", "*", "In-vivo xenograft (TGI)", "", False, True),
    ("tox", "*", "Toxicity panel (cytotox / hERG)", "", True, False),
    ("adme", "*", "Measured ADME (clearance / stability)", "", False, False),
]


def _assay_metrics(conn, program_id: str) -> list[dict]:
    out = []
    for modality, target, label, units, log, hib in ASSAY_SPEC:
        # only surface axes that actually have data (custom metrics cover the rest)
        if target == "*":
            n = conn.execute(
                "SELECT COUNT(*) c FROM assays WHERE program_id=? AND modality=?",
                (program_id, modality)).fetchone()["c"]
        else:
            n = conn.execute(
                "SELECT COUNT(*) c FROM assays WHERE program_id=? AND modality=? AND target=?",
                (program_id, modality, target)).fetchone()["c"]
        if n == 0:
            continue
        out.append({
            "key": f"assay:{modality}:{target}",
            "label": label, "kind": "assay", "modality": modality, "target": target,
            "units": units, "log": log, "higher_is_better": hib,
        })
    return out


def _custom_metrics(conn, program_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM custom_metrics WHERE program_id=?", (program_id,)).fetchall()
    return [{
        "key": r["key"], "label": r["label"], "kind": "custom",
        "modality": r["modality"], "target": r["target"], "units": r["units"] or "",
        "log": bool(r["log"]), "higher_is_better": bool(r["higher_is_better"]),
        "description": r["description"],
    } for r in rows]


def catalog(program_id: str = DEMO_PROGRAM_ID, include_counts: bool = True) -> list[dict]:
    conn = db.connect()
    metrics = _assay_metrics(conn, program_id) + _adme_metrics() + _custom_metrics(conn, program_id)
    # de-dup by key (a custom metric may shadow a discovered assay one)
    seen, uniq = set(), []
    for m in metrics:
        if m["key"] in seen:
            continue
        seen.add(m["key"])
        uniq.append(m)
    if include_counts:
        mols = [r["id"] for r in conn.execute(
            "SELECT id FROM molecules WHERE program_id=? AND held_out=0", (program_id,)).fetchall()]
        for m in uniq:
            m["count"] = sum(1 for mid in mols if resolve(conn, program_id, mid, m["key"]) is not None)
    conn.close()
    return uniq


def resolve(conn, program_id: str, molecule_id: int, key: str) -> float | None:
    """Turn a metric key + molecule into a scalar value (median for assays)."""
    if key.startswith("adme:"):
        field = key[5:]
        row = conn.execute("SELECT adme_json FROM molecules WHERE id=?", (molecule_id,)).fetchone()
        if not row or not row["adme_json"]:
            return None
        try:
            return float(json.loads(row["adme_json"]).get(field))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if key.startswith("assay:"):
        _, modality, target = key.split(":", 2)
        if target == "*":  # aggregate across all targets for this modality
            rows = conn.execute(
                "SELECT value FROM assays WHERE molecule_id=? AND modality=?",
                (molecule_id, modality)).fetchall()
        else:
            rows = conn.execute(
                "SELECT value FROM assays WHERE molecule_id=? AND modality=? AND target IS ?",
                (molecule_id, modality, None if target in ("None", "") else target)).fetchall()
        vals = [r["value"] for r in rows if r["value"] is not None]
        return statistics.median(vals) if vals else None
    return None


def get_meta(program_id: str, key: str) -> dict | None:
    for m in catalog(program_id, include_counts=False):
        if m["key"] == key:
            return m
    return None


def define_custom(program_id: str, label: str, units: str = "", log: bool = False,
                  higher_is_better: bool = False, target: str = "TGTA",
                  modality: str | None = None, description: str | None = None) -> dict:
    """Register a user-defined property (no data yet). Data arrives later via
    assays with the matching (modality, target)."""
    modality = modality or slug(label)
    key = f"assay:{modality}:{target}"
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO custom_metrics(program_id,key,label,modality,target,"
            "units,log,higher_is_better,description) VALUES (?,?,?,?,?,?,?,?,?)",
            (program_id, key, label, modality, target, units, int(log),
             int(higher_is_better), description),
        )
    conn.close()
    return {"key": key, "label": label, "modality": modality, "target": target}
