"""Decision-ready artifact drafting.

Currently: the go/no-go advancement memo drafted when a molecule crosses the TPP.
Uses the Sonnet-class model with a deterministic fallback so the demo runs keyless.
(PO-from-quote and CRO-reply drafting are stubbed — same pattern, Day 6.)
"""
from __future__ import annotations

from ..config import MODEL_ARTIFACTS
from . import llm

MEMO_SYSTEM = """You are drafting a concise preclinical go/no-go advancement memo \
for a TGTA small-molecule program. Write for a founder/CEO who will sign it. \
Be factual and specific: cite the molecule's data against each TPP criterion, state the \
recommendation (advance to candidate / hold / kill), and note the key remaining risk. \
4-6 sentences, no preamble, no markdown headers."""


def _fallback_memo(molecule: str, scored: dict) -> str:
    lines = [f"Advancement recommendation: {molecule} meets all Target Product Profile criteria."]
    for p in scored.get("params", []):
        if p["status"] == "pass":
            v = p["value"]
            lines.append(
                f"- {p['label']}: {v:.1f}{p['units'] or ''} "
                f"(TPP {p['operator']} {p['threshold']}{p['units'] or ''}) — PASS."
            )
    lines.append(
        f"Recommendation: advance {molecule} to development candidate. "
        "Primary remaining risk is confirmation of the selectivity window in an "
        "orthogonal cellular target-engagement assay before IND-enabling studies."
    )
    return "\n".join(lines)


def go_no_go_memo(molecule: str, scored: dict) -> tuple[str, bool]:
    """Draft the memo. Returns (text, used_llm)."""
    passing = "; ".join(
        f"{p['label']} = {p['value']:.1f}{p['units'] or ''} (TPP {p['operator']} {p['threshold']})"
        for p in scored.get("params", []) if p["status"] == "pass" and p["value"] is not None
    )
    user = (
        f"Molecule: {molecule}\n"
        f"TPP status: MEETS TPP (passes every criterion)\n"
        f"Passing measurements: {passing}\n\n"
        "Draft the go/no-go advancement memo."
    )
    return llm.text(
        model=MODEL_ARTIFACTS,
        system=MEMO_SYSTEM,
        user=user,
        fallback=_fallback_memo(molecule, scored),
        max_tokens=600,
    )
