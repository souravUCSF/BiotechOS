"""Mailbox ingestion — normalized reader over an on-disk email archive.

Layout (both the real archive and the anonymized corpus use it):
    <root>/<org>/Emails/{Inbox,Sent}/YYYY-MM/<slug>/
        email.txt        From/To/Subject/Date headers + body
        metadata.json    {uid, from, to, subject, date, attachments:[{filename,mimetype,protected}]}
        attachments/     raw attachment files
        extracted/       <name>.txt extracted attachment text (+ optional .entities.md)

Two sources share this reader:
  - RealMailboxSource      → raw archive at DATASTORE_ROOT/<org> (local only)
  - AnonymizedCorpusSource → committed anonymized copy at CORPUS_DIR (see anonymize/)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import DATASTORE_ROOT, CORPUS_DIR, CORPUS_ORG, MAILBOX_SOURCE


@dataclass
class Attachment:
    filename: str
    mimetype: str = ""
    protected: bool = False
    text: str = ""            # extracted text (may be empty if locked/undecrypted)
    path: str | None = None   # absolute path to the raw file


@dataclass
class Email:
    slug: str
    direction: str            # inbound | outbound
    email_from: str = ""
    email_to: str = ""
    subject: str = ""
    date: str = ""
    body: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    source_ref: str | None = None

    @property
    def full_text(self) -> str:
        parts = [f"Subject: {self.subject}", self.body]
        for a in self.attachments:
            if a.text:
                parts.append(f"\n--- attachment: {a.filename} ---\n{a.text}")
        return "\n".join(p for p in parts if p)


def _parse_email_txt(text: str) -> tuple[dict, str]:
    """Split leading 'Header: value' lines from the body."""
    headers, lines = {}, text.splitlines()
    i = 0
    for i, line in enumerate(lines):
        if not line.strip():
            break
        if ":" in line and line.split(":", 1)[0].strip().lower() in (
                "from", "to", "cc", "subject", "date"):
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        elif i > 6:
            break
    body = "\n".join(lines[i:]).strip()
    return headers, body


def _read_thread(slug_dir: Path, direction: str) -> Email | None:
    et = slug_dir / "email.txt"
    if not et.exists():
        return None
    headers, body = _parse_email_txt(et.read_text(errors="ignore"))
    meta = {}
    mj = slug_dir / "metadata.json"
    if mj.exists():
        try:
            meta = json.loads(mj.read_text())
        except json.JSONDecodeError:
            meta = {}
    extracted = slug_dir / "extracted"
    atts: list[Attachment] = []
    for a in meta.get("attachments", []) or []:
        fn = a.get("filename", "")
        txt = ""
        if extracted.exists():
            cand = extracted / (Path(fn).stem + ".txt")
            if cand.exists():
                txt = cand.read_text(errors="ignore")
        raw = slug_dir / "attachments" / fn
        atts.append(Attachment(
            filename=fn, mimetype=a.get("mimetype", ""),
            protected=bool(a.get("protected", False)), text=txt,
            path=str(raw) if raw.exists() else None))
    return Email(
        slug=slug_dir.name, direction=direction,
        email_from=meta.get("from") or headers.get("from", ""),
        email_to=meta.get("to") or headers.get("to", ""),
        subject=meta.get("subject") or headers.get("subject", ""),
        date=meta.get("date") or headers.get("date", ""),
        body=body, attachments=atts, source_ref=str(slug_dir),
    )


def _iter_archive(base: Path):
    """Yield Email for every thread under <base>/Emails/{Inbox,Sent}/YYYY-MM/<slug>/."""
    for box, direction in (("Inbox", "inbound"), ("Sent", "outbound")):
        boxdir = base / "Emails" / box
        if not boxdir.is_dir():
            continue
        for month in sorted(boxdir.iterdir()):
            if not month.is_dir():
                continue
            for slug in sorted(month.iterdir()):
                if slug.is_dir():
                    em = _read_thread(slug, direction)
                    if em:
                        yield em


class RealMailboxSource:
    """Raw archive at DATASTORE_ROOT/<org> — LOCAL ONLY, never committed."""

    def __init__(self, org: str = CORPUS_ORG):
        self.base = DATASTORE_ROOT / org

    def emails(self):
        yield from _iter_archive(self.base)


class AnonymizedCorpusSource:
    """Committed anonymized copy at CORPUS_DIR (safe to sync). If `org` is given,
    reads only CORPUS_DIR/<org>/; otherwise iterates every org subdir."""

    def __init__(self, base: Path = CORPUS_DIR, org: str | None = None):
        self.base = Path(base)
        self.org = org

    def emails(self):
        if not self.base.is_dir():
            return
        if self.org:
            org = self.base / self.org
            if (org / "Emails").is_dir():
                yield from _iter_archive(org)
            return
        for org in sorted(self.base.iterdir()):
            if (org / "Emails").is_dir():
                yield from _iter_archive(org)


def get_source(kind: str | None = None, org: str | None = None):
    kind = kind or MAILBOX_SOURCE
    if kind == "real":
        return RealMailboxSource(org) if org else RealMailboxSource()
    return AnonymizedCorpusSource(org=org)
