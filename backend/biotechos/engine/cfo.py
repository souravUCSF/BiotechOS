"""Financial / procurement loop — the second vertical.

A deterministic state machine over the financial tables that mirrors the science
loop (inbound -> OS drafts -> human approves -> state mutates -> Decision Log):

  quote  --approve-->  PO (issued) + vendor email draft + commitment (encumbrance)
  invoice --reconcile--> 2-way match vs PO -> release funds (committed->actual)
                          -> budget + runway recompute

Vendor email is composed as a draft (draft-only, not sent). Absorbs the old
"Ask the CFO" — runway/burn is now real state.
"""
from __future__ import annotations

import json

from ..config import DEMO_PROGRAM_ID, MODEL_ARTIFACTS
from ..state import db
from . import llm


def budget_snapshot(conn, program_id: str) -> dict:
    b = conn.execute("SELECT * FROM budget WHERE program_id=?", (program_id,)).fetchone()
    if b is None:
        return {}
    b = dict(b)
    b["available"] = round(b["total"] - b["committed"] - b["actual"], 2)
    b["runway_months"] = round(b["available"] / b["monthly_burn"], 1) if b["monthly_burn"] else None
    return b


def seed_financials(program_id: str = DEMO_PROGRAM_ID) -> None:
    """Seed a vendor + an inbound quote + a matching (not-yet-arrived) invoice,
    and a vendor-quote inbox item to kick off the loop."""
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM invoices WHERE program_id=?", (program_id,))
        conn.execute("DELETE FROM commitments WHERE program_id=?", (program_id,))
        conn.execute("DELETE FROM purchase_orders WHERE program_id=?", (program_id,))
        conn.execute("DELETE FROM quotes WHERE program_id=?", (program_id,))
        conn.execute("DELETE FROM vendors WHERE program_id=?", (program_id,))
        conn.execute("UPDATE budget SET committed=0, actual=0 WHERE program_id=?", (program_id,))
        conn.execute("DELETE FROM inbox_items WHERE program_id=? AND kind IN ('vendor_quote','vendor_invoice')",
                     (program_id,))

        vid = conn.execute(
            "INSERT INTO vendors(program_id,name,email,kind) VALUES (?,?,?,?)",
            (program_id, "Crelio Bioassays (CRO)", "orders@crelio-cro.example", "biology CRO"),
        ).lastrowid
        line_items = [
            {"item": "TGTA+ cell-panel anti-proliferation (CellLine-2, CellLine-1, SKBR3)", "amount": 48000},
            {"item": "TGTB counter-screen (biochemical)", "amount": 12000},
            {"item": "Dose-response, 8-point, n=3", "amount": 15000},
        ]
        amount = sum(li["amount"] for li in line_items)
        qid = conn.execute(
            "INSERT INTO quotes(program_id,vendor_id,description,line_items,amount) VALUES (?,?,?,?,?)",
            (program_id, vid, "Q2 biology assay package for lead-series compounds",
             json.dumps(line_items), amount),
        ).lastrowid

        conn.execute(
            "INSERT INTO inbox_items(program_id,kind,title,summary,payload,proposed_action)"
            " VALUES (?,?,?,?,?,?)",
            (program_id, "vendor_quote",
             "Vendor quote: Crelio Bioassays — Q2 assay package ($75,000)",
             "A CRO quote arrived for the Q2 biology package. The OS parsed the line items "
             "and drafted a purchase order and vendor email for your approval.",
             json.dumps({"quote_id": qid, "vendor_id": vid, "amount": amount,
                         "line_items": line_items}),
             json.dumps({"action": "approve_po",
                         "label": "Approve → issue PO + draft vendor email",
                         "note": "Registers a committed expense against the budget."})),
        )
    conn.close()


VENDOR_EMAIL_SYSTEM = """You draft a short, professional purchase-order cover email from a \
biotech founder to a CRO vendor. Confirm the scope, reference the PO number and total, and \
state expected timeline for kickoff. 3-4 sentences, no preamble."""


def _po_number(program_id: str, po_id: int) -> str:
    return f"PO-{program_id.upper()}-{1000 + po_id}"


def _draft_vendor_email(vendor_name: str, po_number: str, amount: float, line_items: list) -> tuple[str, bool]:
    scope = "; ".join(li["item"] for li in line_items)
    fallback = (
        f"Dear {vendor_name},\n\n"
        f"Please find attached purchase order {po_number} for the agreed Q2 assay package "
        f"(total ${amount:,.0f}), covering: {scope}. We approve this scope and would like to "
        f"schedule kickoff within the next two weeks. Please confirm receipt and proposed start date.\n\n"
        f"Best regards,\nBiotechOS Program Office"
    )
    return llm.text(model=MODEL_ARTIFACTS, system=VENDOR_EMAIL_SYSTEM,
                    user=f"Vendor: {vendor_name}\nPO: {po_number}\nTotal: ${amount:,.0f}\n"
                         f"Scope: {scope}\n\nDraft the cover email.",
                    fallback=fallback, max_tokens=400)


def approve_quote(quote_id: int, program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Quote -> PO (issued) + vendor email draft + commitment. Appends Decision Log."""
    conn = db.connect()
    q = conn.execute("SELECT * FROM quotes WHERE id=? AND program_id=?",
                     (quote_id, program_id)).fetchone()
    if q is None:
        conn.close()
        raise ValueError("quote not found")
    q = dict(q)
    vendor = conn.execute("SELECT * FROM vendors WHERE id=?", (q["vendor_id"],)).fetchone()
    line_items = json.loads(q["line_items"]) if q["line_items"] else []

    with conn:
        po_id = conn.execute(
            "INSERT INTO purchase_orders(program_id,quote_id,vendor_id,amount,status)"
            " VALUES (?,?,?,?,'issued')",
            (program_id, quote_id, q["vendor_id"], q["amount"]),
        ).lastrowid
        po_number = _po_number(program_id, po_id)
        email, used_llm = _draft_vendor_email(vendor["name"], po_number, q["amount"], line_items)
        conn.execute("UPDATE purchase_orders SET po_number=?, email_draft_id=? WHERE id=?",
                     (po_number, f"draft:{po_id}", po_id))
        conn.execute("UPDATE quotes SET status='ordered' WHERE id=?", (quote_id,))
        # encumbrance: committed budget rises, available falls
        conn.execute("INSERT INTO commitments(program_id,po_id,amount,status) VALUES (?,?,?,'committed')",
                     (program_id, po_id, q["amount"]))
        conn.execute("UPDATE budget SET committed = committed + ? WHERE program_id=?",
                     (q["amount"], program_id))
        conn.execute(
            "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by) VALUES (?,?,?,?,?)",
            (program_id, "po_approval", f"PO approved: {po_number} — {vendor['name']} (${q['amount']:,.0f})",
             email, "founder"),
        )
        # stage the matching invoice as an inbox item (arrives 'later')
        conn.execute(
            "INSERT INTO inbox_items(program_id,kind,title,summary,payload,proposed_action)"
            " VALUES (?,?,?,?,?,?)",
            (program_id, "vendor_invoice",
             f"Vendor invoice: {vendor['name']} against {po_number}",
             "The vendor's billing request arrived. The OS 2-way-matched it against the PO.",
             json.dumps({"po_id": po_id, "amount": q["amount"], "po_number": po_number}),
             json.dumps({"action": "reconcile_invoice",
                         "label": "Reconcile & release funds",
                         "note": "2-way match vs PO; releases committed funds to actual."})),
        )
        snapshot = budget_snapshot(conn, program_id)
    conn.close()
    return {"po_number": po_number, "amount": q["amount"], "email": email,
            "email_used_llm": used_llm, "budget": snapshot}


def reconcile_invoice(po_id: int, invoice_amount: float | None = None,
                      program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Invoice -> 2-way match vs PO -> release funds (committed->actual) -> budget recompute."""
    conn = db.connect()
    po = conn.execute("SELECT * FROM purchase_orders WHERE id=? AND program_id=?",
                      (po_id, program_id)).fetchone()
    if po is None:
        conn.close()
        raise ValueError("PO not found")
    po = dict(po)
    amt = invoice_amount if invoice_amount is not None else po["amount"]
    tol = 0.02 * po["amount"]
    matched = abs(amt - po["amount"]) <= tol
    mismatch_note = "" if matched else (
        f" MISMATCH: invoice ${amt:,.0f} vs PO ${po['amount']:,.0f} — held for review.")

    with conn:
        inv_id = conn.execute(
            "INSERT INTO invoices(program_id,po_id,amount,status,match_notes) VALUES (?,?,?,?,?)",
            (program_id, po_id, amt, "matched" if matched else "mismatch", mismatch_note or "2-way match OK"),
        ).lastrowid
        if matched:
            # release funds: committed -> actual
            conn.execute("UPDATE commitments SET status='released' WHERE po_id=?", (po_id,))
            conn.execute(
                "UPDATE budget SET committed = committed - ?, actual = actual + ? WHERE program_id=?",
                (po["amount"], amt, program_id))
            conn.execute("UPDATE invoices SET status='paid' WHERE id=?", (inv_id,))
            conn.execute("UPDATE purchase_orders SET status='closed' WHERE id=?", (po_id,))
        conn.execute(
            "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by) VALUES (?,?,?,?,?)",
            (program_id, "invoice_reconcile",
             f"Invoice reconciled: {po['po_number']}",
             (f"2-way match OK; released ${amt:,.0f} committed→actual." if matched
              else mismatch_note), "founder"),
        )
        snapshot = budget_snapshot(conn, program_id)
    conn.close()
    return {"matched": matched, "amount": amt, "po_number": po["po_number"],
            "note": mismatch_note or "2-way match OK", "budget": snapshot}


if __name__ == "__main__":
    seed_financials()
    print("seeded financials")
