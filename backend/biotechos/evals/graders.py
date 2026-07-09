"""Deterministic graders — cheap guardrails that run alongside the LLM judge."""
from __future__ import annotations

import re


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def set_f1(expected: list, got: list) -> dict:
    """Precision/recall/F1 over normalized set membership."""
    exp = {_norm(x) for x in (expected or [])}
    gt = {_norm(x) for x in (got or [])}
    if not exp and not gt:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "missing": [], "extra": []}
    tp = len(exp & gt)
    prec = tp / len(gt) if gt else 0.0
    rec = tp / len(exp) if exp else 1.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
            "missing": [x for x in (expected or []) if _norm(x) not in gt],
            "extra": [x for x in (got or []) if _norm(x) not in exp]}


def exact(expected, got) -> bool:
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        return abs(float(expected) - float(got)) < 1e-6
    return _norm(expected) == _norm(got)


def contains_all(text: str, needles: list) -> list:
    """Return the needles NOT present in text (case-insensitive, norm-tolerant)."""
    t = _norm(text)
    return [n for n in (needles or []) if _norm(n) not in t]


def contains_any(text: str, needles: list) -> list:
    """Return the needles that ARE present (violations for must_not_include)."""
    t = _norm(text)
    return [n for n in (needles or []) if _norm(n) in t]


# candidate "asserted value" tokens in an answer we expect to be grounded in sources
_VALUE_RE = re.compile(r"\b([A-Z][A-Za-z0-9\-]{2,}|\d[\d,.]*)\b")
_STOP = {"the", "and", "for", "from", "with", "can", "test", "tests", "cell", "line",
         "lines", "services", "based", "following", "fact", "rows", "note", "quote"}


def groundedness(answer: str, citations: list[dict]) -> dict:
    """Fraction of answer value-tokens supported by the union of cited documents.
    Catches fabrication without hand-labeling. 1.0 = every asserted token appears
    in some cited source."""
    corpus = _norm(" ".join((c or {}).get("body", "") or "" for c in (citations or [])))
    if not corpus:
        return {"grounded": None, "unsupported": []}  # no citations to check against
    toks = {m.group(1) for m in _VALUE_RE.finditer(answer or "")
            if _norm(m.group(1)) not in _STOP and len(_norm(m.group(1))) > 2}
    unsupported = [t for t in toks if _norm(t) not in corpus]
    total = max(len(toks), 1)
    return {"grounded": round(1 - len(unsupported) / total, 3), "unsupported": sorted(unsupported)}
