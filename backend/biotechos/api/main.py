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
from ..engine import structure as structure_engine
from ..engine import tpp as tpp_engine
from ..engine import tpp_builder
from ..state import db

app = FastAPI(title="BiotechOS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
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

    tpp_params = db.rows_to_dicts(conn.execute(
        "SELECT * FROM tpp_params WHERE program_id=?", (program_id,)
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
def molecule_structure3d(molecule_id: int):
    """PDB text for the molecule's structure — a real Boltz co-fold once folded,
    otherwise the TGTA reference placeholder (REF1). `X-Structure-Placeholder`
    header + `X-Structure-Label` tell the UI which it is."""
    result = structure_engine.get_cached_structure(molecule_id)
    if result is None:
        raise HTTPException(404, "no structure available")
    pdb, is_placeholder = result
    return Response(
        content=pdb,
        media_type="text/plain",
        headers={
            "X-Structure-Placeholder": "1" if is_placeholder else "0",
            "X-Structure-Label": structure_engine.PLACEHOLDER_LABEL if is_placeholder
            else "Boltz co-fold",
            "Access-Control-Expose-Headers": "X-Structure-Placeholder,X-Structure-Label",
        },
    )


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


class BuildTppRequest(BaseModel):
    brief: str
    program_id: str = DEMO_PROGRAM_ID


@app.post("/tpp/build")
def tpp_build(req: BuildTppRequest):
    """TPP Builder: turn a program brief into a structured, executable TPP."""
    return tpp_builder.build(req.brief, req.program_id)


@app.get("/tpp/demo-brief")
def tpp_demo_brief():
    return {"brief": tpp_builder.DEMO_BRIEF}


@app.get("/healthz")
def healthz():
    return {"ok": True}
