"""LLM-as-judge for free-text answers (primary grader for the qa suite).

Falls back to a deterministic verdict (from the guardrails) when no API key, so
CI never hard-depends on a key.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..config import MODEL_ARTIFACTS
from ..engine import llm


class Verdict(BaseModel):
    passed: bool
    score: float          # 0..1
    reasons: str


_SYSTEM = (
    "You are grading an AI assistant's answer to a question about a biotech CRO "
    "email corpus. You are given the QUESTION, a REFERENCE answer (ground truth), "
    "and the ASSISTANT answer. Judge whether the assistant answer is correct and "
    "faithful to the reference: it must contain the key facts in the reference, must "
    "NOT add facts absent from the reference (hallucination), and should be relevant "
    "and concise. Return passed=true only if it is substantively correct. score is "
    "0..1 (fraction of reference facts correctly covered, penalizing fabrication)."
)


def judge(question: str, reference: str, answer: str, rubric: str = "",
          model: str | None = None, repeat: int = 1,
          fallback_passed: bool | None = None) -> Verdict:
    if not llm.has_api_key():
        return Verdict(passed=bool(fallback_passed), score=1.0 if fallback_passed else 0.0,
                       reasons="no API key — deterministic guardrail verdict")
    user = (f"QUESTION:\n{question}\n\nREFERENCE ANSWER:\n{reference}\n\n"
            f"ASSISTANT ANSWER:\n{answer}\n\n"
            f"{'EXTRA RUBRIC: ' + rubric if rubric else ''}")
    verdicts: list[Verdict] = []
    for _ in range(max(1, repeat)):
        v, used = llm.structured(model=model or MODEL_ARTIFACTS, system=_SYSTEM, user=user,
                                 schema=Verdict, fallback=Verdict(
                                     passed=bool(fallback_passed),
                                     score=1.0 if fallback_passed else 0.0,
                                     reasons="fallback"), max_tokens=512)
        verdicts.append(v)
        if not used:
            break
    # majority pass + mean score
    passed = sum(1 for v in verdicts if v.passed) > len(verdicts) / 2
    score = round(sum(v.score for v in verdicts) / len(verdicts), 3)
    reasons = verdicts[0].reasons
    return Verdict(passed=passed, score=score, reasons=reasons)
