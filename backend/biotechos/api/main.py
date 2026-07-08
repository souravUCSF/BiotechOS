"""FastAPI app: all routes are program_id-scoped. Day 1 delivers GET /state."""
from __future__ import annotations

import json

import csv
import io

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..config import DEMO_PROGRAM_ID
from ..engine import inbox as inbox_engine
from ..engine import structure as structure_engine
from ..engine import tpp as tpp_engine
from ..engine import tpp_builder
from ..integrations import competitive as competitive_engine
from ..state import db

app = FastAPI(title="BiotechOS API")

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
    d = dict(mol)
    d["assays"] = assays
    if d.get("adme_json"):
        try:
            d["adme"] = json.loads(d["adme_json"])
        except (TypeError, json.JSONDecodeError):
            d["adme"] = None
    d["has_structure"] = structure_engine.structure_path(molecule_id).exists()
    return _scrub(d)


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
def molecule_structure3d(molecule_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """PDB text for the molecule's structure — a real Boltz co-fold once folded,
    otherwise the program's configured reference PDB. `X-Structure-Placeholder`
    + `X-Structure-Label` headers tell the UI which it is."""
    result = structure_engine.get_cached_structure(molecule_id, program_id)
    if result is None:
        raise HTTPException(404, "no structure available")
    pdb, is_placeholder, label = result
    return Response(
        content=pdb,
        media_type="text/plain",
        headers={
            "X-Structure-Placeholder": "1" if is_placeholder else "0",
            "X-Structure-Label": label,
            "Access-Control-Expose-Headers": "X-Structure-Placeholder,X-Structure-Label",
        },
    )


@app.get("/fold-config")
def get_fold_config(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    return structure_engine.get_fold_config(program_id)


class FoldConfigRequest(BaseModel):
    pdb_id: str
    constraints: str = ""
    program_id: str = DEMO_PROGRAM_ID


@app.post("/fold-config")
def set_fold_config(req: FoldConfigRequest):
    """Set the protein/PDB (and folding constraints) used for this program's
    co-folds and reference structure."""
    return structure_engine.set_fold_config(req.program_id, req.pdb_id, req.constraints)


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
    program_id: str = DEMO_PROGRAM_ID


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
        req.target, req.modality, req.description)


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


@app.get("/competitive")
def competitive(program_id: str = Query(default=DEMO_PROGRAM_ID),
                refresh: bool = Query(default=False)):
    """Structured competitive radar (programs / catalysts / financings / news)."""
    return competitive_engine.build(program_id, use_cache=not refresh)


@app.get("/healthz")
def healthz():
    return {"ok": True}
