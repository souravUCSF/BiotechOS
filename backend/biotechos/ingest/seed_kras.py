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

# KRAS G-domain (residues 1-188) — the folding target sequence for the program.
KRAS_SEQ = ("MTEYKLVVVGAGGVGKSALTIQLIQNHFVDEYDPTIEDSYRKQVVIDGETCLLDILDTAGQEEYSAMRDQYMRTGEGFLC"
            "VFAINNTKSFEDIHHYREQIKRVKDSEDVPMVLVGNKCDLPSRTVDTKQAQDLARSYGIPFIETSAKTRQRVEDAFYTLVR"
            "EIRQYRLKKISKEEKTPGCVKIKKCIIM")


def _load(name: str):
    return json.loads((SEED / name).read_text())


def _clear(conn):
    """Remove all rows for this program across every table (so re-seed / reset is clean).
    defer_foreign_keys lets us delete in any order — FK is checked at commit, by which
    point all program rows are gone."""
    conn.execute("PRAGMA defer_foreign_keys=ON")
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for t in tables:
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})").fetchall()]
        if "program_id" in cols:
            try:
                conn.execute(f"DELETE FROM {t} WHERE program_id=?", (PROG,))
            except Exception:
                pass
    conn.execute("DELETE FROM programs WHERE id=?", (PROG,))


def seed() -> dict:
    db.init_db(reset=False)
    meta = _load("program.json")
    mols = _load("molecules.json")
    emails = _load("emails.json")
    conn = db.connect()
    conn.execute("PRAGMA foreign_keys=OFF")   # seed is internally consistent; avoids
    with conn:                                # FK ordering issues on clear + re-seed
        _clear(conn)
        p = meta["program"]
        conn.execute(
            "INSERT INTO programs(id,name,target,anti_target,indication,status) VALUES (?,?,?,?,?,?)",
            (PROG, p["name"], p["target"], p["anti_target"], p["indication"], p.get("status", "active")))

        # molecules + assays
        FAVORITES = {"KES-0001", "KES-0002", "KES-0003", "KES-0004", "KES-0005"}
        fav_ids = []
        fav_mid = {}
        for m in mols:
            adme = {"MW": m["mw"], "cLogP": m["clogp"], "TPSA": m["tpsa"],
                    "HBD": m["hbd"], "HBA": m["hba"]}
            fav = 1 if m["name"] in FAVORITES else 0
            mid = conn.execute(
                "INSERT INTO molecules(program_id,name,smiles,inchi_key,held_out,status,favorite,adme_json) "
                "VALUES (?,?,?,?,0,'active',?,?)",
                (PROG, m["name"], m["smiles"], identity.inchikey(m["smiles"]), fav, json.dumps(adme))).lastrowid
            if fav:
                fav_ids.append(mid)
                fav_mid[m["name"]] = mid
            # register the code as a verified alias so incoming CRO data resolves to this
            # molecule (attaches) instead of creating a duplicate registry candidate
            conn.execute(
                "INSERT OR IGNORE INTO molecule_aliases(program_id,molecule_id,alias,alias_norm,"
                "alias_type,verified) VALUES (?,?,?,?, 'internal', 1)",
                (PROG, mid, m["name"], identity.normalize(m["name"])))
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

        # "Favorites" group of the flagged lead compounds
        if fav_ids:
            conn.execute("INSERT INTO molecule_groups(program_id,name,molecule_ids) VALUES (?,?,?)",
                         (PROG, "Favorites", json.dumps(fav_ids)))

        # prepopulate co-folds for the favorites (precomputed KRAS complexes; the demo
        # has no Boltz key, so load committed structures into the cache + store scores)
        import shutil
        from ..engine.structure import structure_path
        folds = SEED / "folds"
        for i, (code, mid) in enumerate(sorted(fav_mid.items())):
            src = folds / f"{code}.pdb"
            if not src.exists():
                continue
            dest = structure_path(mid)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            scores = {"ligand_iptm": round(0.86 - 0.02 * i, 3),
                      "binding_confidence": round(0.72 - 0.03 * i, 3),
                      "affinity": round(0.30 + 0.05 * i, 3),
                      "complex_plddt": round(0.88 - 0.01 * i, 3)}
            conn.execute("UPDATE molecules SET structure_cache_ref=?, boltz_json=? WHERE id=?",
                         (f"mol_{mid}.pdb", json.dumps(scores), mid))

        # inbox emails (documents)
        doc_by_cat = {}
        for e in emails:
            extraction = {k: e[k] for k in ("dataset", "line_items", "amount", "legal", "invoice_number", "vendor") if k in e}
            did = conn.execute(
                "INSERT INTO documents(program_id,direction,email_from,email_to,subject,sent_at,doc_type,"
                "triage,raw_text,extraction_json,triage_json,seen) "
                "VALUES (?, 'inbound', ?,?,?,?,?, 'actionable', ?,?,?, 0)",
                (PROG, e["email_from"], e["email_to"], e["subject"], e["sent_at"], e["doc_type"],
                 e["raw_text"], json.dumps(extraction) if extraction else None,
                 json.dumps({"category": e["category"], "triage": "actionable"}))).lastrowid
            doc_by_cat[e["category"]] = did
            # quote line items -> quote_lines, so "Create PO from this quote"
            # builds a filled PO (create_draft_po_from_document reads quote_lines).
            if e.get("doc_type") == "quote":
                for li in e.get("line_items") or []:
                    conn.execute(
                        "INSERT INTO quote_lines(program_id,document_id,vendor,scope,quantity,amount,currency) "
                        "VALUES (?,?,?,?,?,?, 'USD')",
                        (PROG, did, e.get("vendor"), li.get("description"),
                         li.get("quantity"), li.get("amount") or 0))

        # precomputed DataQC + Legal review so the buttons work with no LLM key
        if "data" in doc_by_cat and (SEED / "data_analysis.json").exists():
            da = _load("data_analysis.json")
            conn.execute(
                "INSERT INTO data_analyses(program_id,document_id,status,verdict,summary,analysis_json) "
                "VALUES (?,?, 'pending', ?, ?, ?)",
                (PROG, doc_by_cat["data"], da.get("verdict"),
                 (da["analysis"].get("vendor_summary") or "")[:200], json.dumps(da["analysis"])))
        if "legal" in doc_by_cat and (SEED / "legal_review.json").exists():
            lr = _load("legal_review.json")
            conn.execute(
                "INSERT INTO legal_reviews(program_id,document_id,status,summary,review_json) "
                "VALUES (?,?, 'pending', ?, ?)",
                (PROG, doc_by_cat["legal"], (lr.get("summary") or "")[:200], json.dumps(lr)))
    n_mol = conn.execute("SELECT COUNT(*) FROM molecules WHERE program_id=?", (PROG,)).fetchone()[0]
    n_doc = conn.execute("SELECT COUNT(*) FROM documents WHERE program_id=?", (PROG,)).fetchone()[0]
    n_fold = conn.execute("SELECT COUNT(*) FROM molecules WHERE program_id=? AND boltz_json IS NOT NULL",
                          (PROG,)).fetchone()[0]
    conn.close()
    # the program's folding target is the KRAS G-domain sequence
    from ..engine.structure import set_fold_config
    set_fold_config(PROG, "sequence", KRAS_SEQ)
    return {"program": PROG, "molecules": n_mol, "emails": n_doc, "folded": n_fold}


if __name__ == "__main__":
    print("Seeded KRAS demo:", seed())
