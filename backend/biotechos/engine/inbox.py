"""Monday-morning inbox: the closed loop.

seed_inbox() stages a small set of realistic inbound items. approve() runs the
loop for a data item: load the incoming CRO measurements onto the molecule,
recompute the TPP, append to the Decision Log, and — if a molecule crosses the
TPP — draft the go/no-go memo.

The "lead candidate" item is authored so that approving it flips exactly one
molecule to MEETS TPP (a differentiated compound with a real TGTB selectivity
window). A second item carries a planted reported-vs-raw IC50 discrepancy for
the re-derivation catch.
"""
from __future__ import annotations

import json
import re

from ..config import DEMO_PROGRAM_ID
from ..state import db
from . import artifacts, cfo, curvefit, identity, tpp
from .corpus import store as corpus_store


def _next_btx_name(conn, program_id: str) -> str:
    """Return the next BTX-#### name, continuing the sequence."""
    rows = conn.execute(
        "SELECT name FROM molecules WHERE program_id=? AND name LIKE 'BTX-%'",
        (program_id,)).fetchall()
    mx = 0
    for r in rows:
        m = re.match(r"BTX-(\d+)", r["name"])
        if m:
            mx = max(mx, int(m.group(1)))
    return f"BTX-{max(mx, 1299) + 1:04d}"


def _promote_item_observations(conn, program_id: str, document_id: int | None) -> int:
    """Promote observations sourced from this item's document into current facts."""
    if not document_id:
        return 0
    obs = conn.execute(
        "SELECT id,subject_type,subject_key,predicate,value FROM observations "
        "WHERE program_id=? AND source_document_id=?", (program_id, document_id)).fetchall()
    n = 0
    for o in obs:
        corpus_store._promote(conn, program_id, o["id"],
                              {"subject_type": o["subject_type"], "subject_key": o["subject_key"],
                               "predicate": o["predicate"], "value": o["value"]})
        n += 1
    return n


def _resolve_or_create(conn, program_id: str, token: str, smiles: str | None,
                       document_id: int | None) -> tuple[int, str, bool]:
    """Resolve a compound token; if unresolved, create a new BTX-#### molecule and
    register the surrogate token as an alias. Returns (mol_id, name, created)."""
    r = identity.resolve_molecule(program_id, token, smiles=smiles,
                                  source_document_id=document_id, conn=conn)
    if r.get("molecule_id"):
        return r["molecule_id"], token, r["status"] == "created"
    name = _next_btx_name(conn, program_id)
    ik = identity.inchikey(smiles)
    mid = conn.execute(
        "INSERT INTO molecules(program_id,name,smiles,inchi_key,held_out) VALUES (?,?,?,?,0)",
        (program_id, name, smiles, ik)).lastrowid
    # canonical name is an implicit alias; also register the surrogate/CRO code
    identity.add_alias(program_id, mid, token, source_document_id=document_id,
                       confidence=1.0, verified=True, conn=conn)
    return mid, name, True


def _mol_id_by_name(conn, program_id: str, name: str) -> int | None:
    r = conn.execute(
        "SELECT id FROM molecules WHERE program_id=? AND name=?", (program_id, name)
    ).fetchone()
    return r["id"] if r else None


def _assay(modality, target, stype, value, units, source="cro", raw=None, reported=None):
    return {"modality": modality, "target": target, "standard_type": stype,
            "value": value, "units": units, "source": source,
            "raw_points": raw, "reported_value": reported}


def _lead_candidate_payload() -> dict:
    """Authored CRO deliverable for the lead candidate: a differentiated compound
    that clears every TPP axis, driven by a real TGTB-selectivity window."""
    ic50 = 18.0
    conc, resp = curvefit.synth_curve(ic50, hill=1.0, noise=2.5, seed=7)
    return {
        "assays": [
            _assay("biochemical_ic50", "TGTA", "IC50", ic50, "nM",
                   raw={"concentration_nM": conc, "pct_inhibition": resp}, reported=ic50),
            _assay("biochemical_ic50", "TGTB", "IC50", 540.0, "nM"),
            _assay("selectivity", "TGTA/TGTB", "Fold selectivity", 30.0, "x", source="derived"),
            _assay("cellular_antiprolif", "TGTA", "GI50", 65.0, "nM"),
        ],
    }


def _rederivation_payload() -> dict:
    """A dataset whose reported IC50 looks best-in-class but disagrees with its
    own raw curve — the re-derivation catch."""
    true_ic50 = 41.0
    reported = 7.0  # looks sub-10nM; a transcription/analysis error
    conc, resp = curvefit.synth_curve(true_ic50, hill=1.1, noise=3.0, seed=13)
    return {
        "assays": [
            _assay("biochemical_ic50", "TGTA", "IC50", reported, "nM",
                   raw={"concentration_nM": conc, "pct_inhibition": resp}, reported=reported),
        ],
    }


def seed_inbox(program_id: str = DEMO_PROGRAM_ID,
               lead_name: str = "BTX-1033", catch_name: str = "BTX-1026",
               chem_name: str = "BTX-1027") -> int:
    """Create the demo inbox items. Returns the count created."""
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM inbox_items WHERE program_id=?", (program_id,))

        lead_id = _mol_id_by_name(conn, program_id, lead_name)
        catch_id = _mol_id_by_name(conn, program_id, catch_name)
        chem_id = _mol_id_by_name(conn, program_id, chem_name)

        items = []
        if lead_id:
            items.append((
                "bio_cro_data",
                f"Biology CRO: cell-panel + selectivity results for {lead_name}",
                f"CRO returned TGTA biochemical, TGTB counter-screen, and TGTA+ cellular "
                f"anti-proliferation for {lead_name}. The OS parsed the report and scored it "
                f"against the TPP — this compound's TGTB selectivity window clears the bar.",
                json.dumps({"molecule_id": lead_id, **_lead_candidate_payload()}),
                json.dumps({"action": "approve_data",
                            "label": "Approve interpretation & load data",
                            "note": "Projected to meet TPP on all axes → candidate for advancement."}),
            ))
        if catch_id:
            items.append((
                "bio_cro_data",
                f"Biology CRO: TGTA potency for {catch_name} — QC flag",
                f"CRO reported a sub-10nM TGTA IC50 for {catch_name}, but the OS re-fit the raw "
                f"dose-response curve and the derived IC50 disagrees with the reported value. "
                f"Flagged for review before the data is trusted.",
                json.dumps({"molecule_id": catch_id, **_rederivation_payload()}),
                json.dumps({"action": "approve_data",
                            "label": "Review re-derivation & decide",
                            "note": "Reported IC50 conflicts with the raw curve — see dose-response overlay."}),
            ))
        if chem_id:
            items.append((
                "chem_update",
                f"Chemistry: synthesis update for {chem_name}",
                f"Medicinal chemistry completed a 3-step resynthesis of {chem_name} at scale; "
                f"material is ready for the next assay cycle. No data to score — timeline update only.",
                json.dumps({"molecule_id": chem_id, "timeline": "resynthesis complete"}),
                json.dumps({"action": "acknowledge", "label": "Acknowledge & update timeline"}),
            ))

        for kind, title, summary, payload, action in items:
            conn.execute(
                "INSERT INTO inbox_items(program_id,kind,title,summary,payload,proposed_action)"
                " VALUES (?,?,?,?,?,?)",
                (program_id, kind, title, summary, payload, action),
            )
    n = len(items)
    conn.close()
    return n


def rederivation_for_item(item: dict) -> dict | None:
    """If an item carries a raw dose-response with a reported value, return the
    re-derivation check (for the UI overlay). Else None."""
    payload = json.loads(item["payload"]) if item.get("payload") else {}
    for a in payload.get("assays", []):
        raw = a.get("raw_points")
        rep = a.get("reported_value")
        if raw and rep is not None:
            chk = curvefit.rederivation_check(
                raw["concentration_nM"], raw["pct_inhibition"], rep)
            chk["raw_points"] = raw
            return chk
    return None


def _approve_quote_from_extraction(conn, program_id: str, item: dict, payload: dict) -> dict:
    """Quote → PO: materialize a vendor + quote from the extraction, then run the
    CFO approve_quote flow (PO + vendor email draft + budget commit) → ledger + facts."""
    ex = payload.get("extraction", {}) or {}
    vendor_name = payload.get("vendor") or ex.get("vendor") or "Unknown vendor"
    amount = ex.get("total") or (max(ex["amounts"]) if ex.get("amounts") else 0.0)
    document_id = payload.get("document_id")

    with conn:
        vrow = conn.execute("SELECT id FROM vendors WHERE program_id=? AND name=?",
                            (program_id, vendor_name)).fetchone()
        vid = vrow["id"] if vrow else conn.execute(
            "INSERT INTO vendors(program_id,name,email,kind) VALUES (?,?,?,?)",
            (program_id, vendor_name, payload.get("email_from", ""), "CRO")).lastrowid
        line_items = [{"item": s, "amount": None} for s in ex.get("services", [])] or \
                     [{"item": payload.get("subject", "Quoted services"), "amount": amount}]
        qid = conn.execute(
            "INSERT INTO quotes(program_id,vendor_id,description,line_items,amount,status)"
            " VALUES (?,?,?,?,?, 'received')",
            (program_id, vid, payload.get("subject", "Vendor quote"),
             json.dumps(line_items), amount)).lastrowid

    fin = cfo.approve_quote(qid, program_id)  # its own txn: PO + email + commit + ledger + invoice item
    with conn:
        promoted = _promote_item_observations(conn, program_id, document_id)
        conn.execute("UPDATE inbox_items SET status='approved' WHERE id=?", (item["id"],))
    return {"kind": item["kind"], "financial": fin, "promoted_facts": promoted}


def _approve_data_from_extraction(conn, program_id: str, item: dict, payload: dict,
                                  before: dict) -> dict:
    """Data → DB: resolve/merge each compound into the BTX set, insert assays,
    recompute TPP, draft go/no-go memos on crossings → ledger + facts."""
    ex = payload.get("extraction", {}) or {}
    document_id = payload.get("document_id")
    assays = ex.get("assays", []) or []
    loaded, mols = 0, {}

    with conn:
        for a in assays:
            if not isinstance(a, dict):
                continue
            token = a.get("molecule") or payload.get("subject")
            if token not in mols:
                mid, name, created = _resolve_or_create(
                    conn, program_id, str(token), a.get("smiles"), document_id)
                mols[token] = {"id": mid, "name": name, "created": created}
            mid = mols[token]["id"]
            # extract_cro_data emits {type,value,units}; map to assays table best-effort
            try:
                val = float(a.get("value")) if a.get("value") is not None else None
            except (TypeError, ValueError):
                val = None
            if val is None:
                continue
            conn.execute(
                "INSERT INTO assays(program_id,molecule_id,modality,target,standard_type,"
                "value,units,source) VALUES (?,?,?,?,?,?,?,?)",
                (program_id, mid, a.get("modality", "biochemical_ic50"),
                 a.get("target", ""), a.get("type") or a.get("standard_type", "IC50"),
                 val, a.get("units", "nM"), "cro"))
            loaded += 1
        for m in mols.values():
            conn.execute("UPDATE molecules SET held_out=0 WHERE id=?", (m["id"],))

    after = {m["name"]: m for m in tpp.recompute(program_id)["molecules"]}
    crossed = [n for n, m in after.items()
               if m["status"] == "pass" and before.get(n) != "pass"]

    with conn:
        conn.execute(
            "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by)"
            " VALUES (?,?,?,?,?)",
            (program_id, "data_interpretation", item["title"],
             f"Loaded {loaded} CRO measurements across {len(mols)} molecule(s): "
             + ", ".join(m["name"] for m in mols.values()), "founder"))
        promoted = _promote_item_observations(conn, program_id, document_id)
        conn.execute("UPDATE inbox_items SET status='approved' WHERE id=?", (item["id"],))

    memo = None
    for name in crossed:
        text, used_llm = artifacts.go_no_go_memo(name, after[name])
        memo = {"molecule": name, "text": text, "used_llm": used_llm}
        with conn:
            conn.execute(
                "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by)"
                " VALUES (?,?,?,?,?)",
                (program_id, "go_no_go", f"Go/No-Go: advance {name}", text, "founder"))

    return {"kind": item["kind"], "loaded": loaded, "crossed": crossed, "memo": memo,
            "molecules": [{"name": m["name"], "created": m["created"]} for m in mols.values()],
            "promoted_facts": promoted}


def _draft_query_reply(conn, program_id: str, item: dict, payload: dict) -> dict:
    """Query → grounded reply draft (no send). Uses qa.ask READ-ONLY for grounding."""
    from .corpus import qa  # local import: READ-ONLY grounding, never edited here
    question = (payload.get("extraction", {}) or {}).get("question") \
        or payload.get("subject") or ""
    grounded = qa.ask(program_id, question)
    draft = (f"Hi,\n\n{grounded.get('answer', '').strip()}\n\n"
             f"Best regards,\nBiotechOS Program Office")
    document_id = payload.get("document_id")
    with conn:
        conn.execute(
            "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by)"
            " VALUES (?,?,?,?,?)",
            (program_id, "query_reply", item["title"], draft, "founder"))
        promoted = _promote_item_observations(conn, program_id, document_id)
        conn.execute("UPDATE inbox_items SET status='approved' WHERE id=?", (item["id"],))
    return {"kind": item["kind"], "reply_draft": draft,
            "grounding": {"source": grounded.get("source"),
                          "citations": grounded.get("citations", [])},
            "promoted_facts": promoted}


def approve(item_id: int, program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Run the loop for one inbox item."""
    conn = db.connect()
    item = conn.execute(
        "SELECT * FROM inbox_items WHERE id=? AND program_id=?", (item_id, program_id)
    ).fetchone()
    if item is None:
        conn.close()
        raise ValueError("inbox item not found")
    item = dict(item)
    payload = json.loads(item["payload"]) if item["payload"] else {}
    action = json.loads(item["proposed_action"]) if item["proposed_action"] else {}

    before = {m["name"]: m["status"] for m in tpp.recompute(program_id)["molecules"]}

    result = {"item_id": item_id, "kind": item["kind"], "loaded": 0,
              "crossed": [], "memo": None, "rederivation": None}

    # financial loop items dispatch to the CFO engine
    if action.get("action") == "approve_po":
        fin = cfo.approve_quote(payload["quote_id"], program_id)
        with conn:
            conn.execute("UPDATE inbox_items SET status='approved' WHERE id=?", (item_id,))
        conn.close()
        return {**result, "kind": item["kind"], "financial": fin}

    if action.get("action") == "reconcile_invoice":
        fin = cfo.reconcile_invoice(payload["po_id"], payload.get("amount"), program_id)
        with conn:
            conn.execute("UPDATE inbox_items SET status='approved' WHERE id=?", (item_id,))
        conn.close()
        return {**result, "kind": item["kind"], "financial": fin}

    if action.get("action") == "acknowledge":
        # timeline-only item; log the acknowledgement
        with conn:
            conn.execute(
                "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by)"
                " VALUES (?,?,?,?,?)",
                (program_id, "chem_update", item["title"],
                 payload.get("timeline", "acknowledged"), "founder"),
            )
            conn.execute("UPDATE inbox_items SET status='approved' WHERE id=?", (item_id,))
        conn.close()
        return result

    act = action.get("action")
    document_id = payload.get("document_id")

    # --- Inbox v2 branches (document-driven items staged by store.ingest) ------
    if act == "review_quote":
        res = _approve_quote_from_extraction(conn, program_id, item, payload)
        conn.close()
        return {**result, **res}

    if act == "review_data":
        res = _approve_data_from_extraction(conn, program_id, item, payload, before)
        conn.close()
        return {**result, **res}

    if act == "draft_reply":
        res = _draft_query_reply(conn, program_id, item, payload)
        conn.close()
        return {**result, **res}

    if act in ("review_invoice", "review_contract", "review_logistics"):
        with conn:
            promoted = _promote_item_observations(conn, program_id, document_id)
            conn.execute(
                "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by)"
                " VALUES (?,?,?,?,?)",
                (program_id, act, item["title"],
                 payload.get("analysis", {}).get("note", "Reviewed and approved."), "founder"))
            conn.execute("UPDATE inbox_items SET status='approved' WHERE id=?", (item_id,))
        conn.close()
        return {**result, "promoted_facts": promoted}

    # data item: load the incoming assays onto the molecule (activate it)
    mol_id = payload.get("molecule_id")
    result["rederivation"] = rederivation_for_item(item)
    with conn:
        for a in payload.get("assays", []):
            conn.execute(
                "INSERT INTO assays(program_id,molecule_id,modality,target,standard_type,"
                "value,units,reported_value,raw_points,source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (program_id, mol_id, a["modality"], a["target"], a["standard_type"],
                 a["value"], a["units"], a.get("reported_value"),
                 json.dumps(a["raw_points"]) if a.get("raw_points") else None, a["source"]),
            )
            result["loaded"] += 1
        conn.execute("UPDATE molecules SET held_out=0 WHERE id=?", (mol_id,))

    # recompute + diff
    after_scores = tpp.recompute(program_id)
    after = {m["name"]: m for m in after_scores["molecules"]}
    for name, m in after.items():
        if m["status"] == "pass" and before.get(name) != "pass":
            result["crossed"].append(name)

    # log the approved interpretation
    with conn:
        rederiv_note = ""
        if result["rederivation"] and result["rederivation"].get("flagged"):
            rederiv_note = " [QC: " + result["rederivation"]["note"] + "]"
        conn.execute(
            "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by)"
            " VALUES (?,?,?,?,?)",
            (program_id, "data_interpretation", item["title"],
             f"Approved {result['loaded']} CRO measurements." + rederiv_note, "founder"),
        )
        conn.execute("UPDATE inbox_items SET status='approved' WHERE id=?", (item_id,))

    # go/no-go memo for any molecule that crossed to MEETS TPP
    for name in result["crossed"]:
        memo, used_llm = artifacts.go_no_go_memo(name, after[name])
        result["memo"] = {"molecule": name, "text": memo, "used_llm": used_llm}
        with conn:
            conn.execute(
                "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by)"
                " VALUES (?,?,?,?,?)",
                (program_id, "go_no_go", f"Go/No-Go: advance {name}", memo, "founder"),
            )

    conn.close()
    return result


if __name__ == "__main__":
    print("seeded", seed_inbox(), "inbox items")
