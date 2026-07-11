"""Generic numeric analyzer — the universal fallback.

Any value+unit measurement gets plausibility/range QC so the pipeline has coverage
on day one, before (or without) a specialist analyzer for its data type.
"""
from __future__ import annotations

# plausible (min, max) per common standard_type, in the usual reported units
_RANGES = {"IC50": (1e-3, 1e6), "EC50": (1e-3, 1e6), "Kd": (1e-3, 1e6), "Ki": (1e-3, 1e6),
           "GI50": (1e-3, 1e6), "kinact": (0, 1e4)}


def analyze(ds: dict) -> dict:
    comp, st = ds.get("compound"), ds.get("standard_type")
    val, units = ds.get("reported_value"), ds.get("units")
    steps, status = [], "ok"
    if val is None:
        steps.append({"step": f"Value — {comp}", "status": "warn",
                      "detail": "no numeric value could be established"})
        status = "warn"
    else:
        lo_hi = _RANGES.get(st)
        if lo_hi and not (lo_hi[0] <= val <= lo_hi[1]):
            steps.append({"step": f"Range check — {comp}", "status": "warn",
                          "detail": f"{st} {val} {units or ''} outside plausible range"})
            status = "warn"
        else:
            steps.append({"step": f"Sanity check — {comp}", "status": "ok",
                          "detail": f"{st} {val} {units or ''} is plausible"})
    dep = ([{"molecule": comp, "modality": ds.get("modality", "other"), "target": ds.get("target"),
             "standard_type": st, "value": val, "units": units, "reported_value": val,
             "raw_points": None, "flags": [s["detail"] for s in steps if s["status"] != "ok"]}]
           if val is not None else [])
    return {"qc_steps": steps, "chart": None, "deposition": dep, "status": status}
