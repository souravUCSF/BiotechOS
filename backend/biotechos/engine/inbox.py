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

from ..config import DEMO_PROGRAM_ID
from ..state import db
from . import artifacts, curvefit, tpp


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
