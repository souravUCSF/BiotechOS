"""CLI: run evals, capture a qa case, sample docs for labeling, set a baseline.

    uv run python -m biotechos.evals run [suite ...] [--repeat N] [--json out]
    uv run python -m biotechos.evals capture "your question"
    uv run python -m biotechos.evals sample classify --n 20
    uv run python -m biotechos.evals baseline
"""
from __future__ import annotations

import argparse
import json
import sys

from ..config import DEMO_PROGRAM_ID
from ..state import db
from . import report as R
from .runner import run, SUITES


def _capture(question: str, program_id: str) -> None:
    from ..engine.corpus import qa
    r = qa.ask(program_id, question)
    case = {"id": "qa-NEW", "question": question,
            "reference_answer": r["answer"], "expect_source": r["source"],
            "must_include": [], "must_not_include": [], "min_citations": len(r["citations"]),
            "rubric": ""}
    if program_id != DEMO_PROGRAM_ID:
        case["program"] = program_id
    print("# review + edit, then append to data/evals/qa.jsonl:")
    print(json.dumps(case, ensure_ascii=False))
    print("\n# citations:", [c.get("subject", "")[:60] for c in r["citations"]], file=sys.stderr)


def _sample(suite: str, n: int, program_id: str) -> None:
    """Dump n corpus docs with the system's predicted labels as JSONL stubs to correct."""
    from ..engine import extract as X
    import types
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM documents WHERE program_id=? ORDER BY RANDOM() LIMIT ?",
        (program_id, n)).fetchall()
    for row in rows:
        em = types.SimpleNamespace(subject=row["subject"] or "", full_text=row["raw_text"] or "",
                                   body=row["raw_text"] or "", email_from=row["email_from"] or "",
                                   email_to=row["email_to"] or "", attachments=[])
        res = X.extract(program_id, em, conn=conn)
        if suite == "classify":
            case = {"id": f"cl-{row['id']}", "doc_subject": row["subject"],
                    "expect": {"triage": res["triage"], "doc_type": res["doc_type"]}}
        elif suite == "fields":
            ex = res.get("extraction", {})
            case = {"id": f"fx-{row['id']}", "doc_subject": row["subject"],
                    "expect": {k: ex.get(k) for k in ("vendor", "total", "cell_lines", "services")
                               if ex.get(k) not in (None, [], "")}}
        elif suite == "decision":
            case = {"id": f"dec-{row['id']}", "doc_subject": row["subject"],
                    "expect_recommendation": (res.get("analysis") or {}).get("recommendation")}
        else:
            case = {"id": f"{suite}-{row['id']}"}
        print(json.dumps(case, ensure_ascii=False))
    conn.close()
    print(f"# ^ {len(rows)} stubs — correct the labels, then save to data/evals/{suite}.jsonl",
          file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(prog="biotechos.evals")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("run"); rp.add_argument("suites", nargs="*")
    rp.add_argument("--repeat", type=int, default=1); rp.add_argument("--json")
    rp.add_argument("--program", default=DEMO_PROGRAM_ID)
    cp = sub.add_parser("capture"); cp.add_argument("question"); cp.add_argument("--program", default=DEMO_PROGRAM_ID)
    sp = sub.add_parser("sample"); sp.add_argument("suite"); sp.add_argument("--n", type=int, default=20)
    sp.add_argument("--program", default=DEMO_PROGRAM_ID)
    bp = sub.add_parser("baseline"); bp.add_argument("--program", default=DEMO_PROGRAM_ID)
    args = ap.parse_args()

    if args.cmd == "capture":
        _capture(args.question, args.program)
    elif args.cmd == "sample":
        _sample(args.suite, args.n, args.program)
    elif args.cmd in ("run", "baseline"):
        suites = getattr(args, "suites", None) or None
        rep = run(suites, args.program, getattr(args, "repeat", 1))
        print(R.render(rep))
        print("\n" + R.baseline_diff(rep))
        path = R.save(rep)
        print(f"\nsaved: {path}")
        if getattr(args, "json", None):
            open(args.json, "w").write(json.dumps(rep, indent=2))
        if args.cmd == "baseline":
            R.set_baseline(rep); print("baseline set.")


if __name__ == "__main__":
    main()
