"""Attachment data extraction → surfaced for approval.

Attachments are already extracted to text and merged into `documents.raw_text`
(with `--- attachment: <filename> ---` markers). This module pulls the real
*data* out of those attachments and stages it into the existing data-approval
flow (a `cro_data` / `review_data` inbox item), so approving it loads the assay
results onto the molecule (creating the CLO compound if new) via
`engine.inbox._approve_data_from_extraction`.

Cost policy (per product decision):
- xlsx/xls/csv/pptx  → structured data → LLM extraction.
- pdf                → most are capability/sales brochures ("fluff"). Gate on a
  cheap data-vs-fluff classifier FIRST; only run the LLM on data-bearing PDFs.
- docx/other         → classify like PDF.
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel

from ..config import DEMO_PROGRAM_ID, MODEL_ARTIFACTS
from ..state import db
from . import llm
from .extract import vendor_of

_ATT_RE = re.compile(r"--- attachment: (.+?) ---\n(.*?)(?=\n--- attachment: |\Z)", re.S)

# extensions that are (almost) always structured data
_DATA_EXT = {"xlsx", "xls", "csv"}
_DECK_EXT = {"pptx", "ppt"}

# signals that an attachment carries real assay/result data
_DATA_SIG = re.compile(
    r"ic50|ec50|gi50|\bkd\b|\bki\b|kinact|adp-?glo|intact ?ms|htrf|% ?inhibition|"
    r"residence time|k[_ ]?off|labeling|competition|\bnM\b|\buM\b|µM|/min|"
    r"CLO[-_]?\d|BTX-?\d|PH-[A-Z]{2,}", re.I)
# marketing/capability fluff
_FLUFF = re.compile(
    r"brochure|capabilit|our services|about us|company overview|leading provider|"
    r"integrated drug discovery|unlocking potential|contact us|newsletter|"
    r"why choose|value proposition", re.I)
# filenames that are business docs, never assay data (handled by other flows)
_FLUFF_NAME = re.compile(
    r"invoice|quotation|\bquote\b|\bpo[_\- ]?\d|purchase.?order|\bmsa\b|\bnda\b|"
    r"non.?disclosure|mutual.?disclosure|agreement|template|brochure|datasheet|"
    r"data.?sheet|capabilit|introduction|\bcv\b|resume", re.I)
# filenames that strongly indicate real results/data
_DATA_NAME = re.compile(
    r"\bqc\b|result|assay|\bdata\b|report|profiling|ic50|kinact|intact.?ms|"
    r"adp.?glo|kinetic|caco|potency|selectivity|xenograft|\bpk\b", re.I)


def parse_attachments(raw_text: str) -> list[tuple[str, str]]:
    """(filename, text) for each attachment embedded in a document's raw_text."""
    return [(m.group(1).strip(), m.group(2).strip()) for m in _ATT_RE.finditer(raw_text or "")]


def classify(filename: str, text: str) -> str:
    """'data' | 'fluff' | 'empty' — decides whether the LLM should read it."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not text or len(text.strip()) < 20:
        return "empty"
    # filename shortcuts: business docs are never assay data; result-named files are
    if _FLUFF_NAME.search(filename):
        return "fluff"
    if ext in _DATA_EXT:
        return "data"
    data_hits = len(_DATA_SIG.findall(text))
    name_data = bool(_DATA_NAME.search(filename))
    if ext in _DECK_EXT:
        return "data" if (data_hits >= 1 or name_data) else (
            "fluff" if _FLUFF.search(text[:1000]) else "data")
    # pdf / docx / other: 'data' on compound+value signals, or a result-named file
    has_code = bool(re.search(r"CLO[-_]?\d|CL0[-_]?\d|BTX-?\d|PH-[A-Z]{2,}", text, re.I))
    if (has_code and data_hits >= 2) or data_hits >= 5 or (name_data and data_hits >= 1):
        return "data"
    return "fluff"


# --- LLM extraction -------------------------------------------------------
class _Assay(BaseModel):
    molecule: str                       # compound code (e.g. CLO-00002)
    modality: str = "biochemical_ic50"  # biochemical_ic50|intact_ms|kinetics|cellular_antiprolif|adme|selectivity
    target: str | None = None           # TGTA/TGTA | TGTB | ...
    standard_type: str | None = None    # IC50|Kd|kinact|% labeling|...
    value: float | None = None
    units: str | None = None
    cell_line: str | None = None
    note: str | None = None


class _Extract(BaseModel):
    assays: list[_Assay] = []


_SYS = (
    "You read ONE extracted attachment (an Excel/PPT/CSV/PDF report from a biotech CRO) and pull out "
    "structured assay RESULTS as rows. Each row = one measurement for one compound. Use the compound "
    "code exactly as written (CLO-00002, CLO_RQ-0004, BTX-1050). modality ∈ biochemical_ic50|intact_ms|"
    "kinetics|cellular_antiprolif|adme|selectivity. target is the protein (TGTA/TGTA, TGTB). "
    "standard_type is the measured quantity (IC50, Kd, kinact, % labeling, % inhibition). value is the "
    "NUMBER, units the unit (nM, uM, %, /min). Only include rows with a real measured value present in "
    "the text — do NOT invent values or infer from an assay-assignment matrix (X marks = planned, not a "
    "result). Return JSON {assays:[...]}; empty if the attachment has no numeric results.")


def extract_rows(filename: str, text: str, api_key: str | None = None) -> list[dict]:
    """LLM → assay-result rows from one data attachment ([] on no key / no data)."""
    res, _ = llm.structured(model=MODEL_ARTIFACTS, system=_SYS,
                            user=f"ATTACHMENT: {filename}\n\n{text[:8000]}",
                            schema=_Extract, fallback=_Extract(), api_key=api_key,
                            max_tokens=4096)
    return [a.model_dump() for a in res.assays if a.molecule and a.value is not None]


# --- stage into the existing data-approval flow ---------------------------
def stage_document(conn, program_id: str, doc_id: int, subject: str, email_from: str,
                   raw_text: str, api_key: str | None = None,
                   stats: dict | None = None) -> int:
    """Classify + extract one document's attachments; if any assay rows come out,
    stage (replace) a `review_data` inbox item for approval. Returns rows staged.
    Fluff attachments are skipped before any LLM call."""
    vendor = vendor_of(email_from) or "Unknown vendor"
    doc_rows: list[dict] = []
    for fn, text in parse_attachments(raw_text):
        cls = classify(fn, text)
        if stats is not None:
            stats["attachments"] = stats.get("attachments", 0) + 1
            stats["by_class"][cls] = stats["by_class"].get(cls, 0) + 1
            if cls == "fluff":
                stats["fluff"] = stats.get("fluff", 0) + 1
        if cls != "data":
            continue
        if stats is not None:
            stats["data_attachments"] = stats.get("data_attachments", 0) + 1
        for row in extract_rows(fn, text, api_key=api_key):
            row["_attachment"] = fn
            doc_rows.append(row)
    if not doc_rows:
        return 0
    # replace any prior auto-staged extraction item for this document (idempotent)
    conn.execute(
        "DELETE FROM inbox_items WHERE program_id=? AND document_id=? AND kind='attachment_data'",
        (program_id, doc_id))
    payload = {
        "document_id": doc_id, "vendor": vendor, "subject": subject, "email_from": email_from,
        "extraction": {"assays": doc_rows},
        "analysis": {"note": f"{len(doc_rows)} assay result(s) extracted from attachments."},
    }
    proposed = {"action": "review_data", "label": "Review extracted data → load to molecule",
                "note": f"{len(doc_rows)} rows from {vendor} attachments"}
    conn.execute(
        "INSERT INTO inbox_items(program_id,kind,title,summary,payload,proposed_action,"
        "document_id,doc_type,analysis,extraction_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (program_id, "attachment_data", f"Extracted assay data — {subject}",
         f"{len(doc_rows)} assay rows from {vendor} attachments",
         json.dumps(payload), json.dumps(proposed), doc_id, "cro_data",
         json.dumps(payload["analysis"]), json.dumps(payload["extraction"])))
    return len(doc_rows)


# --- general (non-assay) knowledge extraction -----------------------------
# Invoices, contracts, quotes, capability brochures and datasheets aren't assay
# results but ARE biotech knowledge. This path pulls typed facts/relationships out
# of them and stores them in the same world model (entities, edges, facts) or the
# decisions queue for commitments.
class _KItem(BaseModel):
    kind: str = "other"          # capability|contract_term|invoice|pricing|reagent_spec|relationship|other
    subject_type: str = "vendor" # vendor|contract|molecule|assay|cell_line|reagent|program|person
    subject_key: str
    predicate: str
    value: str | None = None
    target_type: str | None = None   # set for a relationship (edge)
    target_key: str | None = None
    store_as: str = "fact"           # fact (reference knowledge) | decision (a commitment)
    confidence: float = 0.7
    rationale: str = ""


class _Knowledge(BaseModel):
    items: list[_KItem] = []


_K_SYS = (
    "You read ONE non-assay attachment from a biotech CRO (an invoice, contract/MSA/NDA, quote, "
    "capability brochure, or reagent datasheet) and extract structured KNOWLEDGE as items. Types: "
    "capability (a vendor offers a service/assay/cell-line — subject=vendor, predicate=offers_service|"
    "tests_cell_line, value=the service/line), contract_term (parties, effective_date, expiry, scope "
    "— subject=vendor or contract id), invoice (subject=vendor; predicate=invoice_number|invoice_amount|"
    "due_date|po_number; value=the value), pricing (subject=vendor, predicate=list_price for a service), "
    "reagent_spec (subject=the protein/reagent, predicate=molecular_weight|purity|concentration|construct). "
    "Use store_as='decision' ONLY for a financial/legal commitment that a human should confirm (an "
    "invoice amount due, a contract signed, a price agreed); everything descriptive is store_as='fact'. "
    "For a relationship set target_type+target_key (e.g. vendor offers_service→assay). Keep vendor/"
    "protein names as written. Return JSON {items:[...]}; empty if nothing substantive.")


def extract_knowledge(filename: str, text: str, api_key: str | None = None) -> list[dict]:
    res, _ = llm.structured(model=MODEL_ARTIFACTS, system=_K_SYS,
                            user=f"ATTACHMENT: {filename}\n\n{text[:8000]}",
                            schema=_Knowledge, fallback=_Knowledge(), api_key=api_key,
                            max_tokens=4096)
    return [k.model_dump() for k in res.items if k.subject_key and k.predicate]


def stage_knowledge(conn, program_id: str, doc_id: int, raw_text: str,
                    api_key: str | None = None, event_at: str | None = None,
                    stats: dict | None = None) -> int:
    """Extract knowledge from a doc's NON-assay attachments and store it: reference
    items become entities/edges/facts directly; commitments go to the decisions
    queue for approval. Returns items stored."""
    from . import graph, decisions as D
    from .corpus import store as corpus_store
    n = 0
    for fn, text in parse_attachments(raw_text):
        if classify(fn, text) != "fluff":   # 'data' handled by assay path; skip 'empty'
            continue
        for it in extract_knowledge(fn, text, api_key=api_key):
            st, sk, pred, val = it["subject_type"], it["subject_key"], it["predicate"], it.get("value")
            if it.get("store_as") == "decision":
                D.insert_suspected(conn, program_id, {
                    "kind": it.get("kind", "other"), "subject_type": st, "subject_key": sk,
                    "predicate": pred, "value": val, "confidence": it.get("confidence", 0.6),
                    "rationale": (it.get("rationale") or "") + f" [attachment: {fn}]"},
                    doc_id, event_at)
                n += 1
                continue
            sid = graph.resolve_entity(conn, program_id, st, sk, source_document_id=doc_id)
            if it.get("target_type") and it.get("target_key"):
                tid = graph.resolve_entity(conn, program_id, it["target_type"], it["target_key"],
                                           source_document_id=doc_id)
                graph.add_edge(conn, program_id, sid, pred, tid, source_document_id=doc_id,
                               confidence=it.get("confidence", 0.7), event_at=event_at)
            else:
                oc = conn.execute(
                    "INSERT INTO observations(program_id,subject_type,subject_key,predicate,value,"
                    "source_document_id,decision_state,confidence) VALUES (?,?,?,?,?,?, 'agreed', ?)",
                    (program_id, st, sk, pred, val, doc_id, it.get("confidence", 0.7)))
                corpus_store._promote(conn, program_id, oc.lastrowid,
                                      {"subject_type": st, "subject_key": sk,
                                       "predicate": pred, "value": val}, event_at)
            n += 1
    if stats is not None and n:
        stats["knowledge_items"] = stats.get("knowledge_items", 0) + n
    return n


def backfill_knowledge(program_id: str = DEMO_PROGRAM_ID, limit: int | None = None,
                       api_key: str | None = None) -> dict:
    """Extract general knowledge from all non-assay attachments (invoices, contracts,
    quotes, brochures, datasheets) and store it into the world model / decisions."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT id,sent_at,raw_text FROM documents "
        "WHERE program_id=? AND raw_text LIKE '%--- attachment:%' ORDER BY sent_at",
        (program_id,)).fetchall()
    stats = {"documents": 0, "knowledge_items": 0}
    for r in rows:
        if limit and stats["documents"] >= limit:
            break
        stats["documents"] += 1
        with conn:   # commit per document so a long run is resilient to interruption
            stage_knowledge(conn, program_id, r["id"], r["raw_text"] or "",
                            api_key=api_key, event_at=r["sent_at"], stats=stats)
    conn.close()
    return stats


def backfill(program_id: str = DEMO_PROGRAM_ID, limit: int | None = None,
             api_key: str | None = None) -> dict:
    """Scan ALL ingested documents' attachments and stage extraction items for
    approval (no re-ingest). Skips fluff before spending any LLM call."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT id,subject,email_from,raw_text FROM documents "
        "WHERE program_id=? AND raw_text LIKE '%--- attachment:%' ORDER BY sent_at DESC",
        (program_id,)).fetchall()
    stats = {"documents": 0, "attachments": 0, "data_attachments": 0, "fluff": 0,
             "rows_extracted": 0, "items_staged": 0, "by_class": {}}
    with conn:
        for r in rows:
            if limit and stats["documents"] >= limit:
                break
            stats["documents"] += 1
            staged = stage_document(conn, program_id, r["id"], r["subject"] or "",
                                    r["email_from"] or "", r["raw_text"] or "",
                                    api_key=api_key, stats=stats)
            if staged:
                stats["rows_extracted"] += staged
                stats["items_staged"] += 1
    conn.close()
    return stats
