"""Analyzer registry — the extensibility point for the data-QC workflow.

Each analyzer has one contract:
    analyze(dataset: dict) -> {qc_steps: list, chart: dict|None, deposition: list, status}
where status ∈ ok|warn|fail. The dispatcher routes a typed dataset to its analyzer;
unrecognized types fall back to `generic`. Adding a data type = write one analyzer
file and register it here — nothing else in the pipeline changes.
"""
from __future__ import annotations

from . import dose_response, generic, adme


def _stub(name: str):
    """Placeholder for a not-yet-built specialist: still runs generic QC so the data
    is never dropped, but flags that a dedicated analyzer is pending."""
    def run(ds: dict) -> dict:
        g = generic.analyze(ds)
        g["qc_steps"] = [{"step": f"{name} analyzer", "status": "warn",
                          "detail": f"specialist '{name}' analyzer not yet implemented — "
                                    f"applied generic numeric checks"}] + g["qc_steps"]
        return g
    return run


ANALYZERS = {
    "dose_response": dose_response.analyze,
    "adme": adme.analyze,
    "generic_numeric": generic.analyze,
    # stubbed specialists (fall back to generic + a "pending" note):
    "kinetics": _stub("kinetics"),
    "intact_ms": _stub("intact_ms"),
    "selectivity": _stub("selectivity"),
    "pk": _stub("pk"),
    "thermal_shift": _stub("thermal_shift"),
}
DATA_TYPES = list(ANALYZERS.keys())


def dispatch(ds: dict) -> dict:
    """Route one typed dataset to its analyzer (generic fallback for unknown types)."""
    fn = ANALYZERS.get(ds.get("data_type") or "generic_numeric", generic.analyze)
    return fn(ds)
