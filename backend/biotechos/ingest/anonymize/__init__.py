"""Minimal anonymization of the real corpus → committable TGTA corpus.

SCOPE (deliberately narrow, per product decision): anonymize ONLY
  (1) the target identity — TGTA/TGTA→TGTA, TGTA→TGTB, TGTA→Kinase-C;
  (2) chemical structures — SMILES strings scrubbed to "[structure withheld]";
  (3) chemical images — dropped (we keep extracted *text* only, never re-render figures).
Everything else is preserved verbatim: vendor names, people, email domains, phone
numbers, molecule/project codes, and the original folder slugs.

Output: CORPUS_DIR (committed). Real numbers, prose, timelines, workflow intact.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ...config import CORPUS_DIR, CORPUS_ORG
from ..mailbox import RealMailboxSource

# Alnum-aware boundaries: treat '_','-','/','.',space as separators (plain \b
# fails on underscore-joined tokens like CTGTA_CATX).
_B, _E = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
# Target remap only. Specific isoforms first, generic TGTA last.
_RAW_SUBS = [
    (rf"{_B}C[-\s]?TGTA{_E}", "TGTA"), (rf"{_B}TGTA[-\s]?1{_E}", "TGTA"),
    (rf"{_B}B[-\s]?TGTA{_E}", "TGTB"), (rf"{_B}A[-\s]?TGTA{_E}", "Kinase-C"),
    (rf"{_B}TGTA{_E}", "TGTA"),
]
_TOKEN_SUBS = [(re.compile(p, re.I), r) for p, r in _RAW_SUBS]
# residual target tokens that must NOT survive (the only leak class we care about)
LEAK_RE = re.compile(r"\b(tgta|tgtb)\b", re.I)

# Amino-acid residues / mutations / positions — these reveal the specific kinase
# even after the TGTA→TGTA rename (e.g. TGTA V600E, TGTA Y340D/Y341D, Cys covalent
# site). Require 3–4 digit positions so cell-line names (T47D, A375, H358) are NOT
# caught (kinase positions are 3-digit: 340/600/805; cell-line numbers are 2–3 with
# no trailing residue letter).
_MUT_RE = re.compile(r"\b[ACDEFGHIKLMNPQRSTVWY]\d{3,4}[ACDEFGHIKLMNPQRSTVWY]\b", re.I)  # V600E, y340e
_RES3 = "Ala|Arg|Asn|Asp|Cys|Gln|Glu|Gly|His|Ile|Leu|Lys|Met|Phe|Pro|Ser|Thr|Trp|Tyr|Val"
_RES3_RE = re.compile(rf"\b(?:{_RES3})-?\d{{1,4}}\b", re.I)                        # Cys805, Tyr340
_POS_RE = re.compile(r"\b(residue|position|codon|mutation)s?\s+(\d{1,4})\b", re.I)  # position 600

# SMILES-ish token: long chemistry run with ring/bond chars, not a URL/domain.
_SMILES_RE = re.compile(r"(?<![\w.=&?/])(?=[^\s]*[=#\[\]])[A-Za-z0-9@+\[\]()=#\\-]{14,}(?![\w.])")


def _smiles_repl(m: "re.Match") -> str:
    tok = m.group(0)
    if any(c in tok for c in "/%&?:") or "http" in tok.lower():
        return tok
    if not re.search(r"[cCnNoO]", tok) or not re.search(r"[=#\[\]()]", tok):
        return tok
    return "[structure withheld]"


def anonymize_text(s: str) -> str:
    if not s:
        return s
    for rx, repl in _TOKEN_SUBS:
        s = rx.sub(repl, s)
    # amino-acid residues / mutations / positions (target-revealing)
    s = _MUT_RE.sub("[mutation]", s)
    s = _RES3_RE.sub("[residue]", s)
    s = _POS_RE.sub(lambda m: f"{m.group(1)} [pos]", s)
    return _SMILES_RE.sub(_smiles_repl, s)


def leak_scan(*texts: str) -> list[str]:
    hits = []
    for t in texts:
        hits += [m.group(0) for m in LEAK_RE.finditer(t or "")]
    return sorted(set(hits))


def build_corpus(org: str = CORPUS_ORG, out_dir: Path = CORPUS_DIR,
                 limit: int | None = None, clean: bool = True) -> dict:
    """Read the raw archive, apply target+structure anonymization, write the
    committable corpus. Keeps real vendor/person/domain/phone/codes + slugs;
    drops attachment binaries/figures (extracted text only)."""
    src = RealMailboxSource(org)
    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    n, leaks = 0, []
    for em in src.emails():
        if limit and n >= limit:
            break
        box = "Inbox" if em.direction == "inbound" else "Sent"
        mmatch = re.match(r"(\d{4}-\d{2})", em.slug)
        month = mmatch.group(1) if mmatch else "unknown"
        # keep the real slug but scrub the target name from it (paths must not leak
        # the target either); rest of the slug (sender, subject words) stays real.
        slug = em.slug
        for rx, repl in _TOKEN_SUBS:
            slug = rx.sub(repl, slug)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-") or em.slug
        dest = out_dir / org / "Emails" / box / month / slug
        (dest / "extracted").mkdir(parents=True, exist_ok=True)
        subject = anonymize_text(em.subject)
        body = anonymize_text(em.body)
        # scrub the target name from filenames too (CTGTA_ADP-Glo… → TGTA_ADP-Glo…),
        # keeping the rest of the real filename intact.
        atts = [{"filename": anonymize_text(a.filename), "mimetype": a.mimetype,
                 "protected": a.protected, "text": anonymize_text(a.text)}
                for a in em.attachments]
        (dest / "email.txt").write_text(
            f"From: {em.email_from}\nTo: {em.email_to}\nSubject: {subject}\nDate: {em.date}\n\n{body}")
        (dest / "metadata.json").write_text(json.dumps({
            "from": em.email_from, "to": em.email_to, "subject": subject, "date": em.date,
            "attachments": [{"filename": a["filename"], "mimetype": a["mimetype"],
                             "protected": a["protected"]} for a in atts]}, indent=2))
        for a in atts:
            if a["text"]:
                # IMPORTANT: name the extracted file exactly `<attachment-stem>.txt`
                # so the corpus reader (which derives it from metadata's filename)
                # finds it. Sanitizing here silently dropped attachment text for any
                # filename with spaces/special chars (most quote/data PDFs).
                (dest / "extracted" / (Path(a["filename"]).stem + ".txt")).write_text(a["text"])
        leaks += leak_scan(subject, body, *[a["text"] for a in atts])
        n += 1
    return {"threads": n, "out_dir": str(out_dir), "leaks": sorted(set(leaks))[:20],
            "leak_count": len(set(leaks))}
