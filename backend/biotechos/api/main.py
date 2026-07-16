"""FastAPI app: all routes are program_id-scoped. Day 1 delivers GET /state."""
from __future__ import annotations

import json

import csv
import io
import re
import sqlite3

from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, FileResponse, HTMLResponse
from pydantic import BaseModel, field_validator

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
        # Real (un-anonymized) Program A archive as its own program. Row is seeded here;
        # its corpus is ingested separately via store.ingest("program-a", source="real").
        conn.execute(
            "INSERT OR IGNORE INTO programs(id,name,target,anti_target,indication,status)"
            " VALUES (?,?,?,?,?,?)",
            ("program-a", "Program A", "TGTA", "TGTB",
             "TGTA-driven cancers", "active"))
        # Remove the orphaned 'program-a-real' program (never seeded by code). Delete its
        # (empty) child rows first, then the program row — idempotent so a stray row from
        # an old DB can't reappear in the program switcher.
        for tbl in ("assays", "molecule_aliases", "molecules", "inbox_items", "documents",
                    "observations", "facts", "ledger_entries", "competitive_items",
                    "tpp_params", "tpp_versions", "budget", "fold_settings"):
            try:
                conn.execute(f"DELETE FROM {tbl} WHERE program_id='program-a-real'")
            except sqlite3.OperationalError:
                pass
        conn.execute("DELETE FROM programs WHERE id='program-a-real'")
    conn.close()
    # Turnkey demo: populate the self-contained KRAS G12C program on first boot so a
    # fresh clone shows data without a manual load step (idempotent; seeds only if empty).
    try:
        conn = db.connect()
        empty = conn.execute("SELECT COUNT(*) FROM molecules WHERE program_id='kras'").fetchone()[0] == 0
        conn.close()
        if empty:
            from ..ingest.seed_kras import seed as _seed_kras
            _seed_kras()
    except Exception as _e:
        print(f"[startup] KRAS demo seed skipped: {_e}")
    # Fold-backlog reconciler exists but the automatic periodic sweep is OFF by request —
    # the backlog is folded only on demand via POST /modeling/fold-backlog/run (the
    # "Fold backlog" button). Re-enable by calling structure.start_backlog_sweep() here.

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

    # Only confirmed (active) molecules appear in the database; 'candidate' molecules
    # (new compounds detected from the inbox) are gated to the Registry until approved.
    molecules = db.rows_to_dicts(conn.execute(
        "SELECT * FROM molecules WHERE program_id=? AND held_out=0 "
        "AND (status='active' OR status IS NULL) ORDER BY id",
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
    # every name/alias the system knows for this molecule (for the aliases + canonical UI)
    from ..engine import identity
    d["aliases"] = identity.passport(mol["program_id"], molecule_id).get("aliases", [])
    return _scrub(d)


class ManualAssay(BaseModel):
    modality: str = "generic_numeric"
    target: str | None = None
    standard_type: str | None = None
    value: float | None = None
    units: str | None = None
    system_type: str | None = None
    system: str | None = None


class ManualMolecule(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    name: str
    smiles: str | None = None
    aliases: list[str] = []
    assays: list[ManualAssay] = []


@app.post("/molecules/add-manual")
def add_manual_molecule(body: ManualMolecule):
    """Manually add a molecule + its data straight into the Molecule Database (status
    'active' — bypasses the registry, since the user is deliberately adding it)."""
    from ..engine import identity
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    smi = (body.smiles or "").strip() or None
    ik = identity.inchikey(smi) if smi else None
    if smi and ik is None:
        raise HTTPException(400, "not a valid SMILES")
    conn = get_conn()
    with conn:
        mid = conn.execute(
            "INSERT INTO molecules(program_id,name,smiles,inchi_key,held_out,status) "
            "VALUES (?,?,?,?,0,'active')", (body.program_id, name, smi, ik)).lastrowid
        deposited = 0
        for a in body.assays:
            if a.value is None:
                continue
            conn.execute(
                "INSERT INTO assays(program_id,molecule_id,modality,target,standard_type,value,"
                "units,system_type,system,source) VALUES (?,?,?,?,?,?,?,?,?, 'manual')",
                (body.program_id, mid, (a.modality or "generic_numeric"), a.target,
                 a.standard_type, a.value, a.units, a.system_type, a.system))
            deposited += 1
    conn.close()
    for al in body.aliases:
        if al.strip():
            identity.add_alias(body.program_id, mid, al.strip(), verified=True)
    # structure detected → RDKit ADME + enqueue Boltz co-fold (SMILES) / fold (sequence)
    if smi:
        structure_engine.on_structure_detected(mid, body.program_id)
    return {"molecule_id": mid, "deposited": deposited}


class GroupCreate(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    name: str
    molecule_ids: list[int]


@app.post("/groups")
def create_group(body: GroupCreate):
    """Create a named molecule group (cohort) from selected molecules — for modeling."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "group name is required")
    if not body.molecule_ids:
        raise HTTPException(400, "select at least one molecule")
    ids = sorted(set(int(i) for i in body.molecule_ids))
    conn = get_conn()
    with conn:
        gid = conn.execute(
            "INSERT INTO molecule_groups(program_id,name,molecule_ids) VALUES (?,?,?)",
            (body.program_id, name, json.dumps(ids))).lastrowid
    conn.close()
    return {"group_id": gid, "name": name, "count": len(ids)}


# ==== Modeling (group/single-molecule structure-based widgets) ================

def _subject_members(conn, program_id: str, group_id: int | None, molecule_id: int | None):
    """Resolve the modeling 'unit' (a group or a single molecule) → [(id, name, has_cofold)]."""
    from ..engine import structure as _st
    if group_id is not None:
        r = conn.execute("SELECT molecule_ids FROM molecule_groups WHERE id=? AND program_id=?",
                         (group_id, program_id)).fetchone()
        ids = json.loads(r["molecule_ids"] or "[]") if r else []
    elif molecule_id is not None:
        ids = [molecule_id]
    else:
        ids = []
    out = []
    for i in ids:
        row = conn.execute("SELECT name FROM molecules WHERE id=? AND program_id=?",
                           (i, program_id)).fetchone()
        out.append({"id": i, "name": row["name"] if row else f"#{i}",
                    "has_cofold": _st.structure_path(i).exists()})
    return out


@app.get("/modeling/subject")
def modeling_subject(program_id: str = Query(default=DEMO_PROGRAM_ID),
                     group_id: int | None = Query(default=None),
                     molecule_id: int | None = Query(default=None)):
    conn = get_conn()
    members = _subject_members(conn, program_id, group_id, molecule_id)
    conn.close()
    return {"members": members, "n_cofolded": sum(1 for m in members if m["has_cofold"])}


class ContactMapReq(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    molecule_ids: list[int]
    interactions: list[str] | None = None


@app.post("/modeling/contact-map")
def modeling_contact_map(body: ContactMapReq):
    from ..engine import prolif_contacts
    conn = get_conn()
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id,name FROM molecules WHERE program_id=?", (body.program_id,)).fetchall()}
    conn.close()
    return prolif_contacts.contact_map(body.program_id, body.molecule_ids, names=names,
                                       interactions=body.interactions)


@app.get("/modeling/contact-map/{molecule_id}/ligplot", response_class=HTMLResponse)
def modeling_ligplot(molecule_id: int):
    from ..engine import prolif_contacts
    html = prolif_contacts.ligplot_html(molecule_id)
    if html is None:
        raise HTTPException(404, "no co-fold structure for this molecule")
    return HTMLResponse(html)


class GenerateReq(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    seed_ids: list[int] = []
    num_molecules: int = 20
    molecule_filters: dict | None = None

    @field_validator("num_molecules")
    @classmethod
    def _clamp_num(cls, v: int) -> int:
        # Boltz small-molecule design accepts 10 .. 1,000,000 molecules per job.
        return max(10, min(1_000_000, v))


@app.post("/modeling/generate/estimate")
def modeling_generate_estimate(body: GenerateReq):
    """Live cost estimate for the current generate params."""
    from ..engine import boltz, structure as _st
    seq = _st.get_fold_config(body.program_id).get("target_value")
    try:
        return boltz.estimate_generate_cost(seq, body.num_molecules)
    except Exception as e:
        raise HTTPException(502, f"Boltz estimate failed: {e}")


# in-memory generate job store (single-user local app)
_GEN_JOBS: dict[str, dict] = {}


@app.post("/modeling/generate")
def modeling_generate(body: GenerateReq):
    """Start a Boltz small-molecule design job (background) → returns a job id to poll."""
    import threading, uuid
    from ..engine import boltz, structure as _st
    seq = _st.get_fold_config(body.program_id).get("target_value")
    if not seq:
        raise HTTPException(400, "program has no folding-target sequence configured")
    job_id = uuid.uuid4().hex[:12]
    _GEN_JOBS[job_id] = {"status": "running", "molecules": [], "error": None}

    def _run():
        try:
            mols = boltz.generate(seq, num_molecules=body.num_molecules,
                                  molecule_filters=body.molecule_filters, name=f"gen_{job_id}")
            _GEN_JOBS[job_id] = {"status": "done", "molecules": mols, "error": None}
        except Exception as e:
            _GEN_JOBS[job_id] = {"status": "error", "molecules": [], "error": str(e)}

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@app.get("/modeling/generate-cached")
def modeling_generate_cached():
    """Most recent completed generate run, read from disk — no new Boltz job / no cost.
    Lets the UI be built/iterated against real candidates without re-running."""
    from ..engine import boltz
    return boltz.latest_generated()


@app.get("/modeling/seed-data")
def modeling_seed_data(program_id: str = Query(default=DEMO_PROGRAM_ID), ids: str = Query(default="")):
    """Normalized rows for the seed (co-folded) molecules, in the same shape as generated
    candidates, so they can be shown/sorted alongside them and highlighted as seeds."""
    conn = get_conn()
    out = []
    for tok in [t for t in ids.split(",") if t.strip()]:
        try:
            mid = int(tok)
        except ValueError:
            continue
        r = conn.execute("SELECT id,name,smiles,boltz_json FROM molecules WHERE id=? AND program_id=?",
                         (mid, program_id)).fetchone()
        if not r or not r["smiles"]:
            continue
        bj = json.loads(r["boltz_json"]) if r["boltz_json"] else {}
        out.append({
            "id": f"seed_{r['id']}", "molecule_id": r["id"], "name": r["name"],
            "smiles": r["smiles"], "seed": True,
            "iptm": bj.get("iptm") or bj.get("ligand_iptm"),
            "binding_confidence": bj.get("binding_confidence"),
            "ptm": bj.get("ptm"), "complex_plddt": bj.get("complex_plddt"),
            "structure_confidence": bj.get("structure_confidence"),
            "optimization_score": bj.get("optimization_score"),
            "adme": {"lipophilicity": bj.get("lipophilicity"), "permeability": bj.get("permeability"),
                     "solubility": bj.get("solubility_class") or bj.get("solubility")},
        })
    conn.close()
    return out


@app.get("/modeling/generate/{job_id}/structure/{pres_id}", response_class=PlainTextResponse)
def modeling_generate_structure(job_id: str, pres_id: str):
    """Predicted co-fold CIF for one generated molecule (for the spinning 3D viewer)."""
    from ..engine import boltz
    cif = boltz.generated_structure_path(job_id, pres_id)
    if not cif:
        raise HTTPException(404, "no structure for that generated molecule")
    return PlainTextResponse(cif.read_text(), headers={"X-Structure-Format": "cif"})


@app.post("/modeling/generate/{job_id}/adopt")
def modeling_generate_adopt(job_id: str, body: dict = Body(default={})):
    """Promote a generated molecule into the Molecule Database, carrying its Boltz
    co-fold structure + metrics + ADME — WITHOUT running a new co-fold job."""
    from ..engine import boltz, identity
    pres_id = body.get("pres_id")
    name = (body.get("name") or "").strip()
    program_id = body.get("program_id") or DEMO_PROGRAM_ID
    if not (pres_id and name):
        raise HTTPException(400, "pres_id and name are required")
    real_job = boltz.latest_generated()["job_id"] if job_id in (None, "latest") else job_id
    mols = boltz._read_generated(boltz._RUN_ROOT / f"gen_{real_job}")
    rec = next((m for m in mols if m.get("id") == pres_id), None)
    if not rec:
        raise HTTPException(404, "generated molecule not found in that run")
    smi = rec.get("smiles")
    ik = identity.inchikey(smi) if smi else None
    conn = get_conn()
    with conn:
        mid = conn.execute(
            "INSERT INTO molecules(program_id,name,smiles,inchi_key,held_out,status) "
            "VALUES (?,?,?,?,0,'active')", (program_id, name, smi, ik)).lastrowid
    # attach the already-computed Boltz co-fold structure (no new job)
    cif = boltz.generated_structure_path(real_job, pres_id)
    if cif:
        try:
            structure_engine.store_cofold_cif(mid, cif)
        except Exception as e:
            print(f"[adopt] store structure failed for {mid}: {e}")
    # RDKit ADME (system-standard) + Boltz metrics/ADME → boltz_json
    adme = structure_engine.predicted_adme(smi) if smi else None
    boltz_json = {k: rec.get(k) for k in ("iptm", "binding_confidence", "ptm", "complex_plddt",
                                          "complex_iplddt", "structure_confidence", "optimization_score")}
    boltz_json["adme_boltz"] = rec.get("adme") or {}
    boltz_json["generated_from"] = real_job
    with conn:
        conn.execute("UPDATE molecules SET adme_json=?, boltz_json=? WHERE id=?",
                     (json.dumps(adme) if adme else None, json.dumps(boltz_json), mid))
    conn.close()
    return {"molecule_id": mid, "has_structure": bool(cif)}


@app.post("/modeling/generate/{job_id}/export")
def modeling_generate_export(job_id: str, body: dict = Body(default={})):
    """ZIP of selected generated molecules: molecules.xlsx (SMILES + data) + co-fold CIFs."""
    from ..engine import boltz
    data = boltz.export_generated(job_id, body.get("ids"))
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="generated_{job_id}.zip"'})


@app.get("/modeling/generate/{job_id}")
def modeling_generate_poll(job_id: str):
    job = _GEN_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    return {"job_id": job_id, **job}


@app.get("/modeling/fold-backlog")
def modeling_fold_backlog(program_id: str | None = None):
    """Count + live cost estimate of active molecules with a SMILES/sequence but no co-fold."""
    from ..engine import structure as _st
    return _st.fold_backlog_summary(program_id)


@app.post("/modeling/fold-backlog/run")
def modeling_fold_backlog_run(body: dict = Body(default={})):
    """Enqueue co-folds for the whole un-folded backlog (real Boltz spend; explicit confirm)."""
    from ..engine import structure as _st
    return _st.run_fold_backlog(program_id=body.get("program_id"), limit=body.get("limit"))


@app.get("/groups")
def list_groups(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """List molecule groups for a program (with member ids + a name lookup)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id,name,molecule_ids,created_at FROM molecule_groups WHERE program_id=? ORDER BY id DESC",
        (program_id,)).fetchall()
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id,name FROM molecules WHERE program_id=?", (program_id,)).fetchall()}
    conn.close()
    out = []
    for r in rows:
        try:
            ids = json.loads(r["molecule_ids"] or "[]")
        except json.JSONDecodeError:
            ids = []
        out.append({"id": r["id"], "name": r["name"], "created_at": r["created_at"],
                    "molecule_ids": ids,
                    "members": [{"id": i, "name": names.get(i, f"#{i}")} for i in ids]})
    return out


@app.delete("/groups/{group_id}")
def delete_group(group_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM molecule_groups WHERE id=? AND program_id=?", (group_id, program_id))
    conn.close()
    return {"deleted": group_id}


class SmilesRequest(BaseModel):
    smiles: str
    program_id: str = DEMO_PROGRAM_ID


@app.post("/molecule/{molecule_id}/smiles")
def molecule_set_smiles(molecule_id: int, req: SmilesRequest):
    """Update a molecule's SMILES (validated via RDKit) + recompute its InChIKey."""
    from ..engine import identity
    smi = (req.smiles or "").strip()
    ik = identity.inchikey(smi)
    if not smi or ik is None:
        raise HTTPException(400, "not a valid SMILES")
    conn = get_conn()
    with conn:
        cur = conn.execute("UPDATE molecules SET smiles=?, inchi_key=? WHERE id=?",
                           (smi, ik, molecule_id))
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "molecule not found")
    # SMILES detected → RDKit ADME now + enqueue Boltz co-fold with the folding target
    fold = structure_engine.on_structure_detected(molecule_id, req.program_id)
    return {"molecule_id": molecule_id, "smiles": smi, "inchi_key": ik, "fold": fold}


class AliasRequest(BaseModel):
    alias: str
    program_id: str = DEMO_PROGRAM_ID


@app.post("/molecule/{molecule_id}/alias")
def molecule_add_alias(molecule_id: int, req: AliasRequest):
    """Add a name/alias to a molecule."""
    from ..engine import identity
    alias = (req.alias or "").strip()
    if not alias:
        raise HTTPException(400, "alias is empty")
    identity.add_alias(req.program_id, molecule_id, alias, verified=True)
    return {"molecule_id": molecule_id, "alias": alias, "aliases":
            identity.passport(req.program_id, molecule_id).get("aliases", [])}


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
    from ..engine import categories
    conn = get_conn()
    rows = conn.execute(
        "SELECT id,email_from,subject,sent_at,doc_type,raw_text,triage_json,seen "
        "FROM documents WHERE program_id=? AND direction='inbound' AND triage_json IS NOT NULL "
        "ORDER BY sent_at DESC LIMIT ?", (program_id, max(limit, 1) * 2)).fetchall()
    out, counts = [], {c: 0 for c in categories.CATEGORIES}
    counts["ignored"] = 0
    from ..engine.triage import latest_message
    for r in rows:
        try:
            t = json.loads(r["triage_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        # 5-way business category (quote|invoice|legal|data|other), triage_json override wins
        cat = categories.category_for(conn, r["id"], r["doc_type"])
        ignored = bool(t.get("ignored"))
        # counters only include UN-ignored emails
        if ignored:
            counts["ignored"] += 1
        else:
            counts[cat] = counts.get(cat, 0) + 1
        # filtering: the 'ignored' tab shows only ignored; every other view hides ignored
        if category == "ignored":
            if not ignored:
                continue
        else:
            if ignored:
                continue
            if category and cat != category:
                continue
            if not include_ignored and not category and cat == "other":
                continue
        out.append({
            "id": r["id"], "from": r["email_from"], "subject": r["subject"],
            "sent_at": r["sent_at"], "doc_type": r["doc_type"], "seen": bool(r["seen"]),
            "category": cat, "ignored": ignored,
            "next_step": t.get("next_step"), "reason": t.get("reason"),
            "needs_reply": t.get("needs_reply", False), "confidence": t.get("confidence"),
            "preview": latest_message(r["raw_text"] or "")[:200],
        })
        if len(out) >= limit:
            break
    conn.close()
    return {"counts": counts, "emails": out}


class SetCategory(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    category: str


@app.post("/mailbox/{doc_id}/category")
def mailbox_set_category(doc_id: int, body: SetCategory):
    """Manually set an email's 5-way category (double-click override in the inbox)."""
    from ..engine import categories
    if body.category not in categories.CATEGORIES:
        raise HTTPException(400, f"category must be one of {categories.CATEGORIES}")
    conn = get_conn()
    r = conn.execute("SELECT triage_json FROM documents WHERE id=? AND program_id=?",
                     (doc_id, body.program_id)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "email not found")
    try:
        tj = json.loads(r["triage_json"] or "{}")
    except json.JSONDecodeError:
        tj = {}
    tj["category"] = body.category
    tj["manual_category"] = True
    with conn:
        conn.execute("UPDATE documents SET triage_json=? WHERE id=?", (json.dumps(tj), doc_id))
    conn.close()
    return {"id": doc_id, "category": body.category}


class SetIgnored(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    ignored: bool = True


@app.post("/mailbox/{doc_id}/ignore")
def mailbox_set_ignored(doc_id: int, body: SetIgnored):
    """Ignore-for-now (or un-ignore) an email — ignored emails drop out of the counters."""
    conn = get_conn()
    r = conn.execute("SELECT triage_json FROM documents WHERE id=? AND program_id=?",
                     (doc_id, body.program_id)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "email not found")
    try:
        tj = json.loads(r["triage_json"] or "{}")
    except json.JSONDecodeError:
        tj = {}
    tj["ignored"] = bool(body.ignored)
    with conn:
        conn.execute("UPDATE documents SET triage_json=? WHERE id=?", (json.dumps(tj), doc_id))
    conn.close()
    return {"id": doc_id, "ignored": bool(body.ignored)}


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


class EmailNote(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    note: str


@app.post("/mailbox/{doc_id}/note")
def mailbox_add_note(doc_id: int, body: EmailNote):
    """Leave a note on an email for Claude to action later (flagged for review).
    Retrieved via `python -m biotechos.review notes` → data/review_notes.md."""
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(400, "note is empty")
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO email_notes(program_id,document_id,note,flagged,resolved,author) "
            "VALUES (?,?,?,1,0,'founder')", (body.program_id, doc_id, note))
    conn.close()
    return {"document_id": doc_id, "saved": True}


@app.get("/mailbox/{doc_id}/notes")
def mailbox_get_notes(doc_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Open (unresolved) notes left on this email."""
    conn = get_conn()
    rows = db.rows_to_dicts(conn.execute(
        "SELECT id,note,created_at FROM email_notes WHERE document_id=? AND program_id=? "
        "AND resolved=0 ORDER BY created_at DESC", (doc_id, program_id)).fetchall())
    conn.close()
    return {"notes": rows}


@app.post("/mailbox/{doc_id}/reclassify")
def mailbox_reclassify(doc_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Re-run the 5-way classifier LLM on this email and store the result as the
    authoritative category (a triage_json override that wins over the doc_type map)."""
    import os
    from ..engine import classifier
    from ..engine.triage import _doc_email
    conn = get_conn()
    r = conn.execute("SELECT * FROM documents WHERE id=? AND program_id=?",
                     (doc_id, program_id)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "email not found")
    res = classifier.classify_email(_doc_email(r), api_key=os.environ.get("ANTHROPIC_API_KEY"))
    try:
        tj = json.loads(r["triage_json"] or "{}")
    except json.JSONDecodeError:
        tj = {}
    tj["category"] = res.category
    tj["reclassified"] = True
    with conn:
        conn.execute("UPDATE documents SET triage_json=? WHERE id=?", (json.dumps(tj), doc_id))
    conn.close()
    return {"id": doc_id, "category": res.category, "reason": res.reason,
            "confidence": res.confidence}


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
    """Restore the KRAS demo to its original seeded state — re-runs the seed loader,
    which clears the program (incl. any approved/registered data) and re-inserts the
    50 compounds, favorites + group, TPP, budget, four fresh inbox emails, precomputed
    DataQC/Legal reviews, and the folded favorites."""
    from ..ingest.seed_kras import seed as _seed_kras
    return {"reset": True, **_seed_kras()}


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


@app.get("/quote/{doc_id}")
def quote_get(doc_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """One vendor quotation rendered as a document (line items + vendor + ref)."""
    import re
    conn = get_conn()
    r = conn.execute("SELECT * FROM documents WHERE id=? AND program_id=?",
                     (doc_id, program_id)).fetchone()
    conn.close()
    if not r or r["doc_type"] != "quote":
        raise HTTPException(404, "quote not found")
    d = dict(r)
    try:
        ext = json.loads(d.get("extraction_json") or "{}")
    except json.JSONDecodeError:
        ext = {}
    raw = d.get("raw_text") or ""
    ref = re.search(r"Quote ref[:\s]+([A-Za-z0-9\-/]+)", raw)
    valid = re.search(r"valid\s+([0-9]{1,3}\s+days)", raw, re.I)
    turn = re.search(r"Turnaround[:\s]+([^\n]+)", raw)
    vendor = ext.get("vendor") or (d.get("email_from") or "").split("<")[0].strip()
    return {
        "doc_id": d["id"],
        "vendor": vendor,
        "vendor_email": d.get("email_from") or "",
        "buyer": {"name": "Kestrel Therapeutics, Inc.", "contact": "Jordan Lee",
                  "email": d.get("email_to") or "founder@kestrel-tx.example",
                  "addr": ["100 Kestrel Way", "South San Francisco, CA 94080"]},
        "subject": d.get("subject") or "",
        "quote_ref": ref.group(1) if ref else "",
        "dated": d.get("sent_at") or "",
        "valid": valid.group(1) if valid else None,
        "turnaround": turn.group(1).strip() if turn else None,
        "line_items": ext.get("line_items") or [],
        "amount": ext.get("amount"),
    }


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
    source: str = "native"                  # native-only (real attachment via Sonnet + LibreOffice)
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
    """Attachment list with native-read availability. For the anonymized demo program
    the filenames are anonymized (matching the extractor); the real programs (program-b,
    program-a) use the real on-disk filenames."""
    from ..engine.processors import data as data_proc
    from ..engine.attachments import parse_attachments
    att_names = [fn for fn, _ in parse_attachments(doc["raw_text"] or "")]
    if program_id == DEMO_PROGRAM_ID:
        real = data_proc.real_attachments_anon(program_id, doc["source_ref"])   # {anon_name: Path}
    else:
        real = {f.name: f for f in data_proc.real_attachments(doc["source_ref"])}  # real names
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
                                      source=body.source, files=body.files, redo=True)
    conn.commit()
    r = conn.execute("SELECT * FROM data_analyses WHERE id=?", (aid,)).fetchone()
    atts = _attachments_for(doc, program_id)
    conn.close()
    analysis = json.loads(r["analysis_json"] or "{}") if r else {}
    return {"found": True, "id": aid, "status": r["status"] if r else "pending",
            "verdict": r["verdict"] if r else None, "analysis": analysis, "attachments": atts}


class DataApproveBody(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    deposition: list[dict] | None = None      # user-edited proposed-deposition rows


@app.post("/data/{analysis_id}/approve")
def data_analysis_approve(analysis_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID),
                          body: DataApproveBody | None = None):
    from ..engine.processors import data as data_proc
    dep = body.deposition if body else None
    conn = get_conn()
    try:
        res = data_proc.approve(conn, program_id, analysis_id, deposition=dep)
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


@app.get("/quotes/related/{doc_id}")
def quotes_related(doc_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Competing quotes for the same service as this quote email (compare price/turnaround)."""
    from ..engine import quote_related
    return quote_related.related_to_document(program_id, doc_id)


@app.post("/mailbox/{doc_id}/create-po")
def mailbox_create_po(doc_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Draft a PO from this quote email's parsed line items → open in the PO editor."""
    try:
        return cfo_engine.create_draft_po_from_document(program_id, doc_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/legal/execution-status/{doc_id}")
def legal_execution_status(doc_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Lightweight classifier: is this legal email an already-executed doc (file it)
    or a draft/redline to review? Used to branch the inbox before any full review."""
    import os
    from ..engine.processors import legal
    conn = get_conn()
    doc = _doc_or_404(conn, doc_id, program_id)
    conn.close()
    return legal.detect_execution_status(program_id, doc, api_key=os.environ.get("ANTHROPIC_API_KEY"))


@app.post("/legal/review/{doc_id}/save")
def legal_review_save(doc_id: int, program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Save a completed/executed legal document to records. Upserts a 'filed' row so it
    works whether or not a full review was run first."""
    conn = get_conn()
    with conn:
        cur = conn.execute("UPDATE legal_reviews SET status='filed' WHERE document_id=? AND program_id=?",
                           (doc_id, program_id))
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO legal_reviews(program_id,document_id,status,summary,review_json) "
                "VALUES (?,?, 'filed', 'Filed executed document', ?)",
                (program_id, doc_id, json.dumps({"execution_status": "executed", "filed": True})))
    conn.close()
    return {"document_id": doc_id, "status": "filed"}


# ---- Compound registry ----
@app.get("/registry/candidates")
def registry_candidates(program_id: str = Query(default=DEMO_PROGRAM_ID),
                        q: str | None = Query(default=None)):
    from ..engine import registry
    cands = registry.candidates(program_id, q)
    return {"candidates": cands, "total": registry.remaining_count(program_id)}


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


class RegistrySetCanonical(BaseModel):
    program_id: str = DEMO_PROGRAM_ID
    alias: str


@app.post("/registry/{molecule_id}/set-canonical")
def registry_set_canonical(molecule_id: int, body: RegistrySetCanonical):
    """Promote an alias to the molecule's canonical name (re-keys the whole system)."""
    from ..engine import registry
    try:
        return registry.set_canonical(body.program_id, molecule_id, body.alias)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/registry/rebuild-from-categories")
def registry_rebuild_from_categories(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Restrict registry candidates to molecules sourced from quote/invoice/legal/data emails."""
    from ..engine import registry
    return registry.rebuild_from_categories(program_id)


@app.post("/registry/flag-unconfirmed")
def registry_flag_unconfirmed(program_id: str = Query(default=DEMO_PROGRAM_ID)):
    """Reconcile the registry: seed molecules → active; detected structure-less → candidate."""
    from ..engine import registry
    return registry.flag_unconfirmed(program_id)


@app.get("/molecules/search")
def molecules_search(program_id: str = Query(default=DEMO_PROGRAM_ID), q: str = Query(...),
                     limit: int = Query(default=8)):
    from ..engine import registry
    return registry.search_molecules(program_id, q, limit=limit)


@app.get("/structure/svg")
def structure_svg(smiles: str = Query(...)):
    svg = structure_engine.structure_svg(smiles)
    if svg is None:
        raise HTTPException(422, "could not render structure")
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/healthz")
def healthz():
    return {"ok": True}
