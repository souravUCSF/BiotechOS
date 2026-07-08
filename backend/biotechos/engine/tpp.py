"""TPP as an executable spec: each parameter is a predicate over molecule data.

score(molecule) -> per-axis pass/near/fail. recompute() persists scores and
returns a diff of molecules whose overall status changed (the "crossed the
line" moment the Tracker highlights).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from ..config import DEMO_PROGRAM_ID
from ..state import db
from . import metrics


class Status(str, Enum):
    PASS = "pass"
    NEAR = "near"
    FAIL = "fail"
    NO_DATA = "no_data"


@dataclass
class ParamScore:
    param_id: int
    label: str
    axis: str
    metric: str
    status: Status
    value: float | None
    threshold: float
    operator: str
    units: str | None


DEFAULT_TPP = [
    # axis, label, metric, operator, threshold, units, weight, rationale
    ("potency", "TGTA biochemical potency", "assay:biochemical_ic50:TGTA", "<", 100.0, "nM", 1.5,
     "Sub-100nM biochemical IC50 vs TGTA is required to clear the kinase-inhibition bar for a "
     "TGTA-directed candidate; observed demo distribution splits cleanly here."),
    ("selectivity", "TGTA vs TGTB selectivity", "assay:selectivity:TGTA/TGTB", ">", 3.0, "x", 1.2,
     "TGTB off-target inhibition drives dermatologic/GI toxicity in the clinic (see TGTB-TKI class "
     "effects); a >3x TGTA-over-TGTB window meaningfully de-risks this liability while remaining "
     "achievable for a differentiated candidate."),
    ("cellular", "Cellular anti-proliferation", "assay:cellular_antiprolif:TGTA", "<", 200.0, "nM", 1.0,
     "Biochemical potency must translate to cell-based activity in TGTA+ lines to be credible."),
]


def _molecule_value(conn, molecule_id: int, metric: str, program_id: str = DEMO_PROGRAM_ID) -> float | None:
    return metrics.resolve(conn, program_id, molecule_id, metric)


def _status_for(value: float | None, operator: str, threshold: float, near_frac: float) -> Status:
    if value is None:
        return Status.NO_DATA
    if operator == "<":
        if value < threshold:
            return Status.PASS
        if value < threshold * (1 + near_frac):
            return Status.NEAR
        return Status.FAIL
    if operator == ">":
        if value > threshold:
            return Status.PASS
        if value > threshold * (1 - near_frac):
            return Status.NEAR
        return Status.FAIL
    raise ValueError(f"unsupported operator {operator!r}")


def active_version(conn, program_id: str) -> dict | None:
    r = conn.execute(
        "SELECT * FROM tpp_versions WHERE program_id=? AND active=1", (program_id,)
    ).fetchone()
    return dict(r) if r else None


def _active_params(conn, program_id: str) -> list[dict]:
    ver = active_version(conn, program_id)
    if ver is None:
        return []
    return db.rows_to_dicts(conn.execute(
        "SELECT * FROM tpp_params WHERE version_id=? ORDER BY id", (ver["id"],)
    ).fetchall())


def _next_version_number(conn, program_id: str) -> int:
    r = conn.execute(
        "SELECT COALESCE(MAX(version), 0) m FROM tpp_versions WHERE program_id=?", (program_id,)
    ).fetchone()
    return r["m"] + 1


def _create_version(conn, program_id: str, params: list[dict], notes: str,
                    author: str = "founder") -> dict:
    """Create a new TPP version from a list of param dicts and make it active."""
    ver_num = _next_version_number(conn, program_id)
    conn.execute("UPDATE tpp_versions SET active=0 WHERE program_id=?", (program_id,))
    ver_id = conn.execute(
        "INSERT INTO tpp_versions(program_id,version,notes,author,active) VALUES (?,?,?,?,1)",
        (program_id, ver_num, notes, author),
    ).lastrowid
    for p in params:
        conn.execute(
            "INSERT INTO tpp_params(program_id,version_id,axis,label,metric,operator,threshold,"
            "near_frac,units,weight,rationale) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (program_id, ver_id, p["axis"], p["label"], p["metric"], p["operator"],
             p["threshold"], p.get("near_frac", 0.5), p.get("units"), p.get("weight", 1.0),
             p.get("rationale")),
        )
    return {"id": ver_id, "version": ver_num}


def seed_default_tpp(program_id: str = DEMO_PROGRAM_ID) -> None:
    conn = db.connect()
    with conn:
        existing = conn.execute(
            "SELECT COUNT(*) c FROM tpp_versions WHERE program_id=?", (program_id,)
        ).fetchone()["c"]
        if existing:
            conn.close()
            return
        params = [
            {"axis": axis, "label": label, "metric": metric, "operator": op,
             "threshold": threshold, "units": units, "weight": weight, "rationale": rationale}
            for (axis, label, metric, op, threshold, units, weight, rationale) in DEFAULT_TPP
        ]
        _create_version(conn, program_id, params,
                        notes="Initial TPP for the TGTA program — potency, TGTB selectivity, "
                              "and cellular anti-proliferation criteria.")
    conn.close()


def list_versions(program_id: str = DEMO_PROGRAM_ID) -> list[dict]:
    conn = db.connect()
    rows = db.rows_to_dicts(conn.execute(
        "SELECT * FROM tpp_versions WHERE program_id=? ORDER BY version DESC", (program_id,)
    ).fetchall())
    conn.close()
    return rows


def current_tpp(program_id: str = DEMO_PROGRAM_ID) -> dict:
    """The active version + its parameters (for the TPP page)."""
    conn = db.connect()
    ver = active_version(conn, program_id)
    params = _active_params(conn, program_id)
    conn.close()
    return {"version": ver, "params": params}


def version_detail(program_id: str, version_number: int) -> dict:
    """A specific TPP version's metadata + parameters (read-only history view)."""
    conn = db.connect()
    ver = conn.execute(
        "SELECT * FROM tpp_versions WHERE program_id=? AND version=?",
        (program_id, version_number),
    ).fetchone()
    if ver is None:
        conn.close()
        raise ValueError("version not found")
    params = db.rows_to_dicts(conn.execute(
        "SELECT * FROM tpp_params WHERE version_id=? ORDER BY id", (ver["id"],)
    ).fetchall())
    conn.close()
    return {"version": dict(ver), "params": params}


def add_param(program_id: str, spec: dict, justification: str) -> dict:
    """Add a new criterion to the TPP -> clones the active version's params and
    appends the new one, creating a NEW version. Justification required."""
    if not justification or not justification.strip():
        raise ValueError("a written justification is required to change the TPP")
    if not spec.get("metric") or spec.get("threshold") is None:
        raise ValueError("a metric and threshold are required")
    conn = db.connect()
    params = _active_params(conn, program_id)
    new_params = [{k: p[k] for k in ("axis", "label", "metric", "operator", "threshold",
                                     "near_frac", "units", "weight", "rationale")} for p in params]
    new_params.append({
        "axis": spec.get("axis", "custom"),
        "label": spec.get("label") or spec["metric"],
        "metric": spec["metric"],
        "operator": spec.get("operator", "<"),
        "threshold": float(spec["threshold"]),
        "near_frac": 0.5,
        "units": spec.get("units", ""),
        "weight": float(spec.get("weight", 1.0)),
        "rationale": spec.get("rationale") or "",
    })
    with conn:
        ver = _create_version(conn, program_id, new_params,
                              notes=f"Added criterion “{new_params[-1]['label']}”. "
                                    f"Justification: {justification.strip()}")
    conn.close()
    return {"new_version": ver["version"]}


def update_param(program_id: str, param_id: int, changes: dict, justification: str) -> dict:
    """Edit one parameter -> clone the active version's params into a NEW version
    with the change applied. Requires a justification (recorded on the version)."""
    if not justification or not justification.strip():
        raise ValueError("a written justification is required to change the TPP")
    conn = db.connect()
    params = _active_params(conn, program_id)
    if not params:
        conn.close()
        raise ValueError("no active TPP to edit")
    target = next((p for p in params if p["id"] == param_id), None)
    if target is None:
        conn.close()
        raise ValueError("parameter not part of the active TPP")
    label = target["label"]
    new_params = []
    for p in params:
        np = {k: p[k] for k in ("axis", "label", "metric", "operator", "threshold",
                                "near_frac", "units", "weight", "rationale")}
        if p["id"] == param_id:
            for k in ("operator", "threshold", "weight", "rationale", "label"):
                if k in changes and changes[k] is not None:
                    np[k] = changes[k]
        new_params.append(np)
    with conn:
        ver = _create_version(conn, program_id, new_params,
                              notes=f"Edited “{label}”. Justification: {justification.strip()}")
    conn.close()
    return {"new_version": ver["version"], "notes_recorded": justification.strip()}


def score_molecule(conn, molecule_id: int, params: list[dict],
                   program_id: str = DEMO_PROGRAM_ID) -> list[ParamScore]:
    out = []
    for p in params:
        value = _molecule_value(conn, molecule_id, p["metric"], program_id)
        status = _status_for(value, p["operator"], p["threshold"], p["near_frac"])
        out.append(ParamScore(
            param_id=p["id"], label=p["label"], axis=p["axis"], metric=p["metric"],
            status=status, value=value, threshold=p["threshold"], operator=p["operator"],
            units=p["units"],
        ))
    return out


def overall_status(scores: list[ParamScore]) -> Status:
    statuses = [s.status for s in scores]
    if all(s == Status.NO_DATA for s in statuses):
        return Status.NO_DATA
    # A molecule only "meets TPP" if it has data on every axis and passes them all —
    # partial data cannot clear the bar (missing an axis is not a pass).
    if all(s == Status.PASS for s in statuses):
        return Status.PASS
    if any(s == Status.FAIL for s in statuses):
        return Status.FAIL
    # remaining mix is NEAR and/or NO_DATA -> not yet a candidate, but not a hard fail
    return Status.NEAR


def recompute(program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Score every molecule against the current TPP; return per-molecule results
    plus the set of molecules currently at PASS (the 'meets TPP' set)."""
    conn = db.connect()
    params = _active_params(conn, program_id)
    molecules = db.rows_to_dicts(
        conn.execute(
            "SELECT id, name, held_out FROM molecules WHERE program_id=? AND held_out=0",
            (program_id,),
        ).fetchall()
    )

    results = {}
    meets_tpp = []
    for m in molecules:
        scores = score_molecule(conn, m["id"], params, program_id)
        status = overall_status(scores)
        results[m["id"]] = {
            "molecule_id": m["id"], "name": m["name"], "status": status.value,
            "params": [
                {"param_id": s.param_id, "label": s.label, "axis": s.axis,
                 "metric": s.metric, "status": s.status.value, "value": s.value,
                 "threshold": s.threshold, "operator": s.operator, "units": s.units}
                for s in scores
            ],
        }
        if status == Status.PASS:
            meets_tpp.append(m["name"])

    conn.close()
    return {"molecules": list(results.values()), "meets_tpp": meets_tpp}


def population_histogram(metric: str, program_id: str = DEMO_PROGRAM_ID, bins: int = 12) -> dict:
    """All-molecule distribution for ANY catalog metric. Uses log-spaced bins for
    metrics flagged log in the catalog. Includes each molecule's bin index so the
    UI can click a bar to filter. Overlays the TPP threshold if this metric is a
    criterion in the active version."""
    conn = db.connect()
    molecules = conn.execute(
        "SELECT id, name FROM molecules WHERE program_id=? AND held_out=0", (program_id,)
    ).fetchall()
    ver = active_version(conn, program_id)
    param = conn.execute(
        "SELECT threshold, operator, units FROM tpp_params WHERE version_id=? AND metric=?",
        (ver["id"] if ver else -1, metric),
    ).fetchone()
    meta = metrics.get_meta(program_id, metric) or {}

    pairs = []  # (molecule_id, name, value)
    for m in molecules:
        v = _molecule_value(conn, m["id"], metric, program_id)
        if v is not None:
            pairs.append((m["id"], m["name"], v))
    conn.close()

    units = (param["units"] if param else None) or meta.get("units")
    result = {"metric": metric, "counts": [], "edges": [], "log_scale": False,
              "threshold": param["threshold"] if param else None,
              "operator": param["operator"] if param else None,
              "units": units, "members": []}
    if not pairs:
        return result

    values = [v for _, _, v in pairs]
    use_log = bool(meta.get("log")) and min(values) > 0
    result["log_scale"] = use_log
    xs = [math.log10(v) for v in values] if use_log else list(values)
    lo, hi = min(xs), max(xs)
    if lo == hi:
        result["members"] = [{"molecule_id": mid, "name": n, "value": v, "bin": 0}
                             for (mid, n, v) in pairs]
        edges = [10 ** lo, 10 ** hi] if use_log else [lo, hi]
        return {**result, "counts": [len(values)], "edges": edges}

    width = (hi - lo) / bins
    counts = [0] * bins
    members = []
    for (mid, n, v), x in zip(pairs, xs):
        b = min(int((x - lo) / width), bins - 1)
        counts[b] += 1
        members.append({"molecule_id": mid, "name": n, "value": v, "bin": b})
    edges = [(10 ** (lo + i * width)) if use_log else (lo + i * width) for i in range(bins + 1)]
    return {**result, "counts": counts, "edges": edges, "members": members}


if __name__ == "__main__":
    import json
    seed_default_tpp()
    print(json.dumps(recompute(), indent=2, default=str))
