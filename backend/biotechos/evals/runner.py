"""Eval runner — dispatches JSONL cases per suite and grades them."""
from __future__ import annotations

import json
import types
from pathlib import Path

from ..config import DATA_DIR, DEMO_PROGRAM_ID
from ..state import db
from ..engine import identity
from ..engine import extract as X
from ..engine.corpus import qa
from . import graders
from .judge import judge

EVALS_DIR = DATA_DIR / "evals"
SUITES = ["qa", "classify", "fields", "identity", "decision"]


def load_suite(name: str) -> list[dict]:
    p = EVALS_DIR / f"{name}.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            out.append(json.loads(line))
    return out


def save_suite(name: str, cases: list[dict]) -> int:
    """Overwrite a suite's JSONL with the given cases (one JSON object per line)."""
    if name not in SUITES:
        raise ValueError(f"unknown suite {name}")
    EVALS_DIR.mkdir(parents=True, exist_ok=True)
    p = EVALS_DIR / f"{name}.jsonl"
    p.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + ("\n" if cases else ""))
    return len(cases)


def _find_doc(conn, program_id: str, case: dict):
    """Look up a corpus document by doc_id or subject substring."""
    if case.get("doc_id"):
        return conn.execute("SELECT * FROM documents WHERE id=?", (case["doc_id"],)).fetchone()
    subj = case.get("doc_subject", "")
    return conn.execute(
        "SELECT * FROM documents WHERE program_id=? AND subject LIKE ? ORDER BY id LIMIT 1",
        (program_id, f"%{subj}%")).fetchone()


def _doc_email(row):
    """Reconstruct a minimal Email-like object to re-run extraction live."""
    return types.SimpleNamespace(
        subject=row["subject"] or "", full_text=row["raw_text"] or "",
        body=row["raw_text"] or "", email_from=row["email_from"] or "",
        email_to=row["email_to"] or "", attachments=[], source_ref=None,
        direction=row["direction"] or "inbound")


# --- per-suite evaluators: return (passed, detail) ---
def _eval_qa(program_id, case, conn, repeat):
    r = qa.ask(program_id, case["question"])
    ans = r["answer"]
    missing = graders.contains_all(ans, case.get("must_include", []))
    violations = graders.contains_any(ans, case.get("must_not_include", []))
    src_ok = ("expect_source" not in case) or (r["source"] == case["expect_source"])
    cites_ok = len(r["citations"]) >= case.get("min_citations", 0)
    grd = graders.groundedness(ans, r["citations"])
    guardrails_ok = not missing and not violations and src_ok and cites_ok
    v = judge(case["question"], case.get("reference_answer", ""), ans,
              rubric=case.get("rubric", ""), repeat=repeat, fallback_passed=guardrails_ok)
    passed = v.passed and not violations and src_ok and cites_ok
    return passed, {"source": r["source"], "expected_source": case.get("expect_source"),
                    "citations": len(r["citations"]),
                    "missing_include": missing, "expected_include": case.get("must_include", []),
                    "must_not_violations": violations,
                    "source_ok": src_ok, "citations_ok": cites_ok,
                    "groundedness": grd.get("grounded"), "unsupported": grd.get("unsupported"),
                    "judge_score": v.score, "judge": v.reasons,
                    "returned": ans, "reference": case.get("reference_answer", "")}


def _eval_extract(program_id, case, conn):
    row = _find_doc(conn, program_id, case)
    if not row:
        return False, {"error": f"doc not found: {case.get('doc_subject') or case.get('doc_id')}"}
    res = X.extract(program_id, _doc_email(row), conn=conn)
    exp = case.get("expect", {})
    detail = {"doc": row["subject"][:50]}
    ok = True
    if "triage" in exp:
        detail["triage"] = (res["triage"], exp["triage"]); ok &= graders.exact(exp["triage"], res["triage"])
    if "doc_type" in exp:
        detail["doc_type"] = (res["doc_type"], exp["doc_type"]); ok &= graders.exact(exp["doc_type"], res["doc_type"])
    ex = res.get("extraction", {}) or {}
    if "vendor" in exp:
        ok_v = graders.exact(exp["vendor"], ex.get("vendor")); detail["vendor"] = (ex.get("vendor"), exp["vendor"]); ok &= ok_v
    if "total" in exp:
        ok_t = ex.get("total") is not None and graders.exact(exp["total"], ex.get("total"))
        detail["total"] = (ex.get("total"), exp["total"]); ok &= ok_t
    for field in ("cell_lines", "services"):
        if field in exp:
            f1 = graders.set_f1(exp[field], ex.get(field, []))
            detail[field] = f1; ok &= f1["recall"] >= case.get("min_recall", 1.0)
    return ok, detail


def _eval_decision(program_id, case, conn):
    row = _find_doc(conn, program_id, case)
    if not row:
        return False, {"error": "doc not found"}
    res = X.extract(program_id, _doc_email(row), conn=conn)
    rec = (res.get("analysis") or {}).get("recommendation")
    ok = graders.exact(case["expect_recommendation"], rec)
    return ok, {"recommendation": (rec, case["expect_recommendation"])}


def _eval_identity(program_id, case, conn):
    r = identity.resolve_molecule(program_id, case["token"], case.get("smiles"), conn=conn)
    detail = {"status": (r["status"], case.get("expect_status"))}
    ok = ("expect_status" not in case) or (r["status"] == case["expect_status"])
    if case.get("expect_same_as"):
        r2 = identity.resolve_molecule(program_id, case["expect_same_as"], conn=conn)
        same = r["molecule_id"] is not None and r["molecule_id"] == r2["molecule_id"]
        detail["same_as"] = same; ok &= same
    return ok, detail


def eval_one(name: str, case: dict, program_id: str = DEMO_PROGRAM_ID,
             repeat: int = 1, conn=None) -> dict:
    """Evaluate a single case → {id, passed, detail}. Used by the per-case
    progress runner in the eval site."""
    own = conn is None
    conn = conn or db.connect()
    try:
        if name == "qa":
            passed, detail = _eval_qa(program_id, case, conn, repeat)
        elif name in ("classify", "fields"):
            passed, detail = _eval_extract(program_id, case, conn)
        elif name == "decision":
            passed, detail = _eval_decision(program_id, case, conn)
        elif name == "identity":
            passed, detail = _eval_identity(program_id, case, conn)
        else:
            passed, detail = False, {"error": f"unknown suite {name}"}
    except Exception as e:
        passed, detail = False, {"error": f"{type(e).__name__}: {e}"}
    finally:
        if own:
            conn.close()
    return {"id": case.get("id", "?"), "passed": bool(passed), "detail": detail}


def run_suite(name: str, program_id: str = DEMO_PROGRAM_ID, repeat: int = 1) -> dict:
    cases = load_suite(name)
    conn = db.connect()
    results = [eval_one(name, c, program_id, repeat, conn=conn) for c in cases]
    conn.close()
    n = len(results)
    npass = sum(1 for r in results if r["passed"])
    return {"suite": name, "total": n, "passed": npass,
            "pass_rate": round(npass / n, 3) if n else None, "results": results}


def run(suites: list[str] | None = None, program_id: str = DEMO_PROGRAM_ID,
        repeat: int = 1) -> dict:
    suites = suites or [s for s in SUITES if (EVALS_DIR / f"{s}.jsonl").exists()]
    return {"suites": [run_suite(s, program_id, repeat) for s in suites]}
