"""Scorecard rendering + baseline regression diff."""
from __future__ import annotations

import json
from datetime import datetime

from .runner import EVALS_DIR

RESULTS_DIR = EVALS_DIR / "results"
BASELINE = EVALS_DIR / "baseline.json"


def render(report: dict) -> str:
    lines = ["", "═══ BiotechOS evals ═══"]
    for s in report["suites"]:
        pr = s["pass_rate"]
        bar = "" if pr is None else f"{int(pr*100)}%"
        lines.append(f"\n▸ {s['suite']:10s} {s['passed']}/{s['total']}  {bar}")
        for r in s["results"]:
            if not r["passed"]:
                d = r["detail"]
                why = d.get("error") or {k: v for k, v in d.items()
                                          if k not in ("answer", "judge", "doc")}
                lines.append(f"    ✗ {r['id']}: {why}")
    return "\n".join(lines)


def save(report: dict) -> str:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"{ts}.json"
    path.write_text(json.dumps(report, indent=2))
    return str(path)


def baseline_diff(report: dict) -> str:
    if not BASELINE.exists():
        return "(no baseline; run `baseline` to set one)"
    base = {s["suite"]: s["pass_rate"] for s in json.loads(BASELINE.read_text())["suites"]}
    out = []
    for s in report["suites"]:
        b = base.get(s["suite"])
        cur = s["pass_rate"]
        if b is None or cur is None:
            continue
        if cur < b - 1e-9:
            out.append(f"  ↓ REGRESSION {s['suite']}: {b:.0%} → {cur:.0%}")
        elif cur > b + 1e-9:
            out.append(f"  ↑ improved {s['suite']}: {b:.0%} → {cur:.0%}")
    return "\n".join(out) if out else "  = no change vs baseline"


def set_baseline(report: dict) -> None:
    BASELINE.write_text(json.dumps(report, indent=2))
