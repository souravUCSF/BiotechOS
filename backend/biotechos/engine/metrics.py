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
        out.append({"key": f"adme:{field}", "alias": field, "label": label, "kind": "adme",
                    "modality": None, "target": None, "units": units,
                    "log": False, "higher_is_better": hib})
    return out


# Curated, meaningful assay metrics. Off-target panels carry raw external target
# IDs and would explode into thousands of junk metrics — instead we expose the
# on/anti-target axes explicitly and aggregate the panel modalities across targets
# (target "*" = median over every assay of that modality). Never surface raw IDs.
# spec: (modality, target, alias, label, units, log, higher_is_better)
# `alias` is the short token used to reference this metric inside formulas.
ASSAY_SPEC = [
    ("biochemical_ic50", "TGTA", "tgta_ic50", "TGTA biochemical IC50", "nM", True, False),
    ("biochemical_ic50", "TGTB", "tgtb_ic50", "TGTB biochemical IC50 (anti-target)", "nM", True, False),
    ("cellular_antiprolif", "TGTA", "cell_ic50", "Cellular anti-proliferation (TGTA+ lines)", "nM", True, False),
    ("selectivity", "TGTA/TGTB", "selectivity", "TGTA vs TGTB selectivity", "x", True, True),
    ("kinetics", "*", "kinetics", "Binding kinetics / residence time", "", True, True),
    ("xenograft", "*", "xenograft", "In-vivo xenograft (TGI)", "", False, True),
    ("tox", "*", "tox", "Toxicity panel (cytotox / hERG)", "", True, False),
    ("adme", "*", "adme_meas", "Measured ADME (clearance / stability)", "", False, False),
]


def _assay_metrics(conn, program_id: str) -> list[dict]:
    out = []
    for modality, target, alias, label, units, log, hib in ASSAY_SPEC:
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
            "key": f"assay:{modality}:{target}", "alias": alias,
            "label": label, "kind": "assay", "modality": modality, "target": target,
            "units": units, "log": log, "higher_is_better": hib,
        })
    return out


def _custom_metrics(conn, program_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM custom_metrics WHERE program_id=?", (program_id,)).fetchall()
    out = []
    for r in rows:
        formula = r["formula"] if "formula" in r.keys() else None
        out.append({
            "key": r["key"], "alias": slug(r["label"]),
            "label": r["label"], "kind": "formula" if formula else "custom",
            "modality": r["modality"], "target": r["target"], "units": r["units"] or "",
            "log": bool(r["log"]), "higher_is_better": bool(r["higher_is_better"]),
            "description": r["description"], "formula": formula,
        })
    return out


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


import ast
import math

# whitelisted functions available inside formulas (arithmetic scope)
_FORMULA_FUNCS = {"log10": math.log10, "log": math.log, "abs": abs, "sqrt": math.sqrt}


def _alias_map(program_id: str) -> dict[str, str]:
    """alias token -> metric key, for every non-formula catalog metric."""
    out = {}
    for m in catalog(program_id, include_counts=False):
        if m.get("kind") != "formula" and m.get("alias"):
            out[m["alias"]] = m["key"]
    return out


def _eval_formula(conn, program_id: str, molecule_id: int, formula: str,
                  aliases: dict[str, str], depth: int = 0) -> float | None:
    if depth > 5:
        return None

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value) if isinstance(node.value, (int, float)) else None
        if isinstance(node, ast.Name):
            k = aliases.get(node.id)
            if k is None:
                raise ValueError(f"unknown metric alias '{node.id}'")
            return resolve(conn, program_id, molecule_id, k)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = ev(node.operand)
            return None if v is None else (v if isinstance(node.op, ast.UAdd) else -v)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            a, b = ev(node.left), ev(node.right)
            if a is None or b is None:
                return None
            if isinstance(node.op, ast.Add): return a + b
            if isinstance(node.op, ast.Sub): return a - b
            if isinstance(node.op, ast.Mult): return a * b
            if isinstance(node.op, ast.Div): return a / b if b != 0 else None
            if isinstance(node.op, ast.Pow): return a ** b
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FORMULA_FUNCS:
            args = [ev(a) for a in node.args]
            if any(a is None for a in args):
                return None
            try:
                return float(_FORMULA_FUNCS[node.func.id](*args))
            except (ValueError, ZeroDivisionError):
                return None
        raise ValueError("unsupported expression")

    try:
        tree = ast.parse(formula, mode="eval")
        v = ev(tree)
        return float(v) if v is not None and math.isfinite(v) else None
    except Exception:
        return None


def resolve(conn, program_id: str, molecule_id: int, key: str) -> float | None:
    """Turn a metric key + molecule into a scalar value (median for assays)."""
    if key.startswith("formula:"):
        row = conn.execute(
            "SELECT formula FROM custom_metrics WHERE program_id=? AND key=?",
            (program_id, key)).fetchone()
        if not row or not row["formula"]:
            return None
        return _eval_formula(conn, program_id, molecule_id, row["formula"], _alias_map(program_id))
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


def values_table(program_id: str, keys: list[str]) -> list[dict]:
    """For every active molecule, resolve the requested metric keys -> a value matrix
    for the Molecule Database's configurable columns."""
    conn = db.connect()
    mols = conn.execute(
        "SELECT id, name FROM molecules WHERE program_id=? AND held_out=0 ORDER BY id",
        (program_id,),
    ).fetchall()
    out = []
    for m in mols:
        vals = {k: resolve(conn, program_id, m["id"], k) for k in keys}
        out.append({"molecule_id": m["id"], "name": m["name"], "values": vals})
    conn.close()
    return out


def get_meta(program_id: str, key: str) -> dict | None:
    for m in catalog(program_id, include_counts=False):
        if m["key"] == key:
            return m
    return None


def define_custom(program_id: str, label: str, units: str = "", log: bool = False,
                  higher_is_better: bool = False, target: str = "TGTA",
                  modality: str | None = None, description: str | None = None,
                  formula: str | None = None) -> dict:
    """Register a user-defined property. With `formula`, it's a derived metric
    (arithmetic over other metric aliases). Otherwise it's an empty assay metric
    whose data arrives later via matching (modality, target) assays."""
    conn = db.connect()
    formula = (formula or "").strip() or None
    if formula:
        key = f"formula:{slug(label)}"
        modality, target = None, None
    else:
        modality = modality or slug(label)
        key = f"assay:{modality}:{target}"
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO custom_metrics(program_id,key,label,modality,target,"
            "units,log,higher_is_better,description,formula) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (program_id, key, label, modality, target, units, int(log),
             int(higher_is_better), description, formula),
        )
    conn.close()
    return {"key": key, "label": label, "formula": formula}
