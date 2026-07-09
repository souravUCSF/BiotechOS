"""Minimal anonymization of the real corpus → committable per-program corpus.

Two program archives are supported, each with its own token map:

  Program A (TGTA kinase-inhibitor program):
    - target identity — TGTA/TGTA→TGTA, TGTA→TGTB, TGTA→Kinase-C;
    - amino-acid residues / mutations / positions (target-revealing);
    - SMILES → "[structure withheld]".

  Program B (TGTA-targeting ADC program):
    - payload name compound-x → [payload];
    - linker chemistry linker-x/linker-x/L2/linker-x/… → [linker];
    - reference/comparator ADC reference-ADC/reference-ADC/reference-ADC → [reference-ADC];
    - SMILES → "[structure withheld]".
    NOTE: TGTA (antibody target) is KEPT — Program B is a TGTA ADC. DAR (drug-
    antibody ratio) is a generic ADC metric and is KEPT. NO TGTA→TGTA remap.

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

# ---- Program B (ADC) identity obfuscation. -------------------------------------
# Order matters: match longer/compound linker tokens before the short standalone
# ones so "linker-x" isn't half-consumed. `vc` is matched case-sensitively as a
# standalone linker abbreviation; L1/L2/linker-x uppercase-only standalone.
_PROGRAM_B_SUBS = [
    # High-specificity identity tokens — GLUE-SAFE (no alnum boundary) because PDF
    # text extraction strips spaces (e.g. "mLofreference-ADC", "resistancetoreference-ADC"). These
    # strings are unambiguous enough that matching inside a run is safe.
    (re.compile(r"T[-\s]?reference-ADC|reference-ADC|(?<![A-Za-z0-9])reference-ADC(?![A-Za-z0-9])|"
                r"DS[-\s]?8201[a-z]?|reference-ADC|reference-mAb[-\s]?payload-1", re.I),
     "[reference-ADC]"),
    (re.compile(r"compound-x", re.I), "[payload]"),
    (re.compile(r"L2[-\s]?L1[-\s]?linker-x|vc[-\s]?linker-x|Val[-\s]?Cit[-\s]?linker-x|"
                r"linker-x[-\s]?linker-x|Val[-\s]?Cit|linker-x", re.I), "[linker]"),
    # standalone linker abbreviations — need boundaries to avoid nuking real words
    # (uppercase L1/L2/linker-x only; lowercase 'vc' too, case-insensitive here since
    # boundaried). linker-x/L1/L2 as standalone tokens are linker chemistry.
    (re.compile(rf"{_B}(?:linker-x|L1|L2|vc){_E}", re.I), "[linker]"),
]

# --- residual leak detectors, per program ---
_TARGET_LEAK = re.compile(r"\b(tgta|tgtb)\b", re.I)
_PROGRAM_B_LEAK = re.compile(
    r"(compound-x|val[-\s]?cit|linker-x|reference-ADC|ds[-\s]?8201|t[-\s]?reference-ADC|reference-ADC|"
    r"(?<![A-Za-z0-9])reference-ADC(?![A-Za-z0-9])|reference-mAb[-\s]?payload-1|"
    r"(?<![A-Za-z0-9])(?:linker-x)(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])L2[-\s]?L1[-\s]?linker-x(?![A-Za-z0-9]))", re.I)

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
