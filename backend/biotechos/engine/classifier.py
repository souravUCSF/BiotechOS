"""The email classifier — THE single place the machine's classification lives.

One LLM call assigns an incoming email exactly one CATEGORY. It judges by the
newest message in the thread + any attachment (via triage.classify_input), which
is where the real signal is — not the subject line or old quoted history.

To change how emails are classified, edit `CATEGORIES` and `INSTRUCTIONS` here and
nowhere else: extract (ingest), triage_document (re-triage), the mailbox filter and
the eval suite all read their labels from this module.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..config import MODEL_ARTIFACTS
from . import llm

# The categories, in priority order. Keep this list and INSTRUCTIONS in sync.
CATEGORIES = ["quote", "invoice", "legal", "data", "other"]

# THE classification instructions the model uses. Single source of truth.
INSTRUCTIONS = (
    "You classify ONE incoming email for a drug-discovery team into EXACTLY ONE "
    "category. Weight the MOST RECENT message in the thread and any ATTACHMENT most "
    "heavily; ignore older quoted history, and do not be fooled by keywords in the "
    "subject line or a filename.\n"
    "\n"
    "Categories:\n"
    "- quote: a vendor's price quote. Typically comes from a vendor and contains line "
    "items / descriptions of services with their costs in USD.\n"
    "- invoice: a bill for work done. Usually says 'invoice' explicitly, states an "
    "amount due, and includes payment/remittance details (bank, wire, terms).\n"
    "- legal: a legal document to review — usually a doc or PDF attachment that reads "
    "like an NDA, CDA, MSA, or terms of service.\n"
    "- data: experimental results — an explanation of a recent experiment with numbers "
    "or descriptors. Most often an attachment, but sometimes inline sentences or a "
    "table.\n"
    "- other: anything else — questions, scheduling, status updates, shipping/logistics, "
    "a password to open a file, marketing. If it isn't clearly one of the four above, "
    "it is 'other'.\n"
    "\n"
    "A message that merely REFERENCES a document (a filename in the subject, a password "
    "to decrypt a PDF, 'please see attached') but contains none of that content itself "
    "is 'other'. Return the category, a one-line reason, and confidence 0-1."
)


class Classification(BaseModel):
    category: str
    reason: str = ""
    confidence: float = 0.6


def normalize(category: str) -> str:
    c = (category or "").strip().lower()
    return c if c in CATEGORIES else "other"


def _fallback(email) -> Classification:
    """No API key: map the deterministic keyword classifier's doc_type into the five."""
    from .triage import classify_input
    from . import extract as X
    text = classify_input(email)
    dt = X.classify(getattr(email, "subject", "") or "", text, "")
    m = {"quote": "quote", "invoice": "invoice", "contract": "legal", "cro_data": "data"}
    return Classification(category=m.get(dt, "other"), reason="keyword fallback (no API key)",
                          confidence=0.4)


def classify_email(email, api_key: str | None = None) -> Classification:
    """Classify one Email-like object into a single CATEGORY, LLM-first."""
    from .triage import classify_input
    text = classify_input(email)
    user = (f"From: {getattr(email, 'email_from', '')}\n"
            f"Subject: {getattr(email, 'subject', '')}\n\n"
            f"EMAIL — newest message + attachments (classify THIS):\n{text[:6000]}")
    res, _ = llm.structured(model=MODEL_ARTIFACTS, system=INSTRUCTIONS, user=user,
                            schema=Classification, fallback=_fallback(email),
                            api_key=api_key, max_tokens=300)
    res.category = normalize(res.category)
    return res
