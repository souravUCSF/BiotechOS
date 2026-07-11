"""Data-QC processor (v1) — the DISPATCHER.

When a DATA email is detected, this runs once (at ingest) and produces a stored,
traceable analysis. It (1) extracts the vendor's datasets and TYPES each one
(dose_response / adme / kinetics / …), (2) dispatches each to its analyzer
(analyzers registry), and (3) aggregates the QC steps, charts, deposition rows and
an overall verdict. The user later reviews the stored result and approves the
deposition — never recomputed on view.

The analysis math lives in the analyzers (deterministic/scipy); the LLM only reads
and types the data.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from ...config import MODEL_ARTIFACTS
from .. import llm
from .analyzers import dispatch, DATA_TYPES


class PanelItem(BaseModel):
    property: str
    value: float | None = None
    units: str | None = None
    # each ADME property has its OWN biological system (microsomes vs plasma vs Caco-2)
    system_type: str | None = None      # subcellular|matrix|cell_line|...
    system: str | None = None           # human liver microsomes | plasma | Caco-2 | ...


class Dataset(BaseModel):
    data_type: str = Field(default="generic_numeric",
                           description="one of: " + ", ".join(DATA_TYPES))
    compound: str = Field(description="compound code exactly as written")
    target: str | None = Field(default=None, description="MOLECULAR target (TGTA/TGTB); null for ADME/PK")
    modality: str | None = None
    standard_type: str | None = Field(default=None, description="IC50|Kd|CLint|Papp|Cmax|…")
    reported_value: float | None = Field(default=None, description="the value the VENDOR reports")
    units: str | None = None
    # biological system (replaces cell_line): where the measurement was made
    system_type: str | None = Field(default=None, description="protein|cell_line|subcellular|matrix|organism|tissue")
    system: str | None = Field(default=None, description="HEK293|TGTA|human liver microsomes|plasma|nude mouse")
    species: str | None = None
    conditions: dict | None = Field(default=None, description="{test_conc,incubation} | {dose,dose_units,route}")
    concentrations: list[float] = Field(default_factory=list,
                                        description="dose_response: raw x (concentrations) if a table is present")
    responses: list[float] = Field(default_factory=list,
                                   description="dose_response: raw y (% response) aligned to concentrations")
    panel: list[PanelItem] = Field(default_factory=list,
                                   description="adme: the compound's ADME properties, one item each")
    note: str | None = None


class DataExtract(BaseModel):
    vendor_summary: str = ""
    datasets: list[Dataset] = []


_SYS = (
    "You read ONE data email + attachments from a biotech CRO and extract EVERY reported result as a "
    "typed DATASET. Results may be in a TABLE, a slide/figure caption, OR stated INLINE IN PROSE "
    "(e.g. 'the compound shows a residence time of 69 minutes', 'koff = 0.002 /min', 'IC50 was "
    "12 nM') — extract those narrative values too, not just tables. For EACH dataset set `data_type`:\n"
    "- dose_response: a concentration-response (IC50/EC50). Include raw `concentrations`+`responses` "
    "arrays only if a dose-response table is present.\n"
    "- adme: ADME properties (CLint, permeability/Papp, solubility, %F, PPB, half-life, microsomal "
    "stability) — put each in `panel` as {property, value, units}.\n"
    "- kinetics: binding/residence kinetics — residence time (min), koff/k_off (1/s or 1/min), kon, "
    "kinact, k_obs, target half-life. standard_type = the quantity (e.g. 'residence_time', 'koff').\n"
    "- intact_ms: mass / DAR.  - selectivity: target×compound panel.  - pk: concentration-time.  "
    "- thermal_shift: Tm / melt curve.  - generic_numeric: any other single value+unit result.\n"
    "For each give the compound code EXACTLY as written (e.g. PH-PGMA-L2-2026-03B-2-0), standard_type, "
    "the vendor's reported_value + units. Decompose the biological context into THREE orthogonal fields: "
    "`target` = the MOLECULAR target the compound acts on (TGTB/TGTA) or null (ADME/PK/cytotox); "
    "`system_type`+`system` = WHERE it was measured — protein (recombinant TGTA), cell_line (HEK293), "
    "subcellular (human liver microsomes), matrix (plasma), organism (nude mouse) — put the cell/prep/"
    "matrix/animal in `system`, NEVER in `target`; `species` (human/mouse/rat); `conditions` = exposure/"
    "dosing JSON ({test_conc,incubation,competition} in-vitro | {dose,dose_units,route,regimen} in-vivo). "
    "For an ADME `panel`, set each item's own system (microsomal stability→subcellular/microsomes, "
    "PPB→matrix/plasma, Papp→cell_line/Caco-2). Only include REAL measured "
    "values present in the text — never invent numbers or read a planned/assignment matrix (X = "
    "planned, not a result). If the email says a result FAILED QC or is pending, do NOT emit a value "
    "for it.\n"
    "IMPORTANT: mark reference/QC CONTROL compounds with `is_control: true` — these are known assay "
    "standards used to validate the run (e.g. Atenolol, Digoxin, Minoxidil, Propranolol, Warfarin, "
    "Verapamil, or anything the report labels 'control'/'reference'). They are NOT our test compounds. "
    "PRESERVE value qualifiers: if a value is reported as '<0.00972' or '>27' (below/above limit of "
    "detection), set `relation` to '<' or '>' and put the number in value. Give a one-line "
    "`vendor_summary`. Return {vendor_summary, datasets:[...]}; empty only if there are truly no "
    "numeric results."
)


_SCHEMA_HINT = ('{"vendor_summary": str, "datasets": [{"data_type": one of '
                + str(DATA_TYPES) + ', "compound": str, "is_control": bool, "target": str|null, '
                '"modality": str|null, "standard_type": str|null, "reported_value": number|null, '
                '"relation": "<"|">"|null, "units": str|null, '
                '"system_type": "protein"|"cell_line"|"subcellular"|"matrix"|"organism"|"tissue"|null, '
                '"system": str|null, "species": str|null, "conditions": object|null, '
                '"concentrations": [number], "responses": [number], '
                '"panel": [{"property": str, "value": number, "relation": "<"|">"|null, "units": str, '
                '"system_type": str|null, "system": str|null}], '
                '"note": str|null}]}')

_MEDIA = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
          ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
_OFFICE = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".odt", ".ods", ".odp"}


def real_attachments(source_ref: str | None) -> list:
    """The original binary attachment files in the real datastore for a corpus doc
    (the anonymized corpus keeps only text; binaries live under DATASTORE_ROOT)."""
    from pathlib import Path
    from ...config import CORPUS_DIR, DATASTORE_ROOT
    if not source_ref:
        return []
    try:
        rel = Path(source_ref).relative_to(CORPUS_DIR)
    except ValueError:
        return []
    ad = Path(DATASTORE_ROOT) / rel / "attachments"
    if not ad.exists():
        return []
    return sorted(f for f in ad.iterdir() if f.is_file() and not f.name.startswith("~$"))


def real_attachments_anon(program_id: str, source_ref: str | None) -> dict:
    """Real binaries keyed by their ANONYMIZED filename, so they match the (anonymized)
    attachment names the corpus/UI knows (a real 'TGTA-TGTA.pdf' → 'TGTB-TGTA.pdf')."""
    from ...config import org_for_program
    from ...ingest.anonymize import anonymize_text, _profile
    prof = _profile(org_for_program(program_id))
    return {anonymize_text(f.name, prof): f for f in real_attachments(source_ref)}


def _find_soffice() -> str | None:
    """Locate the LibreOffice CLI — on PATH, or inside the macOS/Linux app bundle."""
    import shutil as _sh
    from pathlib import Path
    hit = _sh.which("soffice") or _sh.which("libreoffice")
    if hit:
        return hit
    for p in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
              "/usr/lib/libreoffice/program/soffice", "/opt/libreoffice/program/soffice"):
        if Path(p).exists():
            return p
    return None


def can_read_native(path) -> bool:
    """True if Claude can read this file natively right now (PDF/image directly, or an
    Office file when LibreOffice is installed to convert it)."""
    ext = path.suffix.lower()
    if ext in _MEDIA:
        return True
    if ext in _OFFICE:
        return _find_soffice() is not None
    return False


def _to_document(path) -> tuple[str, bytes] | None:
    """(media_type, bytes) for a file Claude can read natively; Office is converted to
    PDF via LibreOffice if available. None if unsupported/unconvertible."""
    ext = path.suffix.lower()
    if ext in _MEDIA:
        return _MEDIA[ext], path.read_bytes()
    if ext in _OFFICE:
        import subprocess as _sp
        import tempfile as _tf
        soffice = _find_soffice()
        if not soffice:
            return None                     # needs LibreOffice; caller reports this
        with _tf.TemporaryDirectory() as td:
            _sp.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", td, str(path)],
                    check=False, capture_output=True, timeout=120)
            pdfs = list(__import__("pathlib").Path(td).glob("*.pdf"))
            if pdfs:
                return "application/pdf", pdfs[0].read_bytes()
    return None


def _normalize_datasets(obj: dict) -> tuple[str, list]:
    vendor_summary = str(obj.get("vendor_summary") or "")
    datasets = []
    for d in obj.get("datasets") or []:
        if not isinstance(d, dict) or not d.get("compound"):
            continue
        d.setdefault("data_type", "generic_numeric")
        for k in ("concentrations", "responses", "panel"):
            if not isinstance(d.get(k), list):
                d[k] = []
        datasets.append(d)
    return vendor_summary, datasets


def _extract_text(program_id: str, doc_row, api_key) -> dict:
    """Extract from the ANONYMIZED text (safe: nothing new sent to the API)."""
    from ..attachments import parse_attachments
    raw = doc_row["raw_text"] or ""
    atts = "\n".join(f"[attachment: {fn}]\n{txt}" for fn, txt in parse_attachments(raw))
    user = f"SUBJECT: {doc_row['subject'] or ''}\n\n{raw[:4000]}\n\n{atts[:8000]}"
    obj, _ = llm.json_object(model=MODEL_ARTIFACTS, system=_SYS + "\n\nJSON shape:\n" + _SCHEMA_HINT,
                             user=user, fallback={"vendor_summary": "", "datasets": []},
                             api_key=api_key, max_tokens=4096, timeout=120)
    return obj


def _extract_native(program_id: str, doc_row, api_key, wanted: list | None) -> tuple[dict, list, list]:
    """Send the REAL attachment binaries to Claude natively (reads figures/plots), then
    re-anonymize the extracted identities. Returns (obj, sent_files, skipped)."""
    from ...config import org_for_program
    from ...ingest.anonymize import anonymize_text, _profile
    by_anon = real_attachments_anon(program_id, doc_row["source_ref"])  # {anon_name: real Path}
    items = [(an, p) for an, p in by_anon.items() if not wanted or an in wanted]
    blocks, sent, skipped = [], [], []
    for anon_name, f in items:
        doc = _to_document(f)
        if doc is None:
            skipped.append(anon_name)       # report using the anonymized name
            continue
        blocks.append((doc[0], doc[1], anon_name))
        sent.append(anon_name)
    if not blocks:
        return {"vendor_summary": "", "datasets": []}, sent, skipped
    user = ("Extract every reported result from the attached file(s) as typed datasets. "
            "Read tables AND figures/plots (e.g. dose-response curves, mass spectra).")
    obj, _ = llm.document_json(model=MODEL_ARTIFACTS, system=_SYS + "\n\nJSON shape:\n" + _SCHEMA_HINT,
                              user=user, files=blocks, fallback={"vendor_summary": "", "datasets": []},
                              api_key=api_key, max_tokens=4096, timeout=180)
    # re-anonymize identities that came from the real binary before we store anything
    prof = _profile(org_for_program(program_id))
    obj["vendor_summary"] = anonymize_text(obj.get("vendor_summary") or "", prof)
    for d in obj.get("datasets") or []:
        for k in ("compound", "target", "standard_type", "modality", "system", "note"):
            if isinstance(d.get(k), str):
                d[k] = anonymize_text(d[k], prof)
        for it in d.get("panel") or []:
            if isinstance(it.get("property"), str):
                it["property"] = anonymize_text(it["property"], prof)
    return obj, sent, skipped


def analyze(program_id: str, doc_row, api_key: str | None = None,
            source: str = "text", files: list | None = None) -> dict:
    """Extract + type + QC one data email → the full analysis dict. `source`:
    'text' = anonymized corpus text (default, safe); 'native' = send the real
    attachment binaries to Claude (reads figures) then re-anonymize the results."""
    read_source, sent, skipped = "anonymized text", [], []
    if source == "native":
        obj, sent, skipped = _extract_native(program_id, doc_row, api_key, files)
        read_source = ("native: " + ", ".join(sent)) if sent else "native (no readable binary)"
    else:
        obj = _extract_text(program_id, doc_row, api_key)
    vendor_summary, datasets = _normalize_datasets(obj)

    by_type: dict = {}
    for d in datasets:
        by_type[d["data_type"]] = by_type.get(d["data_type"], 0) + 1
    qc_steps = [{"step": "Read source", "status": "warn" if (source == "native" and not sent) else "ok",
                 "detail": (f"read {read_source}"
                            + (f"; re-anonymized before storing" if source == "native" and sent else "")
                            + (f"; could not read: {', '.join(skipped)} (needs LibreOffice/unsupported)"
                               if skipped else ""))},
                {"step": "Detect + extract", "status": "ok",
                 "detail": f"{len(datasets)} dataset(s): "
                           + (", ".join(f"{n}× {t}" for t, n in by_type.items()) or "none")}]
    controls = [d for d in datasets if d.get("is_control")]
    if controls:
        qc_steps.append({"step": "Assay controls", "status": "ok",
                         "detail": f"{len(controls)} reference control(s) present "
                                   f"({', '.join(d['compound'] for d in controls)}) — validate the run; "
                                   f"not deposited to the compound DB"})
    charts, deposition = [], []
    for d in datasets:
        if d.get("is_control"):
            continue                      # controls validate the assay; never deposited
        out = dispatch(d)                 # → right analyzer for this data type
        qc_steps += out["qc_steps"]
        if out.get("chart"):
            charts.append(out["chart"])
        # stamp the dataset's biological system + conditions onto its deposition rows
        # (the type analyzers don't carry them); ADME panel items keep their own system.
        for dep in out.get("deposition", []):
            dep.setdefault("system_type", d.get("system_type"))
            dep.setdefault("system", d.get("system"))
            dep.setdefault("species", d.get("species"))
            dep.setdefault("conditions", d.get("conditions"))
        deposition += out.get("deposition", [])

    n_fail = sum(1 for s in qc_steps if s["status"] == "fail")
    n_warn = sum(1 for s in qc_steps if s["status"] == "warn")
    verdict = "fail" if n_fail else ("warn" if n_warn else "pass")
    return {
        "vendor_summary": vendor_summary,
        "datasets": datasets,
        "qc_steps": qc_steps,
        "charts": charts,
        "verdict": verdict,
        "deposition": deposition,
        "read_source": read_source,
        "sent_files": sent,
        "counts": {"datasets": len(datasets), "by_type": by_type,
                   "warnings": n_warn, "discrepancies": n_fail},
    }


def analyze_and_store(conn, program_id: str, doc_row, api_key: str | None = None,
                      redo: bool = False, source: str = "text", files: list | None = None) -> int | None:
    doc_id = doc_row["id"]
    existing = conn.execute("SELECT id FROM data_analyses WHERE document_id=?", (doc_id,)).fetchone()
    if existing and not redo:
        return existing["id"]
    a = analyze(program_id, doc_row, api_key=api_key, source=source, files=files)
    summary = (a["vendor_summary"] or "")[:200]
    if existing:
        conn.execute("UPDATE data_analyses SET status='pending', verdict=?, summary=?, analysis_json=? "
                     "WHERE id=?", (a["verdict"], summary, json.dumps(a), existing["id"]))
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO data_analyses(program_id,document_id,status,verdict,summary,analysis_json) "
        "VALUES (?,?, 'pending', ?, ?, ?)", (program_id, doc_id, a["verdict"], summary, json.dumps(a)))
    return cur.lastrowid


def approve(conn, program_id: str, analysis_id: int) -> dict:
    """Deposit the QC'd measurements into the assay database and mark approved."""
    from .. import identity
    row = conn.execute("SELECT * FROM data_analyses WHERE id=? AND program_id=?",
                       (analysis_id, program_id)).fetchone()
    if not row:
        raise ValueError("analysis not found")
    a = json.loads(row["analysis_json"] or "{}")
    deposited = 0
    for d in a.get("deposition", []):
        if d.get("value") is None:
            continue
        r = identity.resolve_molecule(program_id, d["molecule"], create=True, conn=conn)
        mid = r.get("molecule_id")
        if not mid:
            continue
        conn.execute(
            "INSERT INTO assays(program_id,molecule_id,modality,target,standard_type,value,units,"
            "reported_value,raw_points,system_type,system,species,conditions,source_document_id,flags,source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'cro')",
            (program_id, mid, d.get("modality"), d.get("target"), d.get("standard_type"),
             d.get("value"), d.get("units"), d.get("reported_value"),
             json.dumps(d["raw_points"]) if d.get("raw_points") else None,
             d.get("system_type"), d.get("system"), d.get("species"),
             json.dumps(d["conditions"]) if d.get("conditions") else None, row["document_id"],
             json.dumps(d.get("flags") or [])))
        deposited += 1
    conn.execute("UPDATE data_analyses SET status='approved' WHERE id=?", (analysis_id,))
    return {"deposited": deposited, "status": "approved"}


def backfill(program_id: str, api_key: str | None = None, limit: int | None = None) -> dict:
    """Run the data-QC processor over data emails lacking an analysis (no re-ingest)."""
    from ...state import db
    conn = db.connect()
    docs = conn.execute(
        "SELECT * FROM documents WHERE program_id=? AND direction='inbound' AND doc_type='data' "
        "AND id NOT IN (SELECT IFNULL(document_id,-1) FROM data_analyses) ORDER BY sent_at DESC",
        (program_id,)).fetchall()
    if limit:
        docs = docs[:limit]
    n = 0
    for d in docs:
        with conn:
            analyze_and_store(conn, program_id, d, api_key=api_key)
        n += 1
    conn.close()
    return {"analyzed": n}
