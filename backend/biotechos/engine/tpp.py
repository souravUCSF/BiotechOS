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
    ("selectivity", "TGTA vs TGTB selectivity", "selectivity_fold", ">", 10.0, "x", 1.2,
     "TGTB off-target inhibition drives dermatologic/GI toxicity in the clinic (see TGTB-TKI class "
     "effects); >10x selectivity for TGTA over TGTB reduces this liability."),
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
            param_id=p["id"], label=p["label"], axis=p["axis"], status=status,
            value=value, threshold=p["threshold"], operator=p["operator"], units=p["units"],
        ))
    return out


def overall_status(scores: list[ParamScore]) -> Status:
    statuses = [s.status for s in scores if s.status != Status.NO_DATA]
    if not statuses:
        return Status.NO_DATA
    if all(s == Status.PASS for s in statuses):
        return Status.PASS
    if any(s == Status.FAIL for s in statuses):
        return Status.FAIL
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
                 "status": s.status.value, "value": s.value, "threshold": s.threshold,
                 "operator": s.operator, "units": s.units}
                for s in scores
            ],
        }
        if status == Status.PASS:
            meets_tpp.append(m["name"])

    conn.close()
    return {"molecules": list(results.values()), "meets_tpp": meets_tpp}


def population_histogram(metric: str, program_id: str = DEMO_PROGRAM_ID, bins: int = 12) -> dict:
    """All-molecule distribution for a metric, for the Tracker's per-parameter histogram."""
    conn = db.connect()
    molecules = conn.execute(
        "SELECT id FROM molecules WHERE program_id=? AND held_out=0", (program_id,)
    ).fetchall()
    values = []
    for m in molecules:
        v = _molecule_value(conn, m["id"], metric)
        if v is not None:
            values.append(v)
    conn.close()
    if not values:
        return {"metric": metric, "counts": [], "edges": []}
    lo, hi = min(values), max(values)
    if lo == hi:
        return {"metric": metric, "counts": [len(values)], "edges": [lo, hi]}
    width = (hi - lo) / bins
    edges = [lo + i * width for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    return {"metric": metric, "counts": counts, "edges": edges}


if __name__ == "__main__":
    import json
    seed_default_tpp()
    print(json.dumps(recompute(), indent=2, default=str))
