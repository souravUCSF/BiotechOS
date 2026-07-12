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


# ---------------------------------------------------------------------------
# PO document editor (the /po/{id} page): view / edit a draft PO, then issue it.
# The line items live on the PO itself (purchase_orders.line_items JSON); a PO
# minted from a quote inherits the quote's line items on first read.
# ---------------------------------------------------------------------------

def _po_line_items(conn, po: dict) -> list[dict]:
    """Line items for a PO, normalized to {description,quantity,amount}. Falls back
    to the source quote's items (shape {item,amount}) when the PO has none yet."""
    if po.get("line_items"):
        try:
            raw = json.loads(po["line_items"])
        except (TypeError, json.JSONDecodeError):
            raw = []
    elif po.get("quote_id"):
        q = conn.execute("SELECT line_items FROM quotes WHERE id=?", (po["quote_id"],)).fetchone()
        raw = json.loads(q["line_items"]) if q and q["line_items"] else []
    else:
        raw = []
    items = []
    for li in raw:
        items.append({
            "description": li.get("description") or li.get("item") or "",
            "quantity": li.get("quantity", 1),
            "amount": li.get("amount", 0),
        })
    return items


def _po_view(conn, po: dict) -> dict:
    vendor = None
    if po.get("vendor_id"):
        vendor = conn.execute("SELECT name FROM vendors WHERE id=?", (po["vendor_id"],)).fetchone()
    return {
        "id": po["id"],
        "program_id": po["program_id"],
        "vendor_name": po.get("vendor_name") or (vendor["name"] if vendor else None),
        "status": po["status"],
        "po_number": po["po_number"],
        "approved_at": po.get("approved_at") or po.get("created_at"),
        "line_items": _po_line_items(conn, po),
    }


def get_po(po_id: int, program_id: str = DEMO_PROGRAM_ID) -> dict:
    conn = db.connect()
    try:
        po = conn.execute("SELECT * FROM purchase_orders WHERE id=? AND program_id=?",
                          (po_id, program_id)).fetchone()
        if po is None:
            raise ValueError("PO not found")
        return _po_view(conn, dict(po))
    finally:
        conn.close()


def create_draft_po_from_document(program_id: str, document_id: int) -> dict:
    """Build a DTGTAT purchase order from a quote email's parsed quote_lines, so the
    user can review/issue it in the PO template editor (/po/{id}). Reuses one draft per
    document (idempotent) rather than spawning duplicates."""
    conn = db.connect()
    try:
        existing = conn.execute(
            "SELECT id FROM purchase_orders WHERE program_id=? AND source_document_id=? "
            "AND status='draft' ORDER BY id DESC LIMIT 1", (program_id, document_id)).fetchone()
        lines = conn.execute(
            "SELECT vendor, scope, service, compound, quantity, unit, amount FROM quote_lines "
            "WHERE program_id=? AND document_id=? ORDER BY id", (program_id, document_id)).fetchall()
        line_items = [{
            "description": (li["scope"] or li["service"] or li["compound"] or "Line item").strip(),
            "quantity": li["quantity"],
            "amount": round(float(li["amount"] or 0), 2),
        } for li in lines]
        amount = round(sum(li["amount"] for li in line_items), 2)
        vendor_name = next((li["vendor"] for li in lines if li["vendor"]), None)
        with conn:
            if existing:
                po_id = existing["id"]
                conn.execute(
                    "UPDATE purchase_orders SET line_items=?, vendor_name=?, amount=? WHERE id=?",
                    (json.dumps(line_items), vendor_name, amount, po_id))
            else:
                po_id = conn.execute(
                    "INSERT INTO purchase_orders(program_id,status,line_items,vendor_name,amount,"
                    "source_document_id) VALUES (?,'draft',?,?,?,?)",
                    (program_id, json.dumps(line_items), vendor_name, amount, document_id)).lastrowid
        return {"po_id": po_id, "line_items": len(line_items), "amount": amount,
                "vendor_name": vendor_name}
    finally:
        conn.close()


def update_po(po_id: int, line_items: list, vendor_name: str | None = None,
              program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Save edits to a DTGTAT PO's line items + vendor name. Issued POs are immutable."""
    conn = db.connect()
    try:
        po = conn.execute("SELECT * FROM purchase_orders WHERE id=? AND program_id=?",
                          (po_id, program_id)).fetchone()
        if po is None:
            raise ValueError("PO not found")
        po = dict(po)
        if po["status"] != "draft":
            return _po_view(conn, po)
        clean = [{"description": (li.get("description") or "").strip(),
                  "quantity": li.get("quantity"),
                  "amount": round(float(li.get("amount") or 0), 2)}
                 for li in line_items]
        amount = round(sum(li["amount"] for li in clean), 2)
        with conn:
            conn.execute(
                "UPDATE purchase_orders SET line_items=?, vendor_name=?, amount=? WHERE id=?",
                (json.dumps(clean), (vendor_name or "").strip() or None, amount, po_id))
            po = dict(conn.execute("SELECT * FROM purchase_orders WHERE id=?", (po_id,)).fetchone())
        return _po_view(conn, po)
    finally:
        conn.close()


def approve_po(po_id: int, program_id: str = DEMO_PROGRAM_ID) -> dict:
    """Issue a DTGTAT PO: assign a number, encumber the budget, draft the vendor
    cover email, and append the Decision Log. Mirrors approve_quote's tail but
    runs on an already-edited PO document. Idempotent for non-draft POs."""
    conn = db.connect()
    try:
        po = conn.execute("SELECT * FROM purchase_orders WHERE id=? AND program_id=?",
                          (po_id, program_id)).fetchone()
        if po is None:
            raise ValueError("PO not found")
        po = dict(po)
        items = _po_line_items(conn, po)
        vendor_name = po.get("vendor_name")
        if not vendor_name and po.get("vendor_id"):
            v = conn.execute("SELECT name FROM vendors WHERE id=?", (po["vendor_id"],)).fetchone()
            vendor_name = v["name"] if v else "Vendor"
        vendor_name = vendor_name or "Vendor"
        amount = round(sum(float(li.get("amount") or 0) for li in items), 2) or (po.get("amount") or 0)
        # email draft expects [{item, amount}]
        scope_items = [{"item": li["description"], "amount": li["amount"]} for li in items]
        email, used_llm = _draft_vendor_email(vendor_name, po.get("po_number") or _po_number(program_id, po_id),
                                               amount, scope_items or [{"item": "agreed scope", "amount": amount}])
        if po["status"] != "draft":
            return {"email": email, "email_used_llm": used_llm, "po_number": po["po_number"],
                    "status": po["status"]}
        po_number = po.get("po_number") or _po_number(program_id, po_id)
        with conn:
            conn.execute(
                "UPDATE purchase_orders SET status='issued', po_number=?, amount=?, "
                "email_draft_id=?, approved_at=datetime('now') WHERE id=?",
                (po_number, amount, f"draft:{po_id}", po_id))
            conn.execute("INSERT INTO commitments(program_id,po_id,amount,status) VALUES (?,?,?,'committed')",
                         (program_id, po_id, amount))
            conn.execute("UPDATE budget SET committed = committed + ? WHERE program_id=?",
                         (amount, program_id))
            if po.get("quote_id"):
                conn.execute("UPDATE quotes SET status='ordered' WHERE id=?", (po["quote_id"],))
            conn.execute(
                "INSERT INTO ledger_entries(program_id,kind,title,content,approved_by) VALUES (?,?,?,?,?)",
                (program_id, "po_approval",
                 f"PO issued: {po_number} — {vendor_name} (${amount:,.0f})", email, "founder"))
        return {"email": email, "email_used_llm": used_llm, "po_number": po_number, "status": "issued"}
    finally:
        conn.close()


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
