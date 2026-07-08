"""Triage + purpose-built extraction agents for the corpus.

Pipeline per email: triage (actionable|fyi|noise) → classify (doc_type) → the
matching agent → typed extraction + observations (claims for the world model) +
a proposed next step. Deterministic-first (works with no API key); the LLM is an
optional upgrade via engine.llm.structured.
"""
from __future__ import annotations

import re

from ...engine import identity

# anonymized email domain → vendor display name (mirrors ingest/anonymize maps)
VENDOR_BY_DOMAIN = {
    "vendor-23.example": "Vendor 23", "vendor-22.example": "Vendor 22",
    "crystalpath.example": "CrystalPath", "novakin.example": "NovaKin",
    "cytonova.example": "CytoNova Labs", "kinaseworks.example": "KinaseWorks",
    "reagentco.example": "ReagentCo",
}
OWN_DOMAIN = "demoorg.example"

# Broad cancer cell-line vocabulary — matches lines CROs list in capability docs.
CELL_LINE_RE = re.compile(
    r"\b(CellLine-1|NCI-?CellLine-1|SK-?BR-?3|BT-?474|MCF-?7|T-?47D|SK-?OV-?3|A431|A549|"
    r"MDA-?MB-?\d{3}|HCC-?\d{3,4}|AU565|ZR-?75-?1?|Calu-?3|LoVo|3T3|HCT-?116|"
    r"Colo-?205|HT-?29|SW-?\d{3}|SK-?MEL-?\d+|WM\d{2,4}|MALME-?3M|A375|LOX-?IMVI|"
    r"NCI-?H\d{3,4}|NCIH\d{3,4}|PC-?9|HeLa|Jurkat|K-?562|Ramos|Raji)\b", re.I)
SERVICE_KWS = {
    "biochemical_ic50": r"biochemical|adp-?glo|htrf|kinase assay|ic50",
    "intact_ms": r"intact ?mass|intact ?ms|hrms|covalent binding|deconvolution",
    "kinetics": r"kinact|residence time|k[_ ]?off|k[_ ]?on|kd\b|binding kinetic",
    "cell_proliferation": r"cell prolifer|anti-?prolif|gi50|cell viability",
    "adme": r"\badme\b|caco-?2|microsom|clearance|permeability|ppb|half-?life",
    "pk": r"\bpk\b|pharmacokinetic|cmax|auc|bioavailab",
    "protein_production": r"protein (?:expression|production|purificat)|construct|his-tag",
    "synthesis": r"synthesis|custom synth|resynth|medchem|scale-?up",
    "structure": r"crystal|co-?crystal|structure determination|x-?ray",
    "in_vivo": r"xenograft|cdx\b|pdx\b|in-?vivo|tgi\b|efficacy study",
}
MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")

# --- triage ---------------------------------------------------------------
_NOISE = re.compile(r"webinar|newsletter|unsubscribe|no-?reply|ramp\b|openai|credits|"
                    r"podcast|register now|thank you for attending|verify your email|"
                    r"your interest in|application (?:status|approved)|forum", re.I)
_ACTION = re.compile(r"quote|quotation|proposal|invoice|purchase order|\bpo\b|report|"
                     r"results?|data|weekly update|question|please|could you|shipment|"
                     r"cda|msa|agreement|docusign|signature", re.I)


def triage(subject: str, body: str) -> str:
    t = f"{subject}\n{body}"
    if _NOISE.search(t) and not _ACTION.search(subject):
        return "noise"
    if _ACTION.search(t):
        return "actionable"
    return "fyi"


# --- classify -------------------------------------------------------------
def classify(subject: str, body: str, from_domain: str) -> str:
    t = f"{subject}\n{body}".lower()
    if re.search(r"\binvoice\b|remittance|net ?30|amount due", t):
        return "invoice"
    if re.search(r"\bquot\w+|\bproposal\b|pricing|statement of work|\bsow\b", t):
        return "quote"
    if re.search(r"weekly update|project update|progress", t):
        return "project_update"
    if re.search(r"\bcda\b|\bmsa\b|\bnda\b|docusign|agreement|non-?disclosure", t):
        return "contract"
    if re.search(r"ship|aliquot|transfer|tracking|fedex|courier|material", t):
        return "logistics"
    if re.search(r"report|results?|assay data|ic50 of|deconvolution|% inhibition", t):
        return "cro_data"
    if re.search(r"introduc|capabilit|cell line list|services|our (?:assays|platform)|catalog", t):
        return "vendor_capability"
    if "?" in subject or re.search(r"\bcan you\b|could you|do you (?:offer|have|test)|question", t):
        return "query"
    return "other"


# --- decision state -------------------------------------------------------
def decision_state(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(approved|confirmed|signed|agreed|accepted|will proceed|go ahead|"
                 r"please proceed|completed)\b", t):
        return "agreed"
    if re.search(r"\b(propos|could|might|considering|thinking|maybe|draft|tentative|"
                 r"if (?:you|we)|would like to)\b", t):
        return "under_consideration"
    return "proposed"


def vendor_of(from_addr: str) -> str | None:
    m = re.search(r"@([\w.\-]+)", from_addr or "")
    return VENDOR_BY_DOMAIN.get(m.group(1).lower()) if m else None


# --- agents ---------------------------------------------------------------
def _services(text: str) -> list[str]:
    return [name for name, pat in SERVICE_KWS.items() if re.search(pat, text, re.I)]


def extract_vendor_capability(vendor: str, text: str) -> list[dict]:
    """Vendor menu → facts (cell lines, services). Marked 'agreed' — a vendor's
    stated capability is a fact about the world, not a pending decision."""
    obs = []
    for cl in sorted({m.group(0).upper() for m in CELL_LINE_RE.finditer(text)}):
        obs.append({"subject_type": "vendor", "subject_key": vendor,
                    "predicate": "tests_cell_line", "value": cl,
                    "decision_state": "agreed", "confidence": 0.85})
    for svc in _services(text):
        obs.append({"subject_type": "vendor", "subject_key": vendor,
                    "predicate": "offers_service", "value": svc,
                    "decision_state": "agreed", "confidence": 0.85})
    return obs


def extract_quote(vendor: str, text: str) -> dict:
    amounts = [float(a.replace(",", "")) for a in MONEY_RE.findall(text)]
    total = max(amounts) if amounts else None
    return {"vendor": vendor, "services": _services(text), "amounts": amounts,
            "total": total, "cell_lines": sorted({m.group(0).upper()
                                                   for m in CELL_LINE_RE.finditer(text)})}


def extract_cro_data(text: str) -> dict:
    # crude assay-row capture: "<assay> ... <value> nM/%"
    rows = re.findall(r"(IC50|EC50|Kd|Ki|GI50|Kinact|MRT|TGI|% ?inhibition)[^\n]{0,40}?"
                      r"([\d.]+)\s*(nM|uM|%|hr|/min)", text, re.I)
    return {"assays": [{"type": r[0], "value": r[1], "units": r[2]} for r in rows][:20],
            "services": _services(text)}


# --- unified entry --------------------------------------------------------
def extract(program_id: str, email, conn=None) -> dict:
    """Triage → classify → agent. Returns doc_type, extraction, observations, analysis.
    Pass `conn` during bulk ingest so alias learning shares the transaction."""
    subj, body = email.subject or "", email.full_text
    tri = triage(subj, body)
    from_dom = (re.search(r"@([\w.\-]+)", email.email_from or "") or [None, ""])
    from_dom = from_dom.group(1).lower() if hasattr(from_dom, "group") else ""
    if tri == "noise":
        return {"triage": tri, "doc_type": "noise", "extraction": {}, "observations": [],
                "analysis": {"note": "Filtered as non-actionable."}}
    doc_type = classify(subj, body, from_dom)
    vendor = vendor_of(email.email_from)
    obs, extraction, analysis = [], {}, {}

    # A vendor demonstrates a capability whenever it names a cell line / service in
    # ANY email (quote, data, capability doc) — harvest those facts broadly so the
    # knowledge base can answer "which cell lines can <vendor> test?".
    if vendor:
        obs += extract_vendor_capability(vendor, body)
    vendor = vendor or "Unknown vendor"

    if doc_type == "vendor_capability":
        extraction = {"vendor": vendor, "cell_lines": [o["value"] for o in obs
                      if o["predicate"] == "tests_cell_line"],
                      "services": [o["value"] for o in obs if o["predicate"] == "offers_service"]}
        analysis = {"recommendation": "acknowledge",
                    "note": f"Logged {vendor} capabilities to the knowledge base."}
    elif doc_type == "quote":
        extraction = extract_quote(vendor, body)
        ds = decision_state(body)
        if extraction["total"]:
            obs.append({"subject_type": "vendor", "subject_key": vendor,
                        "predicate": "quoted_amount", "value": str(extraction["total"]),
                        "decision_state": ds, "confidence": 0.8})
        analysis = {"recommendation": "review_quote", "decision_state": ds,
                    "note": f"{vendor} quote"
                            + (f" ~${extraction['total']:,.0f}" if extraction["total"] else "")}
    elif doc_type == "cro_data":
        extraction = extract_cro_data(body)
        analysis = {"recommendation": "review_data",
                    "note": f"{len(extraction['assays'])} assay rows detected."}
    elif doc_type == "query":
        extraction = {"question": subj}
        analysis = {"recommendation": "draft_reply", "note": "Query — draft a response."}
    else:
        analysis = {"recommendation": "acknowledge", "note": f"{doc_type} from {vendor}."}

    # learn molecule aliases declared inline (best-effort; share the ingest txn)
    try:
        identity.learn_inline_aliases(program_id, body, conn=conn)
    except Exception:
        pass
    return {"triage": tri, "doc_type": doc_type, "vendor": vendor,
            "extraction": extraction, "observations": obs, "analysis": analysis}
