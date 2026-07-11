"""FastAPI app: all routes are program_id-scoped. Day 1 delivers GET /state."""
from __future__ import annotations

import json

import csv
import io
import re

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, FileResponse
from pydantic import BaseModel

from ..config import DEMO_PROGRAM_ID
from ..engine import cfo as cfo_engine
from ..engine import identity as identity_engine
from ..engine import inbox as inbox_engine
from ..engine import structure as structure_engine
from ..engine import tpp as tpp_engine
from ..engine import tpp_builder
from ..integrations import competitive as competitive_engine
from ..state import db

app = FastAPI(title="BiotechOS API")

from ..evals.api import router as evals_router  # noqa: E402
app.include_router(evals_router)


@app.on_event("startup")
def _startup() -> None:
    # apply non-destructive schema migrations to an existing DB on boot so new
    # columns (e.g. fold_settings.target_kind) exist without a data reload.
    db.init_db(reset=False)
    # Ensure the Program B ADC program row exists (its corpus is ingested separately
    # via store.ingest("program-b"); no molecules/TPP yet). Idempotent.
    from ..config import PROGRAM_B_ID
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO programs(id,name,target,anti_target,indication,status)"
            " VALUES (?,?,?,?,?,?)",
            (PROGRAM_B_ID, "Program B", "TGTA", None,
             "TGTA-expressing solid tumors", "active"))
    conn.close()

app.add_middleware(
    CORSMiddleware,
    # Local single-user app reachable via localhost, claw.local, or a LAN IP —
    # allow any origin (no credentials are used).
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Structure-Placeholder", "X-Structure-Label"],
)


def get_conn():
    return db.connect()


# Fields that carry provenance to the source dataset / real compound identity —
# these demo molecules are presented as our own proprietary compounds, so this
# never leaves the backend.
_INTERNAL_ONLY_FIELDS = ("internal_ref", "inchi_key")


def _scrub(mol: dict) -> dict:
    for f in _INTERNAL_ONLY_FIELDS:
        mol.pop(f, None)
    return mol


@app.get("/programs")
def list_programs():
    conn = get_conn()
    rows = db.rows_to_dicts(conn.execute("SELECT * FROM programs").fetchall())
    conn.close()
    return rows


@app.get("/state")
def get_state(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    conn = get_conn()

    program = conn.execute("SELECT * FROM programs WHERE id=?", (program_id,)).fetchone()
    if program is None:
        conn.close()
        raise HTTPException(404, f"unknown program_id {program_id}")

    molecules = db.rows_to_dicts(conn.execute(
        "SELECT * FROM molecules WHERE program_id=? AND held_out=0 ORDER BY id",
        (program_id,),
    ).fetchall())

    mol_ids = [m["id"] for m in molecules]
    assays_by_mol: dict[int, list[dict]] = {mid: [] for mid in mol_ids}
    if mol_ids:
        placeholders = ",".join("?" * len(mol_ids))
        for row in conn.execute(
            f"SELECT * FROM assays WHERE molecule_id IN ({placeholders})", mol_ids
        ).fetchall():
            assays_by_mol[row["molecule_id"]].append(dict(row))

    for m in molecules:
        m["assays"] = assays_by_mol.get(m["id"], [])
        if m.get("adme_json"):
            try:
                m["adme"] = json.loads(m["adme_json"])
            except (TypeError, json.JSONDecodeError):
                m["adme"] = None
        _scrub(m)

    _active = tpp_engine.active_version(conn, program_id)
    tpp_params = db.rows_to_dicts(conn.execute(
        "SELECT * FROM tpp_params WHERE version_id=?", (_active["id"] if _active else -1,)
    ).fetchall())

    inbox = db.rows_to_dicts(conn.execute(
        "SELECT * FROM inbox_items WHERE program_id=? ORDER BY id", (program_id,)
    ).fetchall())

    ledger = db.rows_to_dicts(conn.execute(
        "SELECT * FROM ledger_entries WHERE program_id=? ORDER BY id DESC", (program_id,)
    ).fetchall())

    competitive = db.rows_to_dicts(conn.execute(
        "SELECT * FROM competitive_items WHERE program_id=? ORDER BY event_date DESC",
        (program_id,),
    ).fetchall())

    budget = conn.execute(
        "SELECT * FROM budget WHERE program_id=?", (program_id,)
    ).fetchone()

    conn.close()
    return {
        "program": dict(program),
        "molecules": molecules,
        "tpp_params": tpp_params,
        "inbox_items": inbox,
        "ledger_entries": ledger,
        "competitive_items": competitive,
        "budget": dict(budget) if budget else None,
    }


@app.get("/molecule/{molecule_id}")
def get_molecule(molecule_id: int):
    conn = get_conn()
    mol = conn.execute("SELECT * FROM molecules WHERE id=?", (molecule_id,)).fetchone()
    if mol is None:
        conn.close()
        raise HTTPException(404, "molecule not found")
    assays = db.rows_to_dicts(conn.execute(
        "SELECT * FROM assays WHERE molecule_id=?", (molecule_id,)
    ).fetchall())
    conn.close()
    # present targets/descriptions as a biotech's own data — preferred names, no raw IDs
    from ..engine import target_names
    for a in assays:
        a["target"] = target_names.pretty_target(a.get("target"))
        if a.get("assay_desc"):
            a["assay_desc"] = re.sub(r"\bCHEMBL\d+\b", "", a["assay_desc"]).strip()

    d = dict(mol)
    d["assays"] = assays
    if d.get("adme_json"):
        try:
            d["adme"] = json.loads(d["adme_json"])
        except (TypeError, json.JSONDecodeError):
            d["adme"] = None
    d["has_structure"] = structure_engine.structure_path(molecule_id).exists()
    return _scrub(d)


class FavoriteRequest(BaseModel):
    favorite: bool


@app.post("/molecule/{molecule_id}/favorite")
def molecule_favorite(molecule_id: int, req: FavoriteRequest):
    conn = get_conn()
    cur = conn.execute("UPDATE molecules SET favorite=? WHERE id=?",
                       (1 if req.favorite else 0, molecule_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "molecule not found")
    return {"molecule_id": molecule_id, "favorite": req.favorite}


@app.get("/molecule/{molecule_id}/structure2d")
def molecule_structure2d(molecule_id: int):
    conn = get_conn()
    mol = conn.execute("SELECT smiles FROM molecules WHERE id=?", (molecule_id,)).fetchone()
    conn.close()
    if mol is None:
        raise HTTPException(404, "molecule not found")
    svg = structure_engine.structure_svg(mol["smiles"])
    if svg is None:
        raise HTTPException(422, "could not render structure")
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/molecule/{molecule_id}/structure3d", response_class=PlainTextResponse)
def molecule_structure3d(molecule_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID),
                         download: bool = Query(default=False)):
    """PDB text for the molecule's structure — a real Boltz co-fold once folded,
    otherwise the program's configured reference PDB. `X-Structure-Placeholder`
    + `X-Structure-Label` headers tell the UI which it is. `download=1` attaches it."""
    result = structure_engine.get_cached_structure(molecule_id, program_id)
    if result is None:
        raise HTTPException(404, "no structure available")
    pdb, is_placeholder, label, fmt = result
    conn = get_conn()
    mrow = conn.execute("SELECT name FROM molecules WHERE id=?", (molecule_id,)).fetchone()
    conn.close()
    name = mrow["name"] if mrow else f"mol_{molecule_id}"
    headers = {
        "X-Structure-Placeholder": "1" if is_placeholder else "0",
        "X-Structure-Label": label,
        "X-Structure-Format": fmt,
        "Access-Control-Expose-Headers": "X-Structure-Placeholder,X-Structure-Label,X-Structure-Format",
    }
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{name}_structure.{fmt}"'
    media = ("chemical/x-cif" if fmt == "cif" else "chemical/x-pdb") if download else "text/plain"
    return Response(content=pdb, media_type=media, headers=headers)


@app.get("/fold-config")
def get_fold_config(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    return structure_engine.get_fold_config(program_id)


class FoldConfigRequest(BaseModel):
    target_kind: str = "pdb"   # 'pdb' | 'uniprot' | 'sequence'
    target_value: str = ""
    pdb_id: str | None = None  # legacy alias for a PDB target_value
    constraints: str = ""
    program_id: str = DEMO_PROGRAM_ID


@app.post("/fold-config")
def set_fold_config(req: FoldConfigRequest):
    """Set the folding target (PDB id, UniProt id, or raw protein sequence) and
    folding constraints used for this program's co-folds and reference structure."""
    value = req.target_value or req.pdb_id or ""
    return structure_engine.set_fold_config(req.program_id, req.target_kind, value, req.constraints)


@app.get("/molecule/{molecule_id}/data.csv")
def molecule_data_csv(molecule_id: int):
    conn = get_conn()
    mol = conn.execute("SELECT name FROM molecules WHERE id=?", (molecule_id,)).fetchone()
    if mol is None:
        conn.close()
        raise HTTPException(404, "molecule not found")
    rows = conn.execute(
        "SELECT modality, target, standard_type, value, units, relation, pchembl, "
        "source, assay_desc FROM assays WHERE molecule_id=? ORDER BY modality, target",
        (molecule_id,),
    ).fetchall()
    conn.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["modality", "target", "standard_type", "value", "units", "relation",
                "pchembl", "source", "assay_desc"])
    for r in rows:
        w.writerow([r["modality"], r["target"], r["standard_type"], r["value"],
                    r["units"], r["relation"], r["pchembl"], r["source"], r["assay_desc"]])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{mol["name"]}_data.csv"'},
    )


@app.get("/tpp/scores")
def tpp_scores(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Per-molecule TPP scoring + the current 'meets TPP' set."""
    return tpp_engine.recompute(program_id)


@app.post("/tpp/recompute")
def tpp_recompute(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    return tpp_engine.recompute(program_id)


@app.get("/tpp/histogram")
def tpp_histogram(metric: str, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Population distribution for one TPP metric (with threshold context)."""
    return tpp_engine.population_histogram(metric, program_id)


@app.get("/metrics")
def metrics_catalog(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """All available molecule properties (assay + ADME + custom), with data counts."""
    from ..engine import metrics as metrics_engine
    return metrics_engine.catalog(program_id)


class CustomMetricRequest(BaseModel):
    label: str
    units: str = ""
    log: bool = False
    higher_is_better: bool = False
    target: str = "TGTA"
    modality: str | None = None
    description: str | None = None
    formula: str | None = None
    program_id: str = DEMO_PROGRAM_ID


class IngestRequest(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    source: str | None = None       # 'anonymized' | 'real' (defaults to config)
    limit: int | None = None


@app.post("/corpus/ingest")
def corpus_ingest(req: IngestRequest):
    """Read the mailbox source, extract, and (re)build the corpus + world model."""
    from ..engine.corpus import store
    return store.ingest(req.program_id, source=req.source, limit=req.limit)


class AskRequest(BaseModel):
    question: str
    program_id: str = DEMO_PROGRAM_ID


@app.post("/knowledge/ask")
def knowledge_ask(req: AskRequest):
    """QueryOS: grounded, cited answer from the knowledge store (facts-first)."""
    from ..engine.corpus import qa
    return qa.ask(req.program_id, req.question)


@app.get("/corpus/summary")
def corpus_summary(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    conn = get_conn()
    docs = conn.execute("SELECT COUNT(*) c FROM documents WHERE program_id=?", (program_id,)).fetchone()["c"]
    facts = conn.execute("SELECT COUNT(*) c FROM facts WHERE program_id=? AND status='current'", (program_id,)).fetchone()["c"]
    by_type = {r["doc_type"]: r["c"] for r in conn.execute(
        "SELECT doc_type, COUNT(*) c FROM documents WHERE program_id=? GROUP BY doc_type", (program_id,)).fetchall()}
    conn.close()
    return {"documents": docs, "facts": facts, "by_type": by_type}


@app.get("/mailbox")
def mailbox(program_id: str = Query(default=DEMO_PROGRAM_ID),
            category: str | None = Query(default=None),
            include_ignored: bool = Query(default=False),
            limit: int = Query(default=60)):
    """Triaged inbound emails for the mailbox view — most recent first."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id,email_from,subject,sent_at,doc_type,raw_text,triage_json,seen "
        "FROM documents WHERE program_id=? AND direction='inbound' AND triage_json IS NOT NULL "
        "ORDER BY sent_at DESC LIMIT ?", (program_id, max(limit, 1) * 2)).fetchall()
    out, counts = [], {"ignore": 0, "knowledge": 0, "processing": 0, "action": 0}
    for r in rows:
        try:
            t = json.loads(r["triage_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        cat = t.get("category", "action")
        counts[cat] = counts.get(cat, 0) + 1
        if category and cat != category:
            continue
        if not include_ignored and not category and cat == "ignore":
            continue
        from ..engine.triage import latest_message
        preview = latest_message(r["raw_text"] or "")[:200]
        out.append({
            "id": r["id"], "from": r["email_from"], "subject": r["subject"],
            "sent_at": r["sent_at"], "doc_type": r["doc_type"], "seen": bool(r["seen"]),
            "category": cat, "next_step": t.get("next_step"), "reason": t.get("reason"),
            "needs_reply": t.get("needs_reply", False), "confidence": t.get("confidence"),
            "preview": preview,
        })
        if len(out) >= limit:
            break
    conn.close()
    return {"counts": counts, "emails": out}


@app.get("/mailbox/{doc_id}")
def mailbox_email(doc_id: int):
    """Full email + triage for the reading pane."""
    conn = get_conn()
    r = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "email not found")
    conn.execute("UPDATE documents SET seen=1 WHERE id=?", (doc_id,))
    conn.commit()
    d = dict(r)
    conn.close()
    try:
        d["triage"] = json.loads(d.get("triage_json") or "{}")
    except json.JSONDecodeError:
        d["triage"] = {}
    return {"id": d["id"], "from": d["email_from"], "to": d["email_to"],
            "subject": d["subject"], "sent_at": d["sent_at"], "doc_type": d["doc_type"],
            "body": d["raw_text"], "triage": d["triage"]}


@app.get("/molecules/values")
def molecules_values(metrics: str = Query(...), program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Value matrix (molecule × requested metric keys) for the configurable table."""
    from ..engine import metrics as metrics_engine
    keys = [k for k in metrics.split(",") if k]
    return metrics_engine.values_table(program_id, keys)


@app.post("/metrics/custom")
def metrics_define(req: CustomMetricRequest):
    """Define a new molecule property (may have no data yet)."""
    from ..engine import metrics as metrics_engine
    return metrics_engine.define_custom(
        req.program_id, req.label, req.units, req.log, req.higher_is_better,
        req.target, req.modality, req.description, req.formula)


@app.get("/tpp/current")
def tpp_current(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """The active TPP version + its parameters (for the TPP page)."""
    return tpp_engine.current_tpp(program_id)


@app.get("/tpp/versions")
def tpp_versions(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    return tpp_engine.list_versions(program_id)


@app.get("/tpp/version/{version_number}")
def tpp_version_detail(version_number: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    try:
        return tpp_engine.version_detail(program_id, version_number)
    except ValueError as e:
        raise HTTPException(404, str(e))


class UpdateParamRequest(BaseModel):
    changes: dict
    justification: str
    program_id: str = DEMO_PROGRAM_ID


@app.post("/tpp/param/{param_id}/update")
def tpp_update_param(param_id: int, req: UpdateParamRequest):
    """Edit one TPP parameter -> creates a new version (justification required)."""
    try:
        return tpp_engine.update_param(req.program_id, param_id, req.changes, req.justification)
    except ValueError as e:
        raise HTTPException(400, str(e))


class AddParamRequest(BaseModel):
    spec: dict
    justification: str
    program_id: str = DEMO_PROGRAM_ID


@app.post("/tpp/param/add")
def tpp_add_param(req: AddParamRequest):
    """Add a new criterion to the TPP -> creates a new version."""
    try:
        return tpp_engine.add_param(req.program_id, req.spec, req.justification)
    except ValueError as e:
        raise HTTPException(400, str(e))


class BuildTppRequest(BaseModel):
    brief: str
    program_id: str = DEMO_PROGRAM_ID
    api_key: str | None = None


@app.post("/tpp/build")
def tpp_build(req: BuildTppRequest):
    """TPP Builder: turn a program brief into a structured, executable TPP version."""
    return tpp_builder.build(req.brief, req.program_id, api_key=req.api_key)


class ChatMessage(BaseModel):
    role: str
    content: str


class TppChatRequest(BaseModel):
    messages: list[ChatMessage]
    program_id: str = DEMO_PROGRAM_ID
    api_key: str | None = None


@app.get("/tpp/builder/greeting")
def tpp_builder_greeting():
    return {"greeting": tpp_builder.GREETING}


@app.post("/tpp/builder/chat")
def tpp_builder_chat(req: TppChatRequest):
    msgs = [{"role": m.role, "content": m.content} for m in req.messages]
    return tpp_builder.chat(msgs, api_key=req.api_key, program_id=req.program_id)


@app.post("/tpp/builder/finalize")
def tpp_builder_finalize(req: TppChatRequest):
    msgs = [{"role": m.role, "content": m.content} for m in req.messages]
    return tpp_builder.finalize_from_chat(msgs, req.program_id, api_key=req.api_key)


@app.get("/tpp/demo-brief")
def tpp_demo_brief():
    return {"brief": tpp_builder.DEMO_BRIEF}


def _referenced_molecule_ids(conn, program_id: str, payload: dict) -> list[int]:
    """Resolve molecule tokens referenced by an inbox item to canonical ids."""
    ids: list[int] = []
    if payload.get("molecule_id"):
        ids.append(payload["molecule_id"])
    tokens: list[str] = []
    for a in (payload.get("extraction", {}) or {}).get("assays", []):
        if isinstance(a, dict) and a.get("molecule"):
            tokens.append(str(a["molecule"]))
    for tok in (payload.get("extraction", {}) or {}).get("molecules", []) or []:
        tokens.append(str(tok))
    for tok in tokens:
        r = identity_engine.resolve_molecule(program_id, tok, conn=conn)
        if r.get("molecule_id"):
            ids.append(r["molecule_id"])
    # de-dup, preserve order
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _inbox_context(conn, program_id: str, item: dict, payload: dict) -> dict:
    """Assemble the context panel; only include sections that resolve."""
    ctx: dict = {}

    # 1) referenced-molecule TPP status
    mol_ids = _referenced_molecule_ids(conn, program_id, payload)
    if mol_ids:
        scores = {m["molecule_id"]: m for m in tpp_engine.recompute(program_id)["molecules"]}
        mols = []
        for mid in mol_ids:
            row = conn.execute("SELECT id,name FROM molecules WHERE id=?", (mid,)).fetchone()
            if not row:
                continue
            s = scores.get(mid)
            mols.append({"molecule_id": mid, "name": row["name"],
                         "tpp_status": s["status"] if s else "no_data"})
        if mols:
            ctx["molecules"] = mols

    # 2) budget snapshot (always resolvable if a budget exists)
    snap = cfo_engine.budget_snapshot(conn, program_id)
    if snap:
        ctx["budget"] = snap

    # 3) prior quotes from the same vendor (facts + documents)
    vendor = payload.get("vendor")
    if vendor and vendor != "Unknown vendor":
        quotes = [dict(r) for r in conn.execute(
            "SELECT value FROM facts WHERE program_id=? AND subject_type='vendor' "
            "AND subject_key=? AND predicate='quoted_amount' AND status='current'",
            (program_id, vendor)).fetchall()]
        prior_docs = [dict(r) for r in conn.execute(
            "SELECT id,subject,sent_at FROM documents WHERE program_id=? AND doc_type='quote' "
            "AND id<>? ORDER BY id DESC LIMIT 5",
            (program_id, payload.get("document_id") or -1)).fetchall()]
        if quotes or prior_docs:
            ctx["prior_quotes"] = {"amounts": [q["value"] for q in quotes], "documents": prior_docs}

    # 4) related ledger entries (same vendor mention in title)
    if vendor and vendor != "Unknown vendor":
        led = [dict(r) for r in conn.execute(
            "SELECT id,kind,title,created_at FROM ledger_entries WHERE program_id=? "
            "AND title LIKE ? ORDER BY id DESC LIMIT 5",
            (program_id, f"%{vendor}%")).fetchall()]
        if led:
            ctx["ledger"] = led
    return ctx


@app.get("/inbox")
def get_inbox(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Open inbox items with envelope + extraction + analysis + context panel."""
    conn = get_conn()
    rows = db.rows_to_dicts(conn.execute(
        "SELECT * FROM inbox_items WHERE program_id=? AND status='pending' ORDER BY id",
        (program_id,)))
    out = []
    for it in rows:
        payload = json.loads(it["payload"]) if it["payload"] else {}
        analysis = json.loads(it["analysis"]) if it.get("analysis") else payload.get("analysis", {})
        extraction = (json.loads(it["extraction_json"]) if it.get("extraction_json")
                      else payload.get("extraction", {}))
        proposed = json.loads(it["proposed_action"]) if it["proposed_action"] else {}
        out.append({
            "id": it["id"], "kind": it["kind"], "doc_type": it.get("doc_type"),
            "title": it["title"], "summary": it["summary"], "status": it["status"],
            "document_id": it.get("document_id"),
            "envelope": {
                "email_from": payload.get("email_from"), "email_to": payload.get("email_to"),
                "subject": payload.get("subject") or it["title"], "date": payload.get("date"),
                "direction": payload.get("direction"),
                "body_preview": payload.get("body_preview"),
                "attachments": payload.get("attachments", []),
            },
            "extraction": extraction, "analysis": analysis, "proposed_action": proposed,
            "context": _inbox_context(conn, program_id, it, payload),
        })
    conn.close()
    return {"items": out}


@app.get("/inbox/{item_id}/rederivation")
def inbox_rederivation(item_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Re-derivation overlay data for an item (raw curve + fitted vs reported IC50)."""
    conn = get_conn()
    item = conn.execute(
        "SELECT * FROM inbox_items WHERE id=? AND program_id=?", (item_id, program_id)
    ).fetchone()
    conn.close()
    if item is None:
        raise HTTPException(404, "inbox item not found")
    chk = inbox_engine.rederivation_for_item(dict(item))
    if chk is None:
        return {"has_curve": False}
    return {"has_curve": True, **chk}


@app.post("/inbox/{item_id}/approve")
def inbox_approve(item_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    try:
        return inbox_engine.approve(item_id, program_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/inbox/{item_id}/decline")
def inbox_decline(item_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Dismiss an inbox item without acting on it."""
    conn = get_conn()
    with conn:
        cur = conn.execute(
            "UPDATE inbox_items SET status='dismissed' WHERE id=? AND program_id=?",
            (item_id, program_id))
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "inbox item not found")
    return {"status": "dismissed"}


@app.post("/demo/reset")
def demo_reset(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Re-seed the inbox and re-hold the demo molecules — resets the loop for a
    fresh run/recording without a full data reload."""
    conn = get_conn()
    with conn:
        # remove CRO-loaded assays and re-hold the demo molecules
        for name in ("BTX-1033", "BTX-1026", "BTX-1027"):
            r = conn.execute(
                "SELECT id FROM molecules WHERE program_id=? AND name=?", (program_id, name)
            ).fetchone()
            if r:
                conn.execute("DELETE FROM assays WHERE molecule_id=? AND source IN ('cro','derived')",
                             (r["id"],))
                conn.execute("UPDATE molecules SET held_out=1 WHERE id=?", (r["id"],))
        conn.execute("DELETE FROM ledger_entries WHERE program_id=?", (program_id,))
    conn.close()
    n = inbox_engine.seed_inbox(program_id)
    from ..engine import cfo as cfo_engine
    cfo_engine.seed_financials(program_id)
    return {"reset": True, "inbox_items": n}


@app.get("/budget")
def budget(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Budget snapshot + PO pipeline + invoices for the CFO page."""
    from ..engine import cfo as cfo_engine
    conn = get_conn()
    snap = cfo_engine.budget_snapshot(conn, program_id)
    pos = db.rows_to_dicts(conn.execute(
        "SELECT po.*, v.name AS vendor_name FROM purchase_orders po "
        "LEFT JOIN vendors v ON v.id=po.vendor_id WHERE po.program_id=? ORDER BY po.id DESC",
        (program_id,),
    ).fetchall())
    invoices = db.rows_to_dicts(conn.execute(
        "SELECT * FROM invoices WHERE program_id=? ORDER BY id DESC", (program_id,)
    ).fetchall())
    quotes = db.rows_to_dicts(conn.execute(
        "SELECT q.*, v.name AS vendor_name FROM quotes q LEFT JOIN vendors v ON v.id=q.vendor_id "
        "WHERE q.program_id=? ORDER BY q.id DESC", (program_id,)
    ).fetchall())
    conn.close()
    return {"budget": snap, "purchase_orders": pos, "invoices": invoices, "quotes": quotes}


@app.get("/po/{po_id}")
def po_get(po_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """One purchase order as an editable document (line items + vendor)."""
    try:
        return cfo_engine.get_po(po_id, program_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


class POUpdate(BaseModel):
    line_items: list[dict]
    vendor_name: str | None = None
    program_id: str = DEMO_PROGRAM_ID


@app.post("/po/{po_id}")
def po_update(po_id: int, body: POUpdate):
    """Save edits to a draft PO."""
    try:
        return cfo_engine.update_po(po_id, body.line_items, body.vendor_name, body.program_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/po/{po_id}/approve")
def po_approve(po_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Issue the PO: encumber budget, draft vendor email, log the decision."""
    try:
        return cfo_engine.approve_po(po_id, program_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/kb/details")
def kb_details_get(program_id: str = Query(default=DEMO_PROGRAM_ID),
                   entity_type: str = Query(...), name: str = Query(...)):
    """Canonical profile fields (address/phone/email/…) for an entity from the KB."""
    from ..engine import kb_profile
    return kb_profile.get_details(program_id, entity_type, name)


class KbDetails(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    entity_type: str
    name: str
    fields: dict


@app.post("/kb/details")
def kb_details_save(body: KbDetails):
    """Persist user-entered profile fields back into the KB for reuse."""
    from ..engine import kb_profile
    return kb_profile.save_details(body.program_id, body.entity_type, body.name, body.fields)


@app.get("/competitive")
def competitive(program_id: str = Query(default=DEMO_PROGRAM_ID),
                refresh: bool = Query(default=False)):
    """Structured competitive radar (programs / catalysts / financings / news)."""
    return competitive_engine.build(program_id, use_cache=not refresh)


# ==== reconstructed inbox-loop routes: data QC · legal · registry · quotes ====

class RunBody(BaseModel):
    source: str = "text"                    # "text" | "native"
    files: list[str] | None = None
    api_key: str | None = None


def _doc_or_404(conn, doc_id: int, program_id: str):
    doc = conn.execute("SELECT * FROM documents WHERE id=? AND program_id=?",
                       (doc_id, program_id)).fetchone()
    if not doc:
        conn.close()
        raise HTTPException(404, "email not found")
    return doc


def _attachments_for(doc, program_id: str) -> list[dict]:
    """Attachment list with native-read availability — union of parsed-text names and
    on-disk binaries (a file can exist on disk without being inlined into raw_text)."""
    from ..engine.processors import data as data_proc
    from ..engine.attachments import parse_attachments
    att_names = [fn for fn, _ in parse_attachments(doc["raw_text"] or "")]
    real = data_proc.real_attachments_anon(program_id, doc["source_ref"])
    names = list(dict.fromkeys([*att_names, *real.keys()]))
    return [{"filename": n, "native_available": n in real and data_proc.can_read_native(real[n])}
            for n in names]


# ---- Data QC ----
@app.get("/data/analysis/{doc_id}")
def data_analysis_get(doc_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    conn = get_conn()
    doc = _doc_or_404(conn, doc_id, program_id)
    r = conn.execute("SELECT * FROM data_analyses WHERE document_id=? AND program_id=?",
                     (doc_id, program_id)).fetchone()
    atts = _attachments_for(doc, program_id)
    conn.close()
    if not r:
        return {"found": False, "status": "pending", "attachments": atts}
    try:
        analysis = json.loads(r["analysis_json"] or "{}")
    except json.JSONDecodeError:
        analysis = {}
    return {"found": True, "id": r["id"], "status": r["status"], "verdict": r["verdict"],
            "analysis": analysis, "attachments": atts}


@app.post("/data/analysis/{doc_id}/run")
def data_analysis_run(doc_id: int, body: RunBody, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    from ..engine.processors import data as data_proc
    conn = get_conn()
    doc = _doc_or_404(conn, doc_id, program_id)
    aid = data_proc.analyze_and_store(conn, program_id, doc, api_key=body.api_key,
                                      source=body.source, files=body.files)
    conn.commit()
    r = conn.execute("SELECT * FROM data_analyses WHERE id=?", (aid,)).fetchone()
    atts = _attachments_for(doc, program_id)
    conn.close()
    analysis = json.loads(r["analysis_json"] or "{}") if r else {}
    return {"found": True, "id": aid, "status": r["status"] if r else "pending",
            "verdict": r["verdict"] if r else None, "analysis": analysis, "attachments": atts}


@app.post("/data/{analysis_id}/approve")
def data_analysis_approve(analysis_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    from ..engine.processors import data as data_proc
    conn = get_conn()
    try:
        res = data_proc.approve(conn, program_id, analysis_id)
        conn.commit()
        return res
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        conn.close()


@app.post("/data/{analysis_id}/dismiss")
def data_analysis_dismiss(analysis_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    conn = get_conn()
    conn.execute("UPDATE data_analyses SET status='dismissed' WHERE id=? AND program_id=?",
                 (analysis_id, program_id))
    conn.commit()
    conn.close()
    return {"id": analysis_id, "status": "dismissed"}


# ---- Legal review ----
@app.get("/legal/review/{doc_id}")
def legal_review_get(doc_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    from ..engine.processors import legal
    conn = get_conn()
    doc = _doc_or_404(conn, doc_id, program_id)
    r = conn.execute("SELECT * FROM legal_reviews WHERE document_id=? AND program_id=?",
                     (doc_id, program_id)).fetchone()
    out = {"document_text": legal.document_text(doc), "attachments": _attachments_for(doc, program_id)}
    conn.close()
    if not r:
        return {"found": False, "review": None, **out}
    try:
        review = json.loads(r["review_json"] or "{}")
    except json.JSONDecodeError:
        review = {}
    return {"found": True, "review": review, **out}


@app.post("/legal/review/{doc_id}/run")
def legal_review_run(doc_id: int, body: RunBody, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    from ..engine.processors import legal
    conn = get_conn()
    doc = _doc_or_404(conn, doc_id, program_id)
    rid = legal.review_and_store(conn, program_id, doc, api_key=body.api_key,
                                 source=body.source, files=body.files)
    conn.commit()
    r = conn.execute("SELECT * FROM legal_reviews WHERE id=?", (rid,)).fetchone()
    out = {"document_text": legal.document_text(doc), "attachments": _attachments_for(doc, program_id)}
    conn.close()
    review = json.loads(r["review_json"] or "{}") if r else {}
    return {"found": True, "review": review, **out}


@app.get("/legal/document/{doc_id}/download")
def legal_document_download(doc_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    from ..engine.processors import data as data_proc, legal
    conn = get_conn()
    doc = _doc_or_404(conn, doc_id, program_id)
    reals = data_proc.real_attachments(doc["source_ref"])
    conn.close()
    if reals:
        import mimetypes
        p = reals[0]
        mt = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        return FileResponse(str(p), media_type=mt, filename=p.name)
    return PlainTextResponse(legal.document_text(doc))


# ---- Quotes (related-quote grouping) ----
@app.get("/quotes/groups")
def quotes_groups(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    from ..engine import quote_related
    return quote_related.quote_groups(program_id)


# ---- Compound registry ----
@app.get("/registry/candidates")
def registry_candidates(program_id: str = Query(default=DEMO_PROGRAM_ID),
                        q: str | None = Query(default=None)):
    from ..engine import registry
    return registry.candidates(program_id, q)


@app.get("/registry/{molecule_id}/detail")
def registry_detail(molecule_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    from ..engine import registry
    return registry.detail(program_id, molecule_id)


class RegistryConfirm(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    value: str | None = None


@app.post("/registry/{molecule_id}/confirm")
def registry_confirm(molecule_id: int, body: RegistryConfirm):
    from ..engine import registry
    return registry.confirm_new(body.program_id, molecule_id, value=body.value)


class RegistryMerge(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    target_id: int
    vendor: str | None = None


@app.post("/registry/{candidate_id}/merge")
def registry_merge(candidate_id: int, body: RegistryMerge):
    from ..engine import registry
    return registry.merge(body.program_id, candidate_id, body.target_id, vendor=body.vendor)


@app.post("/registry/{molecule_id}/dismiss")
def registry_dismiss(molecule_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    from ..engine import registry
    return registry.dismiss(program_id, molecule_id)


@app.get("/molecules/search")
def molecules_search(program_id: str = Query(default=DEMO_PROGRAM_ID), q: str = Query(...)):
    from ..engine import registry
    return registry.search_molecules(program_id, q)


@app.get("/structure/svg")
def structure_svg(smiles: str = Query(...)):
    svg = structure_engine.structure_svg(smiles)
    if svg is None:
        raise HTTPException(422, "could not render structure")
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/healthz")
def healthz():
    return {"ok": True}
