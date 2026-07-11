"""Export flagged email notes → data/review_notes.md (committable).

The human flags emails with notes in the Simulation UI, then says "check my
flagged emails". This writes a readable table Claude reads to action the
feedback: for each flagged email it shows the date/from/subject, what the OS
decided (triage category + next_step), and the human's note. Claude then fixes
the triage/extract rules and re-triages the email in place.

    uv run python -m biotechos.review notes [program_id]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import DEMO_PROGRAM_ID
from .state import db

OUT = Path(__file__).resolve().parents[2] / "data" / "review_notes.md"


def export_notes(program_id: str = DEMO_PROGRAM_ID) -> Path:
    conn = db.connect()
    rows = conn.execute(
        "SELECT n.id,n.note,n.author,n.created_at,n.document_id,n.decision_id,"
        "d.email_from,d.subject,d.sent_at,d.triage_json,"
        "dec.subject_key AS dec_subject,dec.predicate AS dec_predicate,dec.value AS dec_value "
        "FROM email_notes n LEFT JOIN documents d ON d.id=n.document_id "
        "LEFT JOIN decisions dec ON dec.id=n.decision_id "
        "WHERE n.program_id=? AND n.flagged=1 AND n.resolved=0 "
        "ORDER BY n.created_at DESC",
        (program_id,)).fetchall()
    conn.close()

    lines = [f"# Flagged for review — {program_id}", "",
             f"{len(rows)} flagged note(s). Each: what the OS decided vs. the human's note.", ""]
    if not rows:
        lines.append("_No flagged notes._")
    for r in rows:
        try:
            t = json.loads(r["triage_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            t = {}
        if r["decision_id"]:
            claim = (f"{r['dec_subject']} — {r['dec_predicate']}"
                     + (f" = {r['dec_value']}" if r["dec_value"] else ""))
            lines += [
                f"## Decision [{r['decision_id']}] {claim}",
                f"- **Source email:** [{r['document_id']}] {r['subject'] or '(no subject)'} ({r['sent_at']})",
                f"- **Note ({r['author']}):** {r['note']}",
                "",
            ]
        else:
            lines += [
                f"## Email [{r['document_id']}] {r['subject'] or '(no subject)'}",
                f"- **Date:** {r['sent_at']}",
                f"- **From:** {r['email_from']}",
                f"- **OS triage:** {t.get('category', '?')} → {t.get('next_step', '?')}",
                f"- **Note ({r['author']}):** {r['note']}",
                "",
            ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    return OUT


def main(argv: list[str]) -> None:
    cmd = argv[1] if len(argv) > 1 else "notes"
    program = argv[2] if len(argv) > 2 else DEMO_PROGRAM_ID
    if cmd == "notes":
        path = export_notes(program)
        print(f"wrote {path}")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv)
