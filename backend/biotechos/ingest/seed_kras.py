"""Seed the self-contained KRAS G12C demo program into the database.

Populates the `kras` program from the committed JSON under data/seed/kras/:
50 internal compounds (KES-####) with biochemical + cellular + selectivity assays,
a TPP, a $500K budget with a quote/PO/invoice, and four inbox emails
(quote / invoice / data / legal). Idempotent — clears and re-inserts the program.

Run:  uv run python -m biotechos.ingest.seed_kras
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import DATA_DIR
from ..state import db
from ..engine import identity

SEED = DATA_DIR / "seed" / "kras"
PROG = "kras"


def _load(name: str):
    return json.loads((SEED / name).read_text())


def _clear(conn):
    for tbl in ("assays", "molecules", "tpp_params", "tpp_versions", "documents",
                "invoices", "purchase_orders", "quotes", "vendors", "budget",
                "molecule_groups"):
        try:
            conn.execute(f"DELETE FROM {tbl} WHERE program_id=?", (PROG,))
        except Exception:
            pass
    conn.execute("DELETE FROM programs WHERE id=?", (PROG,))


def seed() -> dict:
    db.init_db(reset=False)
    meta = _load("program.json")
    mols = _load("molecules.json")
    emails = _load("emails.json")
    conn = db.connect()
    with conn:
        _clear(conn)
        p = meta["program"]
        conn.execute(
            "INSERT INTO programs(id,name,target,anti_target,indication,status) VALUES (?,?,?,?,?,?)",
            (PROG, p["name"], p["target"], p["anti_target"], p["indication"], p.get("status", "active")))

        # molecules + assays
        for m in mols:
            adme = {"MW": m["mw"], "cLogP": m["clogp"], "TPSA": m["tpsa"],
                    "HBD": m["hbd"], "HBA": m["hba"]}
            mid = conn.execute(
                "INSERT INTO molecules(program_id,name,smiles,inchi_key,held_out,status,adme_json) "
                "VALUES (?,?,?,?,0,'active',?)",
                (PROG, m["name"], m["smiles"], identity.inchikey(m["smiles"]), json.dumps(adme))).lastrowid
            rows = [
                ("biochemical_ic50", "KRAS", "IC50", m["kras_g12c_ic50_nM"], "nM", "protein", "KRAS-G12C",
                 "KRAS G12C(GDP) biochemical inhibition IC50 (TR-FRET)"),
                ("cellular_antiprolif", "KRAS", "IC50", m["cellular_perk_ic50_nM"], "nM", "cell_line", "NCI-H358",
                 "Cellular p-ERK inhibition IC50, NCI-H358 (KRAS G12C)"),
                ("selectivity", "KRAS/WT", "ratio", m["wt_selectivity_fold"], "x", "protein", "WT-KRAS",
                 "WT-KRAS / G12C biochemical selectivity fold"),
            ]
            for modality, target, stype, val, units, systype, system, desc in rows:
                conn.execute(
                    "INSERT INTO assays(program_id,molecule_id,modality,target,standard_type,value,units,"
                    "system_type,system,species,source,assay_desc) "
                    "VALUES (?,?,?,?,?,?,?,?,?, 'human','internal', ?)",
                    (PROG, mid, modality, target, stype, val, units, systype, system, desc))

        # TPP
        t = meta["tpp"]
        vid = conn.execute(
            "INSERT INTO tpp_versions(program_id,version,notes,author,active) VALUES (?,?,?,?,1)",
            (PROG, t["version"], t["notes"], t["author"])).lastrowid
        for q in t["params"]:
            conn.execute(
                "INSERT INTO tpp_params(program_id,version_id,axis,label,metric,operator,threshold,"
                "near_frac,units,weight,rationale) VALUES (?,?,?,?,?,?,?,0.5,?,?,?)",
                (PROG, vid, q["axis"], q["label"], q["metric"], q["operator"], q["threshold"],
                 q.get("units", ""), q.get("weight", 1.0), q.get("rationale", "")))

        # budget + vendors + quote/PO/invoice
        b = meta["budget"]
        conn.execute("INSERT INTO budget(program_id,total,committed,actual,monthly_burn) VALUES (?,?,?,?,?)",
                     (PROG, b["total"], b["committed"], b["actual"], b["monthly_burn"]))
        vid_by_name = {}
        for v in meta["vendors"]:
            vid_by_name[v["name"]] = conn.execute(
                "INSERT INTO vendors(program_id,name,email,kind) VALUES (?,?,?,?)",
                (PROG, v["name"], v["email"], v["kind"])).lastrowid
        q = meta["quote"]
        qid = conn.execute(
            "INSERT INTO quotes(program_id,vendor_id,description,amount,status) VALUES (?,?,?,?,?)",
            (PROG, vid_by_name.get(q["vendor"]), q["description"], q["amount"], q["status"])).lastrowid
        po = meta["purchase_order"]
        poid = conn.execute(
            "INSERT INTO purchase_orders(program_id,quote_id,vendor_id,po_number,amount,status,vendor_name) "
            "VALUES (?,?,?,?,?,?,?)",
            (PROG, qid, vid_by_name.get(po["vendor"]), po["po_number"], po["amount"], po["status"], po["vendor"])).lastrowid
        inv = meta["invoice"]
        conn.execute(
            "INSERT INTO invoices(program_id,po_id,amount,status,vendor_name,invoice_number) VALUES (?,?,?,?,?,?)",
            (PROG, poid, inv["amount"], inv["status"], inv["vendor"], inv["invoice_number"]))

        # inbox emails (documents)
        for e in emails:
            extraction = {k: e[k] for k in ("dataset", "line_items", "amount", "legal", "invoice_number") if k in e}
            conn.execute(
                "INSERT INTO documents(program_id,direction,email_from,email_to,subject,sent_at,doc_type,"
                "triage,raw_text,extraction_json,triage_json,seen) "
                "VALUES (?, 'inbound', ?,?,?,?,?, 'actionable', ?,?,?, 0)",
                (PROG, e["email_from"], e["email_to"], e["subject"], e["sent_at"], e["doc_type"],
                 e["raw_text"], json.dumps(extraction) if extraction else None,
                 json.dumps({"category": e["category"], "triage": "actionable"})))
    n_mol = conn.execute("SELECT COUNT(*) FROM molecules WHERE program_id=?", (PROG,)).fetchone()[0]
    n_doc = conn.execute("SELECT COUNT(*) FROM documents WHERE program_id=?", (PROG,)).fetchone()[0]
    conn.close()
    return {"program": PROG, "molecules": n_mol, "emails": n_doc}


if __name__ == "__main__":
    print("Seeded KRAS demo:", seed())
