"""TPP Builder: a guided reasoning flow (best-available model) that turns a
program brief into a structured, executable TPP and writes it to tpp_params.

Uses the Opus-class model (config.MODEL_TPP_BUILDER) — this is the genuine
hard-reasoning step. Degrades to the hand-tuned DEFAULT_TPP without an API key.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import DEMO_PROGRAM_ID, MODEL_TPP_BUILDER
from ..state import db
from . import llm, tpp

# Metrics the scoring engine knows how to read (must match tpp.METRIC_SOURCES)
ALLOWED_METRICS = list(tpp.METRIC_SOURCES.keys())


class TppParamSpec(BaseModel):
    axis: str = Field(description="short axis name, e.g. potency, selectivity, cellular, adme, tox")
    label: str = Field(description="human-readable parameter label")
    metric: str = Field(description=f"one of: {', '.join(ALLOWED_METRICS)}")
    operator: str = Field(description="'<' if lower is better, '>' if higher is better")
    threshold: float = Field(description="the go/no-go threshold value in the metric's units")
    units: str
    weight: float = Field(default=1.0, description="relative importance, 0.5-2.0")
    rationale: str = Field(description="1-2 sentences justifying the threshold, grounded in biology/competitive bar")


class TppSpec(BaseModel):
    params: list[TppParamSpec]


SYSTEM = """You are the TPP (Target Product Profile) builder inside BiotechOS, an \
operating system for preclinical drug programs. You design a rigorous, executable \
TPP: a small set of quantitative go/no-go criteria a molecule must meet to advance.

Rules:
- Only use these metrics (the scoring engine can read no others): {metrics}.
- Each parameter needs an operator ('<' means lower is better, '>' means higher is better), \
a numeric threshold in sensible units, a weight (0.5-2.0), and a rationale grounded in \
biology, the competitive bar, or known class liabilities.
- Prefer 3-5 parameters spanning potency, selectivity, cellular activity, and (where relevant) ADME/tox.
- Thresholds should be ambitious but achievable for a best-in-class candidate.""".format(
    metrics=", ".join(ALLOWED_METRICS)
)


def _default_spec() -> TppSpec:
    return TppSpec(params=[
        TppParamSpec(axis=axis, label=label, metric=metric, operator=op,
                     threshold=threshold, units=units, weight=weight, rationale=rationale)
        for (axis, label, metric, op, threshold, units, weight, rationale) in tpp.DEFAULT_TPP
    ])


def build(brief: str, program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Generate a TPP from a natural-language brief, persist it, return it + provenance."""
    fallback = _default_spec()
    spec, used_llm = llm.structured(
        model=MODEL_TPP_BUILDER,
        system=SYSTEM,
        user=f"Program brief:\n{brief}\n\nDesign the TPP.",
        schema=TppSpec,
        fallback=fallback,
        max_tokens=4096,
    )

    # keep only params whose metric the engine can score
    valid = [p for p in spec.params if p.metric in tpp.METRIC_SOURCES]
    if not valid:
        valid = fallback.params

    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM tpp_params WHERE program_id=?", (program_id,))
        for p in valid:
            conn.execute(
                "INSERT INTO tpp_params(program_id,axis,label,metric,operator,threshold,"
                "near_frac,units,weight,rationale) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (program_id, p.axis, p.label, p.metric, p.operator, p.threshold,
                 0.5, p.units, p.weight, p.rationale),
            )
    conn.close()

    return {
        "used_llm": used_llm,
        "model": MODEL_TPP_BUILDER if used_llm else "fallback",
        "params": [p.model_dump() for p in valid],
    }


DEMO_BRIEF = (
    "Program: TGTA kinase inhibitor for TGTA-amplified solid tumors. "
    "Modality: ATP-competitive small-molecule inhibitor. "
    "Competitive bar: must beat the TGTB-driven tox of the approved dual TGTB/TGTA TKIs, "
    "so selectivity over TGTB is critical. Advancement candidate must be sub-100nM on TGTA "
    "biochemically, translate to cellular anti-proliferation, and show a clean TGTB selectivity window."
)


if __name__ == "__main__":
    import json
    print(json.dumps(build(DEMO_BRIEF), indent=2))
