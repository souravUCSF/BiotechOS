"""TPP as an executable spec: each parameter is a predicate over molecule data.

score(molecule) -> per-axis pass/near/fail. recompute() persists scores and
returns a diff of molecules whose overall status changed (the "crossed the
line" moment the Tracker highlights).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import Enum

from ..config import DEMO_PROGRAM_ID
from ..state import db


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


# metric -> (modality, target) lookup used to pull a molecule's value for a param
METRIC_SOURCES = {
    "tgta_biochemical_ic50_nm": ("biochemical_ic50", "TGTA"),
    "egfr_biochemical_ic50_nm": ("biochemical_ic50", "TGTB"),
    "cellular_antiprolif_ic50_nm": ("cellular_antiprolif", "TGTA"),
    "selectivity_fold": ("selectivity", None),
    "adme_clearance": ("adme", None),
    "tox_flag": ("tox", None),
    "xenograft_tgi": ("xenograft", None),
}

DEFAULT_TPP = [
    # axis, label, metric, operator, threshold, units, weight, rationale
    ("potency", "TGTA biochemical potency", "tgta_biochemical_ic50_nm", "<", 100.0, "nM", 1.5,
     "Sub-100nM biochemical IC50 vs TGTA is required to clear the kinase-inhibition bar for a "
     "TGTA-directed candidate; observed demo distribution splits cleanly here."),
    ("selectivity", "TGTA vs TGTB selectivity", "selectivity_fold", ">", 3.0, "x", 1.2,
     "TGTB off-target inhibition drives dermatologic/GI toxicity in the clinic (see TGTB-TKI class "
     "effects); a >3x TGTA-over-TGTB window meaningfully de-risks this liability while remaining "
     "achievable for a differentiated candidate."),
    ("cellular", "Cellular anti-proliferation", "cellular_antiprolif_ic50_nm", "<", 200.0, "nM", 1.0,
     "Biochemical potency must translate to cell-based activity in TGTA+ lines to be credible."),
]


def _molecule_value(conn, molecule_id: int, metric: str) -> float | None:
    modality, target = METRIC_SOURCES.get(metric, (None, None))
    if modality is None:
        return None
    if target:
        rows = conn.execute(
            "SELECT value FROM assays WHERE molecule_id=? AND modality=? AND target=?",
            (molecule_id, modality, target),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT value FROM assays WHERE molecule_id=? AND modality=?",
            (molecule_id, modality),
        ).fetchall()
    vals = [r["value"] for r in rows if r["value"] is not None]
    return statistics.median(vals) if vals else None


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


def seed_default_tpp(program_id: str = DEMO_PROGRAM_ID) -> None:
    conn = db.connect()
    with conn:
        existing = conn.execute(
            "SELECT COUNT(*) c FROM tpp_params WHERE program_id=?", (program_id,)
        ).fetchone()["c"]
        if existing:
            conn.close()
            return
        for axis, label, metric, op, threshold, units, weight, rationale in DEFAULT_TPP:
            conn.execute(
                "INSERT INTO tpp_params(program_id,axis,label,metric,operator,threshold,"
                "near_frac,units,weight,rationale) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (program_id, axis, label, metric, op, threshold, 0.5, units, weight, rationale),
            )
    conn.close()


def score_molecule(conn, molecule_id: int, params: list[dict]) -> list[ParamScore]:
    out = []
    for p in params:
        value = _molecule_value(conn, molecule_id, p["metric"])
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
    params = db.rows_to_dicts(
        conn.execute("SELECT * FROM tpp_params WHERE program_id=?", (program_id,)).fetchall()
    )
    molecules = db.rows_to_dicts(
        conn.execute(
            "SELECT id, name, held_out FROM molecules WHERE program_id=? AND held_out=0",
            (program_id,),
        ).fetchall()
    )

    results = {}
    meets_tpp = []
    for m in molecules:
        scores = score_molecule(conn, m["id"], params)
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


import math

# metrics that span orders of magnitude read far better on a log axis
_LOG_METRICS = {
    "tgta_biochemical_ic50_nm", "egfr_biochemical_ic50_nm",
    "cellular_antiprolif_ic50_nm", "selectivity_fold",
}


def population_histogram(metric: str, program_id: str = DEMO_PROGRAM_ID, bins: int = 12) -> dict:
    """All-molecule distribution for a metric, for the Tracker's per-parameter histogram.
    Uses log-spaced bins for concentration/ratio metrics that span decades."""
    conn = db.connect()
    molecules = conn.execute(
        "SELECT id FROM molecules WHERE program_id=? AND held_out=0", (program_id,)
    ).fetchall()
    param = conn.execute(
        "SELECT threshold, operator, units FROM tpp_params WHERE program_id=? AND metric=?",
        (program_id, metric),
    ).fetchone()
    values = []
    for m in molecules:
        v = _molecule_value(conn, m["id"], metric)
        if v is not None:
            values.append(v)
    conn.close()

    result = {"metric": metric, "counts": [], "edges": [], "log_scale": False,
              "threshold": param["threshold"] if param else None,
              "operator": param["operator"] if param else None,
              "units": param["units"] if param else None}
    if not values:
        return result

    use_log = metric in _LOG_METRICS and min(values) > 0
    result["log_scale"] = use_log
    xs = [math.log10(v) for v in values] if use_log else list(values)
    lo, hi = min(xs), max(xs)
    if lo == hi:
        edges = [10 ** lo, 10 ** hi] if use_log else [lo, hi]
        return {**result, "counts": [len(values)], "edges": edges}

    width = (hi - lo) / bins
    counts = [0] * bins
    for x in xs:
        counts[min(int((x - lo) / width), bins - 1)] += 1
    edges = [(10 ** (lo + i * width)) if use_log else (lo + i * width) for i in range(bins + 1)]
    return {**result, "counts": counts, "edges": edges}


if __name__ == "__main__":
    import json
    seed_default_tpp()
    print(json.dumps(recompute(), indent=2, default=str))
