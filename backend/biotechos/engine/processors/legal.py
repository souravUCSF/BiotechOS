"""Legal screener (processor) — runs a detected legal document (NDA/CDA/MSA/ToS)
through a review that summarizes it and flags issues by High/Medium/Low severity,
given what's known about the company.

INSTRUCTIONS below is the single place the review logic lives — replace it with the
user's `draft_legal` skill instructions to use that exact logic instead.
"""
from __future__ import annotations

import json
import re

from ...config import MODEL_ARTIFACTS, org_for_program
from .. import llm
from .data import real_attachments_anon, _to_document   # reuse the native-reading helpers


# ---- review logic, aligned to Founder's `draft-legal` house standards (redline mode) ----
INSTRUCTIONS = (
    "You are legal counsel reviewing a COUNTERPARTY's legal document against Founder's house "
    "standards (a small biotech; counterparties are CROs/vendors/investors/partners). Identify "
    "the agreement type (NDA, MSA/consulting, IP assignment, term sheet, SAFE, license, SRA, "
    "LOI/MOU, MTA), the parties, and the term. Then flag every DEVIATION from the house standard "
    "and every risk, each with a SEVERITY and a redline-style recommendation (what to change / "
    "ask for).\n"
    "\nHOUSE STANDARDS to check against:\n"
    "- NDAs must be MUTUAL (not one-way), include an AI/ML non-use clause (no uploading "
    "confidential info to AI training/self-improving tools), return/destruction, injunctive "
    "relief, and Delaware governing law.\n"
    "- Consulting/MSA: work product & IP assigned to the Client (us), mutual confidentiality, "
    "independent-contractor status, non-solicitation, Delaware law.\n"
    "- IP assignment: FULL assignment to the Company, further-assurances/attorney-in-fact, reps "
    "& warranties, indemnification, Delaware law.\n"
    "- Term sheets: founder vesting present, 1x non-participating liquidation preference "
    "(participating/multiple = high severity), broad-based weighted-average anti-dilution (full "
    "ratchet = high), standard protective provisions, pro-rata rights, exclusivity + expiration.\n"
    "- SAFE: post-money valuation cap present; California governing law.\n"
    "- Governing law: Delaware for most docs, California for SAFEs — flag other venues.\n"
    "- General red flags (high): uncapped/one-sided liability or indemnification, the "
    "counterparty owning our results/inventions/data, publication or use restrictions that harm "
    "us, assignment without our consent, auto-renewal/evergreen traps, one-sided confidentiality.\n"
    "\nSeverity: high = renegotiate before signing; medium = worth negotiating (payment/term/"
    "termination notice, liability caps, confidentiality duration); low = minor/administrative.\n"
    "For each issue: a short title, the clause/section as written, the concrete concern, and a "
    "specific recommendation in house style. Also give a 2-3 sentence plain-English `summary` "
    "(what this is + the headline risks).\n"
    "Also set `execution_status`: 'executed' if the document is FULLY SIGNED / countersigned by "
    "all parties (signature blocks completed, dated, or marked Completed/DocuSign-completed) — a "
    "final version returned for our records; 'in_revision' if it's a redline/negotiation draft "
    "with edits; 'draft' if it's an initial/unsigned template we'd send out for signature."
)

_SCHEMA_HINT = ('{"agreement_type": str, "parties": [str], "term": str|null, '
                '"execution_status": "draft"|"in_revision"|"executed", "summary": str, '
                '"issues": [{"severity": "high"|"medium"|"low", "title": str, "clause": str|null, '
                '"issue": str, "recommendation": str}]}')


def _company_context(program_id: str) -> str:
    from ...state import db
    conn = db.connect()
    try:
        p = conn.execute("SELECT name, indication FROM programs WHERE id=?", (program_id,)).fetchone()
    finally:
        conn.close()
    if not p:
        return "Small biotech signing with CRO/vendor counterparties."
    return f"Company program: {p['name']} ({p['indication']}). A small biotech; counterparties are CROs/vendors/partners."


def _normalize(obj: dict) -> dict:
    issues = []
    for it in obj.get("issues") or []:
        if not isinstance(it, dict):
            continue
        sev = str(it.get("severity", "low")).lower()
        if sev not in ("high", "medium", "low"):
            sev = "low"
        issues.append({"severity": sev, "title": it.get("title") or "(issue)",
                       "clause": it.get("clause"), "issue": it.get("issue") or "",
                       "recommendation": it.get("recommendation") or ""})
    order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: order[i["severity"]])
    exec_status = str(obj.get("execution_status") or "draft").lower()
    if exec_status not in ("draft", "in_revision", "executed"):
        exec_status = "draft"
    return {"agreement_type": obj.get("agreement_type") or "agreement",
            "parties": obj.get("parties") or [], "term": obj.get("term"),
            "execution_status": exec_status,
            "summary": obj.get("summary") or "", "issues": issues,
            "counts": {"high": sum(1 for i in issues if i["severity"] == "high"),
                       "medium": sum(1 for i in issues if i["severity"] == "medium"),
                       "low": sum(1 for i in issues if i["severity"] == "low")}}


def document_text(doc_row) -> str:
    """The contract text shown in the review popup (the attachment text if present)."""
    from ..attachments import parse_attachments
    raw = doc_row["raw_text"] or ""
    atts = "\n\n".join(f"--- {fn} ---\n{txt}" for fn, txt in parse_attachments(raw))
    return atts or raw


# Strong signals that an attached legal doc is already fully signed / completed and
# returned for our records (so it needs filing, not a redline review).
_EXECUTED_RX = re.compile(
    r"\bfully[-\s]?executed\b|\bexecuted (?:copy|copies|version|document|documents|agreement|contract)\b"
    r"|\bcountersigned\b|\bduly signed\b|\bsignature block[s]? completed\b"
    r"|docusign[^.\n]{0,30}complet|\bcompleted via docusign\b|\bexecution version\b(?=.*sign)",
    re.IGNORECASE)


def detect_execution_status(program_id: str, doc_row, api_key: str | None = None) -> dict:
    """Cheap up-front classifier: is this legal email an ALREADY-EXECUTED document
    (file it) or something to review (draft/redline)? Keyword-first on the email +
    attachment text, with an LLM fallback when ambiguous. Avoids the full redline
    review just to learn execution status."""
    text = ((doc_row["raw_text"] or "") + "\n" + document_text(doc_row))[:8000]
    if _EXECUTED_RX.search(text):
        return {"execution_status": "executed", "method": "keyword",
                "reason": "phrasing indicates a fully-executed document returned for records"}
    # LLM fallback: single focused question, cheap
    sys = ("Classify whether the attached/described legal document is ALREADY FULLY EXECUTED "
           "(signed/countersigned/completed by all parties and returned for records) versus a "
           "DTGTAT or REDLINE still under negotiation. Return JSON "
           '{"execution_status":"executed"|"in_revision"|"draft","reason":str}.')
    obj, _ = llm.json_object(model=MODEL_ARTIFACTS, system=sys, user=text[:6000],
                             fallback={"execution_status": "draft", "reason": "no signature signals"},
                             api_key=api_key, max_tokens=200, timeout=60)
    st = str(obj.get("execution_status") or "draft").lower()
    if st not in ("executed", "in_revision", "draft"):
        st = "draft"
    return {"execution_status": st, "method": "llm", "reason": obj.get("reason", "")}


def review(program_id: str, doc_row, api_key: str | None = None,
           source: str = "text", files: list | None = None) -> dict:
    ctx = _company_context(program_id)
    sys = INSTRUCTIONS + "\n\nCOMPANY CONTEXT:\n" + ctx + "\n\nJSON shape:\n" + _SCHEMA_HINT
    read_source, sent = "anonymized text", []
    if source == "native":
        from ...ingest.anonymize import anonymize_text, _profile
        by_anon = real_attachments_anon(program_id, doc_row["source_ref"])
        items = [(an, p) for an, p in by_anon.items() if not files or an in files]
        blocks = []
        for an, f in items:
            d = _to_document(f)
            if d:
                blocks.append((d[0], d[1], an)); sent.append(an)
        if blocks:
            obj, _ = llm.document_json(model=MODEL_ARTIFACTS, system=sys,
                                       user="Review the attached agreement.", files=blocks,
                                       fallback={}, api_key=api_key, max_tokens=4096, timeout=180)
            prof = _profile(org_for_program(program_id))
            obj = json.loads(anonymize_text(json.dumps(obj), prof))  # re-anonymize whole payload
            read_source = "native: " + ", ".join(sent)
        else:
            obj = {}
            read_source = "native (no readable binary)"
    else:
        obj, _ = llm.json_object(model=MODEL_ARTIFACTS, system=sys,
                                 user=document_text(doc_row)[:14000], fallback={},
                                 api_key=api_key, max_tokens=4096, timeout=150)
    out = _normalize(obj)
    out["read_source"] = read_source
    return out


def review_and_store(conn, program_id: str, doc_row, api_key: str | None = None,
                     source: str = "text", files: list | None = None) -> int:
    r = review(program_id, doc_row, api_key=api_key, source=source, files=files)
    summary = (r.get("summary") or "")[:200]
    existing = conn.execute("SELECT id FROM legal_reviews WHERE document_id=?",
                            (doc_row["id"],)).fetchone()
    if existing:
        conn.execute("UPDATE legal_reviews SET status='pending', summary=?, review_json=? WHERE id=?",
                     (summary, json.dumps(r), existing["id"]))
        return existing["id"]
    cur = conn.execute("INSERT INTO legal_reviews(program_id,document_id,status,summary,review_json) "
                       "VALUES (?,?, 'pending', ?, ?)", (program_id, doc_row["id"], summary, json.dumps(r)))
    return cur.lastrowid
