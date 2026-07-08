"""TPP Builder: a guided reasoning flow (best-available model) that turns a
program brief into a structured, executable TPP and writes it to tpp_params.

Uses the Opus-class model (config.MODEL_TPP_BUILDER) — this is the genuine
hard-reasoning step. Degrades to the hand-tuned DEFAULT_TPP without an API key.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import DEMO_PROGRAM_ID, MODEL_TPP_BUILDER
from ..state import db
from . import llm, metrics, tpp


class TppParamSpec(BaseModel):
    axis: str = Field(description="short axis name, e.g. potency, selectivity, cellular, adme, tox")
    label: str = Field(description="human-readable parameter label")
    metric: str = Field(description="the metric key this scores, from the catalog provided")
    operator: str = Field(description="'<' if lower is better, '>' if higher is better")
    threshold: float = Field(description="the go/no-go threshold value in the metric's units")
    units: str
    weight: float = Field(default=1.0, description="relative importance, 0.5-2.0")
    rationale: str = Field(description="1-2 sentences justifying the threshold, grounded in biology/competitive bar")


class TppSpec(BaseModel):
    params: list[TppParamSpec]


def _catalog_lines(program_id: str) -> str:
    lines = []
    for m in metrics.catalog(program_id):
        n = m.get("count", 0)
        lines.append(f"  {m['key']} — {m['label']} ({m['units'] or 'unitless'}; "
                     f"{'higher better' if m['higher_is_better'] else 'lower better'}; "
                     f"data on {n} molecules)")
    return "\n".join(lines)


def _system(program_id: str) -> str:
    return (
        "You are the TPP (Target Product Profile) builder inside BiotechOS, an operating "
        "system for preclinical drug programs. You design a rigorous, executable TPP: a small "
        "set of quantitative go/no-go criteria a molecule must meet to advance.\n\n"
        "Available metrics (use the exact `key`; the scoring engine reads only these):\n"
        f"{_catalog_lines(program_id)}\n\n"
        "Rules:\n"
        "- Each parameter needs an operator ('<' lower is better, '>' higher is better), a numeric "
        "threshold in the metric's units, a weight (0.5-2.0), and a rationale grounded in biology, "
        "the competitive bar, or known class liabilities.\n"
        "- Prefer 3-6 parameters spanning potency, selectivity, cellular activity, and (where "
        "relevant) ADME/tox. You may use any metric above, including ones with sparse data.\n"
        "- Thresholds should be ambitious but achievable for a best-in-class candidate."
    )


def _default_spec() -> TppSpec:
    return TppSpec(params=[
        TppParamSpec(axis=axis, label=label, metric=metric, operator=op,
                     threshold=threshold, units=units, weight=weight, rationale=rationale)
        for (axis, label, metric, op, threshold, units, weight, rationale) in tpp.DEFAULT_TPP
    ])


def build(brief: str, program_id: str = DEMO_PROGRAM_ID,
          api_key: str | None = None, notes: str | None = None) -> dict:
    """Generate a TPP from a natural-language brief, persist it as a new version."""
    fallback = _default_spec()
    spec, used_llm = llm.structured(
        model=MODEL_TPP_BUILDER,
        system=_system(program_id),
        user=f"Program brief:\n{brief}\n\nDesign the TPP.",
        schema=TppSpec,
        fallback=fallback,
        max_tokens=4096,
        api_key=api_key,
    )

    # keep only params whose metric exists in the catalog (any real or custom property)
    valid_keys = {m["key"] for m in metrics.catalog(program_id, include_counts=False)}
    valid = [p for p in spec.params if p.metric in valid_keys]
    if not valid:
        valid = fallback.params

    param_dicts = [
        {"axis": p.axis, "label": p.label, "metric": p.metric, "operator": p.operator,
         "threshold": p.threshold, "near_frac": 0.5, "units": p.units, "weight": p.weight,
         "rationale": p.rationale}
        for p in valid
    ]
    note = notes or (
        f"Rebuilt with {MODEL_TPP_BUILDER}" if used_llm else "Rebuilt (deterministic fallback)")
    conn = db.connect()
    with conn:
        ver = tpp._create_version(conn, program_id, param_dicts, notes=note)
    conn.close()

    return {
        "used_llm": used_llm,
        "model": MODEL_TPP_BUILDER if used_llm else "fallback",
        "version": ver["version"],
        "params": [p.model_dump() for p in valid],
    }


def _chat_system(program_id: str) -> str:
    return (
        "You are the TPP Builder agent inside BiotechOS, guiding a biotech founder through "
        "designing an effective Target Product Profile for their program in a conversation. A TPP "
        "is a small set of quantitative go/no-go criteria a molecule must meet to advance.\n\n"
        "Your job: ask focused questions and give expert guidance to arrive at a rigorous, "
        "achievable TPP. Cover potency, selectivity (especially anti-target liabilities), cellular "
        "translation, and ADME/tox where relevant. Ground thresholds in the competitive bar and "
        "known class effects. Be concise and consultative — one or two questions at a time, not a "
        "wall of text. When you and the user have converged, tell them they can click "
        "\"Create this TPP\" to finalize it into a new version.\n\n"
        "The scoring engine reads these metrics (steer the TPP toward them; you may use any, "
        "including sparse ones, and can suggest the user define a new property if needed):\n"
        f"{_catalog_lines(program_id)}"
    )

GREETING = (
    "Let's design the TPP for the TGTA program. The current v1 sets TGTA biochemical "
    "IC50 < 100 nM, TGTA/TGTB selectivity > 3×, and cellular anti-proliferation < 200 nM.\n\n"
    "A few things worth pressuring: (1) is a 3× TGTB window enough to de-risk the TGTB-driven "
    "skin/GI tox that dogs the dual TKIs, or do you want to push toward 10×+? (2) should we add "
    "an ADME or tox gate (e.g. cLogP or a hERG proxy) before a molecule can be called a "
    "candidate? What's the intended indication and route — that shapes the bar."
)


def chat(messages: list[dict], api_key: str | None = None,
         program_id: str = DEMO_PROGRAM_ID) -> dict:
    """One turn of the conversational builder. `messages` = prior turns
    [{role, content}]. Returns the assistant reply + whether a live model was used."""
    fallback = (
        "I can guide this best with a live model — add your Anthropic API key above and I'll "
        "reason through the tradeoffs with you. In the meantime: the biggest lever here is the "
        "TGTB selectivity window. If this is an oral oncology asset, pushing selectivity from 3× "
        "toward 10× meaningfully separates you from the approved dual TGTB/TGTA TKIs on tolerability. "
        "You might also add a cLogP < 5 gate to keep the series drug-like. When ready, click "
        "\"Create this TPP\" to finalize."
    )
    reply, used_llm = llm.chat(
        model=MODEL_TPP_BUILDER, system=_chat_system(program_id), messages=messages,
        fallback=fallback, max_tokens=1024, api_key=api_key,
    )
    return {"reply": reply, "used_llm": used_llm}


def finalize_from_chat(messages: list[dict], program_id: str = DEMO_PROGRAM_ID,
                       api_key: str | None = None) -> dict:
    """Extract a structured TPP from the conversation and persist it as a new version."""
    transcript = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
    brief = (
        "Design the final TPP that reflects the conclusions of this design conversation. "
        "Honor the specific thresholds the user agreed to.\n\n" + transcript
    )
    return build(brief, program_id=program_id, api_key=api_key,
                 notes="Built via TPP Builder conversation")


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
