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


# Boltz-2.1 predicted properties (structure-and-binding + ADME), stored per
# molecule in molecules.boltz_json. field -> (label, units, higher_is_better).
BOLTZ_META = {
    "iptm": ("Boltz ipTM (interface confidence)", "", True),
    "ptm": ("Boltz pTM", "", True),
    "ligand_iptm": ("Boltz ligand ipTM", "", True),
    "structure_confidence": ("Boltz structure confidence", "", True),
    "complex_plddt": ("Boltz complex pLDDT", "", True),
    "binding_confidence": ("Boltz binding confidence", "", True),
    "optimization_score": ("Boltz binding optimization score", "", True),
    "lipophilicity": ("Boltz predicted lipophilicity (logD)", "", False),
    "permeability": ("Boltz predicted permeability", "", True),
}


def _boltz_metrics(conn, program_id: str) -> list[dict]:
    """Boltz predicted properties — only surfaced once at least one molecule has
    a stored value for the field."""
    row = conn.execute(
        "SELECT COUNT(*) c FROM molecules WHERE program_id=? AND boltz_json IS NOT NULL",
        (program_id,)).fetchone()
    if not row or row["c"] == 0:
        return []
    out = []
    for field, (label, units, hib) in BOLTZ_META.items():
        out.append({"key": f"boltz:{field}", "alias": f"boltz_{field}", "label": label,
                    "kind": "adme", "modality": None, "target": None, "units": units,
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
    # TGTA/TGTB selectivity is no longer a raw input — it is registered as a
    # composite (tgtb_ic50 / tgta_ic50) so it derives from the two biochemical axes.
    # The kinetics / xenograft / tox / adme panels are no longer pooled into a
    # single median — they are decomposed into measurement-specific metrics below
    # (MEASUREMENT_SPEC), each reading one standard_type (with unit filters where
    # the same measurement is reported in incommensurable units).
]

# Measurement-specific metrics: one clean axis per (modality, standard_type),
# optionally restricted to a set of units so mixed in-vivo/in-vitro readings
# don't get pooled. spec: (slug, label, modality, standard_types, units_label,
# log, higher_is_better, unit_like)  — unit_like is a tuple of SQL LIKE patterns
# (None = accept any unit).
MEASUREMENT_SPEC = [
    # kinetics
    ("kinact", "Covalent inactivation rate (Kinact)", "kinetics", ("Kinact",), "/min", True, True, None),
    ("mrt", "Mean residence time (MRT)", "kinetics", ("MRT",), "hr", True, True, None),
    # in-vivo efficacy
    ("tgi", "Tumor growth inhibition (TGI)", "xenograft", ("TGI",), "%", False, True, None),
    # toxicity
    ("cytotox", "Cytotoxicity (CC50 / IC50)", "tox", ("CC50", "IC50"), "nM", True, True, None),
    ("dili", "DILI severity class", "tox", ("DILI_severity_class",), "class", False, False, None),
    # ADME / PK
    ("t_half", "Half-life (T½)", "adme", ("T1/2",), "hr", True, True, None),
    ("bioavail", "Oral bioavailability (F)", "adme", ("F",), "%", False, True, None),
    ("vdss", "Volume of distribution (Vdss)", "adme", ("Vdss",), "L/kg", True, False, None),
    ("auc", "Exposure (AUC)", "adme", ("AUC",), "ng·hr/mL", True, True, None),
    ("cmax", "Peak concentration (Cmax)", "adme", ("Cmax",), "nM", True, True, None),
    ("ppb", "Plasma protein binding (PPB)", "adme", ("PPB",), "%", False, False, None),
    ("stability", "Metabolic stability", "adme", ("Stability",), "%", False, True, None),
    ("clearance", "In-vivo clearance (CL)", "adme", ("CL",), "mL/min/kg", True, False, ("mL.min-1%",)),
    ("permeability", "Permeability (Papp)", "adme", ("Papp", "permeability"), "10⁻⁶ cm/s", True, True, ("%cm/s",)),
]
_MEAS_BY_SLUG = {s[0]: s for s in MEASUREMENT_SPEC}


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


# canonical cell line -> regex over assay descriptions (order: specific first)
CELL_LINE_PATTERNS = [
    ("MDA-MB-468", r"MDA-?MB-?468"),
    ("MDA-MB-453", r"MDA-?MB-?453"),
    ("MDA-MB-231", r"MDA-?MB-?231"),
    ("HCC1954", r"HCC-?1954"),
    ("NCI-CellLine-1", r"(?:NCI-?)?CellLine-1"),
    ("SKBR3", r"SK-?BR-?3"),
    ("SKOV3", r"SK-?OV-?3"),
    ("CellLine-2", r"BT-?474"),
    ("T47D", r"T-?47D"),
    ("Calu-3", r"Calu-?3"),
    ("A431", r"A-?431"),
    ("A549", r"A-?549"),
    ("AU565", r"AU-?565"),
    ("MCF7", r"MCF-?7"),
    ("3T3", r"3T3"),
    ("LoVo", r"LoVo"),
    ("HB4a", r"HB4a"),
    ("ZR-75", r"ZR-?75"),
]
_CELL_RES = [(name, re.compile(pat, re.I)) for name, pat in CELL_LINE_PATTERNS]


def extract_cell_line(desc: str | None) -> str | None:
    if not desc:
        return None
    for name, rx in _CELL_RES:
        if rx.search(desc):
            return name
    return None


def backfill_cell_lines(program_id: str = DEMO_PROGRAM_ID) -> int:
    """Populate assays.cell_line for cellular assays from their descriptions."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT id, assay_desc FROM assays WHERE program_id=? AND modality='cellular_antiprolif'"
        " AND cell_line IS NULL", (program_id,)).fetchall()
    n = 0
    with conn:
        for r in rows:
            cl = extract_cell_line(r["assay_desc"])
            if cl:
                conn.execute("UPDATE assays SET cell_line=? WHERE id=?", (cl, r["id"]))
                n += 1
    conn.close()
    return n


def _cellline_metrics(conn, program_id: str, min_mols: int = 3) -> list[dict]:
    """One metric per cell line with anti-proliferation data on enough molecules."""
    rows = conn.execute(
        "SELECT cell_line, COUNT(DISTINCT molecule_id) nmol FROM assays "
        "WHERE program_id=? AND modality='cellular_antiprolif' AND cell_line IS NOT NULL "
        "GROUP BY cell_line HAVING nmol >= ? ORDER BY nmol DESC",
        (program_id, min_mols)).fetchall()
    out = []
    for r in rows:
        cl = r["cell_line"]
        out.append({
            "key": f"cell:{cl}", "alias": "cell_" + slug(cl),
            "label": f"Anti-proliferation — {cl}", "kind": "assay",
            "modality": "cellular_antiprolif", "target": cl, "units": "nM",
            "log": True, "higher_is_better": False,
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


def _measurement_metrics(conn, program_id: str) -> list[dict]:
    """One clean metric per (modality, standard_type) from MEASUREMENT_SPEC —
    the decomposed replacements for the old pooled kinetics/xenograft/tox/adme."""
    out = []
    for slug_, label, modality, stypes, units, log, hib, unit_like in MEASUREMENT_SPEC:
        placeholders = ",".join("?" * len(stypes))
        sql = (f"SELECT COUNT(DISTINCT molecule_id) c FROM assays WHERE program_id=? "
               f"AND modality=? AND standard_type IN ({placeholders})")
        args = [program_id, modality, *stypes]
        if unit_like:
            sql += " AND (" + " OR ".join("units LIKE ?" for _ in unit_like) + ")"
            args += list(unit_like)
        if conn.execute(sql, args).fetchone()["c"] == 0:
            continue
        out.append({
            "key": f"meas:{slug_}", "alias": slug_, "label": label, "kind": "assay",
            "modality": modality, "target": None, "units": units,
            "log": log, "higher_is_better": hib,
        })
    return out


def catalog(program_id: str = DEMO_PROGRAM_ID, include_counts: bool = True) -> list[dict]:
    conn = db.connect()
    metrics = (_assay_metrics(conn, program_id) + _measurement_metrics(conn, program_id)
               + _cellline_metrics(conn, program_id)
               + _adme_metrics() + _boltz_metrics(conn, program_id)
               + _custom_metrics(conn, program_id))
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
import functools
import math

# whitelisted functions available inside formulas (arithmetic scope)
_FORMULA_FUNCS = {"log10": math.log10, "log": math.log, "abs": abs, "sqrt": math.sqrt}


@functools.lru_cache(maxsize=8)
def _alias_map(program_id: str) -> dict[str, str]:
    """alias token -> metric key, for every non-formula catalog metric.
    Cached: the catalog is stable within a request; invalidated by define_custom."""
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
    if key.startswith("cell:"):  # cellular anti-proliferation in a specific cell line
        cl = key[5:]
        rows = conn.execute(
            "SELECT value FROM assays WHERE molecule_id=? AND modality='cellular_antiprolif' "
            "AND cell_line=?", (molecule_id, cl)).fetchall()
        vals = [r["value"] for r in rows if r["value"] is not None]
        return statistics.median(vals) if vals else None
    if key.startswith("meas:"):  # measurement-specific assay axis
        spec = _MEAS_BY_SLUG.get(key[5:])
        if not spec:
            return None
        _, _, modality, stypes, _, _, _, unit_like = spec
        placeholders = ",".join("?" * len(stypes))
        sql = (f"SELECT value FROM assays WHERE molecule_id=? AND modality=? "
               f"AND standard_type IN ({placeholders})")
        args = [molecule_id, modality, *stypes]
        if unit_like:
            sql += " AND (" + " OR ".join("units LIKE ?" for _ in unit_like) + ")"
            args += list(unit_like)
        rows = conn.execute(sql, args).fetchall()
        vals = [r["value"] for r in rows if r["value"] is not None]
        return statistics.median(vals) if vals else None
    if key.startswith("adme:"):
        field = key[5:]
        row = conn.execute("SELECT adme_json FROM molecules WHERE id=?", (molecule_id,)).fetchone()
        if not row or not row["adme_json"]:
            return None
        try:
            return float(json.loads(row["adme_json"]).get(field))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if key.startswith("boltz:"):  # Boltz-predicted structure/binding/ADME value
        field = key[6:]
        row = conn.execute("SELECT boltz_json FROM molecules WHERE id=?", (molecule_id,)).fetchone()
        if not row or not row["boltz_json"]:
            return None
        try:
            return float(json.loads(row["boltz_json"]).get(field))
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
    _alias_map.cache_clear()  # catalog changed; drop memoized alias map
    return {"key": key, "label": label, "formula": formula}
