"""Encrypted-attachment handling.

Some CRO attachments are password-protected, with the password arriving in a
separate email from the same sender/domain. Resolution order:
  1. explicit password in a related email body (same domain / thread / near in time)
  2. a stored password for that vendor domain (vendor_credentials — local only)
  3. give up → caller queues a 🔒 'locked_attachment' item
Discovered passwords persist to vendor_credentials for reuse.
"""
from __future__ import annotations

import re

from ..state import db

# "password is ABC123", "PW: ABC123", "passcode ABC-123"
_PW_RE = re.compile(
    r"(?:password|passcode|pass\s*word|pwd|pw)\s*(?:is|:|=)?\s*[\"'`]?([A-Za-z0-9@#!\-_.]{4,32})",
    re.I)


def domain_of(addr: str) -> str:
    m = re.search(r"@([\w.\-]+)", addr or "")
    return m.group(1).lower() if m else ""


def scan_for_passwords(text: str) -> list[str]:
    return [m.group(1) for m in _PW_RE.finditer(text or "")]


def stored_passwords(program_id: str, domain: str, conn=None) -> list[str]:
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = conn.execute(
            "SELECT password FROM vendor_credentials WHERE program_id=? AND domain=? "
            "ORDER BY confidence DESC", (program_id, domain)).fetchall()
        return [r["password"] for r in rows]
    finally:
        if own:
            conn.close()


def remember_password(program_id: str, domain: str, password: str,
                      source_document_id: int | None = None, conn=None) -> None:
    own = conn is None
    conn = conn or db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO vendor_credentials(program_id,domain,password,source_document_id) "
                "VALUES (?,?,?,?)", (program_id, domain, password, source_document_id))
    finally:
        if own:
            conn.close()


def candidate_passwords(program_id: str, sender_domain: str, related_texts: list[str],
                        conn=None) -> list[str]:
    """Passwords to try, best-first: stored for domain, then scanned from related emails."""
    out: list[str] = list(stored_passwords(program_id, sender_domain, conn=conn))
    for t in related_texts:
        for pw in scan_for_passwords(t):
            if pw not in out:
                out.append(pw)
    return out


def try_decrypt(path: str, password: str) -> str | None:
    """Attempt to decrypt a PDF/Office file with `password`; return extracted text or None."""
    p = str(path)
    try:
        if p.lower().endswith(".pdf"):
            from pypdf import PdfReader  # type: ignore
            r = PdfReader(p)
            if r.is_encrypted and r.decrypt(password) == 0:
                return None
            return "\n".join((pg.extract_text() or "") for pg in r.pages) or None
        if p.lower().endswith((".xlsx", ".docx", ".pptx")):
            import io
            import msoffcrypto  # type: ignore
            buf = io.BytesIO()
            with open(p, "rb") as f:
                office = msoffcrypto.OfficeFile(f)
                office.load_key(password=password)
                office.decrypt(buf)
            return f"[decrypted {len(buf.getvalue())} bytes]"  # extraction handled elsewhere
    except Exception:
        return None
    return None
