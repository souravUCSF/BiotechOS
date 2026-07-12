"""Minimal anonymization of the real corpus → committable per-program corpus.

Two program archives are supported, each with its own token map:

  Program A (TGTA kinase-inhibitor program):
    - target identity — TGTA/TGTA→TGTA, TGTA→TGTB, TGTA→Kinase-C;
    - amino-acid residues / mutations / positions (target-revealing);
    - SMILES → "[structure withheld]".

  Program B (targeted-biologic program):
    - payload / linker / reference-comparator tokens → neutral placeholders;
    - SMILES → "[structure withheld]".
    NOTE: the antibody target is KEPT (generic); DAR is a generic metric and is KEPT.

Everything else is preserved verbatim: vendor names, people, email domains, phone
numbers, molecule/project codes, and the original folder slugs (target/payload/
linker tokens scrubbed from slugs + filenames too, so paths don't leak).

Output: CORPUS_DIR/<org>/... (gitignored — third-party PII stays local).
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

# ---- Program A (TGTA kinase) target remap. Isoforms first, generic TGTA last. ----
_PROGRAM_A_SUBS = [
    (rf"{_B}C[-\s]?TGTA{_E}", "TGTA"), (rf"{_B}TGTA[-\s]?1{_E}", "TGTA"),
    (rf"{_B}B[-\s]?TGTA{_E}", "TGTB"), (rf"{_B}A[-\s]?TGTA{_E}", "Kinase-C"),
    (rf"{_B}TGTA{_E}", "TGTA"),
]

# ---- Program B identity obfuscation (placeholder table in the public repo; the real
# payload / linker / comparator token maps are supplied outside version control). ----
_PROGRAM_B_SUBS = [
    (re.compile(r"\[reference-ADC\]", re.I), "[reference-ADC]"),
    (re.compile(r"\[payload\]", re.I), "[payload]"),
    (re.compile(r"\[linker\]", re.I), "[linker]"),
]

# --- residual leak detectors, per program ---
_TARGET_LEAK = re.compile(r"\b(tgta|tgtb)\b", re.I)
_PROGRAM_B_LEAK = re.compile(r"\[(?:reference-ADC|payload|linker)\]", re.I)

# Amino-acid residues / mutations / positions (Program A only — reveal the kinase).
_MUT_RE = re.compile(r"\b[ACDEFGHIKLMNPQRSTVWY]\d{3,4}[ACDEFGHIKLMNPQRSTVWY]\b", re.I)
_RES3 = "Ala|Arg|Asn|Asp|Cys|Gln|Glu|Gly|His|Ile|Leu|Lys|Met|Phe|Pro|Ser|Thr|Trp|Tyr|Val"
_RES3_RE = re.compile(rf"\b(?:{_RES3})-?\d{{1,4}}\b", re.I)
_POS_RE = re.compile(r"\b(residue|position|codon|mutation)s?\s+(\d{1,4})\b", re.I)

# SMILES-ish token: long chemistry run with ring/bond chars, not a URL/domain.
_SMILES_RE = re.compile(r"(?<![\w.=&?/])(?=[^\s]*[=#\[\]])[A-Za-z0-9@+\[\]()=#\\-]{14,}(?![\w.])")


# --- per-org config ------------------------------------------------------------
class _OrgProfile:
    def __init__(self, token_subs, leak_re, scrub_residues: bool):
        self.token_subs = token_subs        # list[(compiled_regex, repl)]
        self.leak_re = leak_re
        self.scrub_residues = scrub_residues


_PROGRAM_A_PROFILE = _OrgProfile(
    [(re.compile(p, re.I), r) for p, r in _PROGRAM_A_SUBS], _TARGET_LEAK, scrub_residues=True)
_PROGRAM_B_PROFILE = _OrgProfile(_PROGRAM_B_SUBS, _PROGRAM_B_LEAK, scrub_residues=False)

_PROFILES = {"Program A": _PROGRAM_A_PROFILE, "Program B": _PROGRAM_B_PROFILE}


def _profile(org: str) -> _OrgProfile:
    return _PROFILES.get(org, _PROGRAM_A_PROFILE)


def _smiles_repl(m: "re.Match") -> str:
    tok = m.group(0)
    if any(c in tok for c in "/%&?:") or "http" in tok.lower():
        return tok
    if not re.search(r"[cCnNoO]", tok) or not re.search(r"[=#\[\]()]", tok):
        return tok
    return "[structure withheld]"


def anonymize_text(s: str, profile: _OrgProfile = _PROGRAM_A_PROFILE) -> str:
    if not s:
        return s
    for rx, repl in profile.token_subs:
        s = rx.sub(repl, s)
    if profile.scrub_residues:
        s = _MUT_RE.sub("[mutation]", s)
        s = _RES3_RE.sub("[residue]", s)
        s = _POS_RE.sub(lambda m: f"{m.group(1)} [pos]", s)
    return _SMILES_RE.sub(_smiles_repl, s)


def leak_scan(*texts: str, profile: _OrgProfile = _PROGRAM_A_PROFILE) -> list[str]:
    hits = []
    for t in texts:
        hits += [m.group(0) for m in profile.leak_re.finditer(t or "")]
        # SMILES must never survive in any org
        for m in _SMILES_RE.finditer(t or ""):
            if _smiles_repl(m) != m.group(0):
                hits.append(m.group(0))
    return sorted(set(hits))


def build_corpus(org: str = CORPUS_ORG, out_dir: Path = CORPUS_DIR,
                 limit: int | None = None, clean: bool = True) -> dict:
    """Read the raw archive for `org`, apply that org's anonymization, write the
    committable corpus to out_dir/<org>/... Keeps real vendor/person/domain/phone/
    codes + slugs; drops attachment binaries/figures (extracted text only)."""
    prof = _profile(org)
    src = RealMailboxSource(org)
    org_out = out_dir / org
    if clean and org_out.exists():
        shutil.rmtree(org_out)
    n, leaks = 0, []
    for em in src.emails():
        if limit and n >= limit:
            break
        box = "Inbox" if em.direction == "inbound" else "Sent"
        mmatch = re.match(r"(\d{4}-\d{2})", em.slug)
        month = mmatch.group(1) if mmatch else "unknown"
        # keep the real slug but scrub identity tokens from it (paths must not leak).
        slug = em.slug
        for rx, repl in prof.token_subs:
            slug = rx.sub(repl, slug)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-") or em.slug
        dest = out_dir / org / "Emails" / box / month / slug
        (dest / "extracted").mkdir(parents=True, exist_ok=True)
        subject = anonymize_text(em.subject, prof)
        body = anonymize_text(em.body, prof)
        atts = [{"filename": anonymize_text(a.filename, prof), "mimetype": a.mimetype,
                 "protected": a.protected, "text": anonymize_text(a.text, prof)}
                for a in em.attachments]
        (dest / "email.txt").write_text(
            f"From: {em.email_from}\nTo: {em.email_to}\nSubject: {subject}\nDate: {em.date}\n\n{body}")
        (dest / "metadata.json").write_text(json.dumps({
            "from": em.email_from, "to": em.email_to, "subject": subject, "date": em.date,
            "attachments": [{"filename": a["filename"], "mimetype": a["mimetype"],
                             "protected": a["protected"]} for a in atts]}, indent=2))
        for a in atts:
            if a["text"]:
                # name the extracted file exactly `<attachment-stem>.txt` so the
                # corpus reader (which derives it from metadata's filename) finds it.
                (dest / "extracted" / (Path(a["filename"]).stem + ".txt")).write_text(a["text"])
        leaks += leak_scan(subject, body, slug, *[a["filename"] for a in atts],
                           *[a["text"] for a in atts], profile=prof)
        n += 1
    return {"threads": n, "org": org, "out_dir": str(org_out),
            "leaks": sorted(set(leaks))[:20], "leak_count": len(set(leaks))}
