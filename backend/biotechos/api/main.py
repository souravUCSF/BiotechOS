"""FastAPI app: all routes are program_id-scoped. Day 1 delivers GET /state."""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from ..config import DEMO_PROGRAM_ID
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
    return d


@app.get("/healthz")
def healthz():
    return {"ok": True}
