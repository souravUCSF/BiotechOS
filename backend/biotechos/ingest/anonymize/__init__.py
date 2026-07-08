"""One-way anonymization of the real Program A corpus → committable TGTA corpus.

Deterministic, consistent substitution applied to every email + extracted
attachment text. Structures and target identity are obfuscated; numbers, prose,
timelines, and workflow structure are preserved.

Decisions (locked): TGTA/TGTA→TGTA (on-target), TGTA→TGTB (anti-target),
TGTA→Kinase-C; surrogate molecule codes; drop structure figures/SMILES; keep real
numbers; mask vendor + person PII; one-way (no reverse key).

Output: CORPUS_DIR (committed, safe). Maps: CORPUS_MAPS_DIR (gitignored, secret).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from ...config import CORPUS_DIR, CORPUS_MAPS_DIR, CORPUS_ORG
from ..mailbox import RealMailboxSource

ANON_ORG = "DemoOrg"   # pseudonym org dir for the committed corpus (no real name in paths)

# --- static maps (real → surrogate) ---------------------------------------
# Alnum-aware boundaries: treat '_', '-', '/', '.', space as separators (plain \b
# fails on underscore-joined tokens like CTGTA_CATX / Vendor 1_Program-A).
_B, _E = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
# Authoritative ordered token scrub — the final pass; guarantees leak_scan≈0.
# Specific/multi-word first. Applied case-insensitively to ALL output text.
_RAW_SUBS = [
    # targets
    (rf"{_B}C[-\s]?TGTA{_E}", "TGTA"), (rf"{_B}TGTA[-\s]?1{_E}", "TGTA"),
    (rf"{_B}B[-\s]?TGTA{_E}", "TGTB"), (rf"{_B}A[-\s]?TGTA{_E}", "Kinase-C"),
    (rf"{_B}TGTA{_E}", "TGTA"),
    # sponsor/site code abbreviations (PGMA=Program A, PGMB=Program B, CT-SB=Program A)
    (rf"{_B}PGMA{_E}", "HLX"), (rf"{_B}PGMB{_E}", "HLX"), (rf"{_B}CT-?SB{_E}", "HLX"),
    # vendors / companies (specific first)
    (r"Program A\s+Therapeutics", "Demo Org"), (rf"{_B}program-atx{_E}", "demoorg"),
    (rf"{_B}Program A{_E}", "Demo Org"),
    (r"Program B\s+Therapeutics", "Demo Org"), (rf"{_B}program-btx{_E}", "demoorg"),
    (rf"{_B}Program B{_E}", "Demo Org"),
    (rf"{_B}Vendor 1{_E}", "Vendor 23"),
    (r"ICE\s*Bioscience", "Vendor 22"), (r"ICE-?biosci\w*", "Vendor 22"),
    (r"Vendor 3\s*Biotech", "CrystalPath"), (rf"{_B}vendor-3{_E}", "crystalpath"),
    (r"Reaction\s*Biology", "NovaKin"), (rf"{_B}reactionbiology{_E}", "novakin"),
    (r"Crown\s*Bioscience", "CytoNova Labs"), (rf"{_B}CrownBio{_E}", "CytoNova Labs"),
    (rf"{_B}crownbio{_E}", "cytonova"),
    (r"BPS\s*Bioscience", "KinaseWorks"), (rf"{_B}bpsbioscience{_E}", "kinaseworks"),
    (rf"{_B}Chempartner{_E}", "SynthPartner"), (rf"{_B}Vendor 12{_E}", "GenoModels"),
    (rf"{_B}Vendor 9{_E}", "GlobalCRO"), (rf"{_B}Carnabio{_E}", "ReagentCo"),
    (rf"{_B}Vendor 7{_E}", "ReagentCo"),
    # founder / primary contact
    (r"Founder\s+Founder", "Sam Founder"), (rf"{_B}Founder{_E}", "Founder"),
    (rf"{_B}Founder{_E}", "Sam"),
]
_TOKEN_SUBS = [(re.compile(p, re.I), r) for p, r in _RAW_SUBS]
_PERSON_POOL = [
    "Jordan Lee", "Priya Nair", "Wei Chen", "Marco Rossi", "Elena Petrova",
    "David Kim", "Sara Okoye", "Tomas Vega", "Aisha Rahman", "Liam Walsh",
    "Nina Kowalski", "Diego Santos", "Mei Tanaka", "Omar Haddad", "Grace Lin",
]
DOMAIN_SUBS = {
    "vendor-1.example.com": "vendor-23.example", "vendor-3.example.com": "crystalpath.example",
    "vendor-2.example.com": "vendor-22.example", "vendor-4.example.com": "novakin.example",
    "vendor-5.example.com": "cytonova.example", "vendor-6.example.com": "kinaseworks.example",
    "vendor-7.example.com": "reagentco.example", "sb.vendor-7.example.com": "reagentco.example",
    "vendor-8.example.com": "reagentco.example", "example-a.com": "demoorg.example",
    "example-b.com": "demoorg.example",
}
# real target-leak / vendor tokens that must NOT survive
LEAK_RE = re.compile(
    r"\b(tgta|tgtb|vendor-1|viva ?biotech|"
    r"ice-?biosci|reaction ?biology|crownbio|crown bioscience|bpsbioscience|"
    r"chempartner|biocytogen|carnabio|program-a|program-b)\b", re.I)
DOMAIN_LEAK_RE = re.compile("|".join(re.escape(d) for d in DOMAIN_SUBS))
# SMILES-ish token: long chemistry run containing ring/bond chars, but NOT a URL
# or dotted domain (no '.', ':', ' ').
_SMILES_RE = re.compile(r"(?<![\w.=&?/])(?=[^\s]*[=#\[\]])[A-Za-z0-9@+\[\]()=#\\-]{14,}(?![\w.])")


def _smiles_repl(m: "re.Match") -> str:
    tok = m.group(0)
    # URL/query cruft, not chemistry: has web punctuation or lacks ring/organic chars
    if any(c in tok for c in "/%&?:") or "http" in tok.lower():
        return tok
    if not re.search(r"[cCnNoO]", tok) or not re.search(r"[=#\[\]()]", tok):
        return tok
    return "[structure withheld]"


class Anonymizer:
    def __init__(self):
        CORPUS_MAPS_DIR.mkdir(parents=True, exist_ok=True)
        self._map_path = CORPUS_MAPS_DIR / "maps.json"
        self.maps = {"person": {}, "code": {}}
        if self._map_path.exists():
            self.maps.update(json.loads(self._map_path.read_text()))
        self._person_n = len(self.maps["person"])

    def save(self):
        self._map_path.write_text(json.dumps(self.maps, indent=2))

    # -- token maps --
    def person_alias(self, name: str) -> str:
        name = name.strip().strip("'\"")
        if not name or "@" in name:
            return name
        if re.search(r"Founder|Founder", name, re.I):
            return "Sam Founder"           # the founder (keep a stable pseudonym)
        # company/role display names are handled by TOKEN_SUBS, not the person map
        if re.search(r"vendor-1|viva|ice|reaction|crown|bps|vendor-9|chempartner|biocytogen|"
                     r"carna|program-a|program-b|invoice|billing|team|support|docusign|inc\b|"
                     r"bioscience|biotech|no-?reply|admin", name, re.I):
            return name
        if name not in self.maps["person"]:
            self.maps["person"][name] = _PERSON_POOL[self._person_n % len(_PERSON_POOL)] + \
                ("" if self._person_n < len(_PERSON_POOL) else f" {self._person_n // len(_PERSON_POOL) + 1}")
            self._person_n += 1
        return self.maps["person"][name]

    def code_alias(self, code: str) -> str:
        """CLO-00002→HLX-0002, CLO_RQ-7→HLX_RQ-7, PH-PGMA-*→AX-HLX-* (number-preserving)."""
        if code in self.maps["code"]:
            return self.maps["code"][code]
        c = code
        c = re.sub(r"\bCLO[_-]?RQ", "HLX_RQ", c, flags=re.I)
        c = re.sub(r"\bCLO", "HLX", c, flags=re.I)
        c = re.sub(r"\bPH-", "AX-", c, flags=re.I)     # PH (Vendor 1) → AX (Apex)
        c = re.sub(r"\bCT-", "HX-", c, flags=re.I)     # CT (Program A) → HX (Demo)
        c = re.sub(r"\b(PGMA|PGMB|DemoU)\b", "HLX", c, flags=re.I)
        self.maps["code"][code] = c
        return c

    def learn_people(self, names) -> None:
        """Pre-pass: register every real sender display name so its full-name
        occurrences (incl. email signatures) get substituted in body text."""
        for n in names:
            self.person_alias(n)

    # -- text transform --
    def text(self, s: str) -> str:
        if not s:
            return s
        # molecule / project codes first (before vendor 'PH' prefixes get mangled)
        s = re.sub(r"\bCLO[_-]?RQ[_-]?\d+\b|\bCLO[-_]?\d{2,}\b|\bPH-[A-Za-z]{2,}[A-Za-z0-9-]*\b|\bCT-[A-Za-z0-9-]{3,}\b",
                   lambda m: self.code_alias(m.group(0)), s, flags=re.I)
        # every email address (domain map + local-part scrub) — handles inline
        # quoted headers in bodies + multi-recipient To lines.
        s = re.sub(r"[\w.\-']+@[\w.\-]+", lambda m: self._email(m.group(0)), s)
        # bare domain mentions (no @), e.g. "vendor-1.example.com/logo.png"
        for real, fake in DOMAIN_SUBS.items():
            s = re.sub(re.escape(real), fake, s, flags=re.I)
        # authoritative token scrub (vendors/targets/founder) — company display
        # names handled here, never via the person map.
        for rx, repl in _TOKEN_SUBS:
            s = rx.sub(repl, s)
        # dynamic person full-names (longest first)
        for real in sorted(self.maps["person"], key=len, reverse=True):
            s = re.sub(re.escape(real), self.maps["person"][real], s, flags=re.I)
        s = _SMILES_RE.sub(_smiles_repl, s)
        return s

    def addr(self, addr: str) -> str:
        """Anonymize a From/To header (handles multiple comma-separated addrs)."""
        return self.text(addr) if addr else addr

    def _email(self, e: str) -> str:
        e = e.strip().strip("<>'\"")
        if "@" not in e:
            return e
        local, _, dom = e.partition("@")
        dom = DOMAIN_SUBS.get(dom.lower(), dom)
        local = "contact"  # local parts are almost always name-derived → generic
        return f"{local}@{dom}"

    def leak_scan(self, *texts: str) -> list[str]:
        hits: list[str] = []
        for t in texts:
            for m in LEAK_RE.finditer(t or ""):
                hits.append(m.group(0))
            for m in DOMAIN_LEAK_RE.finditer(t or ""):
                hits.append(m.group(0))
        return sorted(set(hits))


def anonymize_email(anon: Anonymizer, em) -> dict:
    """Return the anonymized on-disk representation of an Email (dict)."""
    body = anon.text(em.body)
    subject = anon.text(em.subject)
    atts = []
    for a in em.attachments:
        atts.append({"filename": anon.text(a.filename), "mimetype": a.mimetype,
                     "protected": a.protected, "text": anon.text(a.text)})
    return {
        "slug": em.slug, "direction": em.direction,
        "from": anon.addr(em.email_from), "to": anon.addr(em.email_to),
        "subject": subject, "date": em.date, "body": body, "attachments": atts,
    }


def build_corpus(org: str = CORPUS_ORG, out_dir: Path = CORPUS_DIR, limit: int | None = None,
                 clean: bool = True) -> dict:
    """Read the raw archive, anonymize, and write the committable corpus. Drops
    attachment binaries + structure figures (text only). Returns a summary + leak report."""
    anon = Anonymizer()
    src = RealMailboxSource(org)
    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    # pre-pass: register all sender/recipient display names so full names in
    # bodies + signatures get substituted consistently.
    all_emails = list(src.emails())
    for em in all_emails:
        for addr in (em.email_from, em.email_to):
            m = re.match(r"\s*\"?([^\"<]+?)\"?\s*<", addr or "")
            if m:
                anon.person_alias(m.group(1))
    n = 0
    leaks: list[str] = []
    for em in all_emails:
        if limit and n >= limit:
            break
        box = "Inbox" if em.direction == "inbound" else "Sent"
        # month + date from slug prefix YYYY-MM-DD
        dmatch = re.match(r"(\d{4}-\d{2})(-\d{2})?", em.slug)
        month = dmatch.group(1) if dmatch else "unknown"
        date_prefix = (dmatch.group(0) if dmatch else "unknown")
        # anonymized slug — the ORIGINAL slug contains real names/vendors, so we
        # rebuild it from anonymized subject + a stable hash (paths must not leak).
        a = anonymize_email(anon, em)
        subj_slug = re.sub(r"[^a-z0-9]+", "-", a["subject"].lower()).strip("-")[:48]
        h = hashlib.md5(em.slug.encode()).hexdigest()[:8]
        anon_slug = f"{date_prefix}_{h}_{subj_slug}".strip("_")
        dest = out_dir / ANON_ORG / "Emails" / box / month / anon_slug
        (dest / "extracted").mkdir(parents=True, exist_ok=True)
        (dest / "email.txt").write_text(
            f"From: {a['from']}\nTo: {a['to']}\nSubject: {a['subject']}\nDate: {a['date']}\n\n{a['body']}")
        (dest / "metadata.json").write_text(json.dumps({
            "from": a["from"], "to": a["to"], "subject": a["subject"], "date": a["date"],
            "attachments": [{"filename": at["filename"], "mimetype": at["mimetype"],
                             "protected": at["protected"]} for at in a["attachments"]],
        }, indent=2))
        for i, at in enumerate(a["attachments"]):
            if at["text"]:
                # neutralize the extracted filename too (raw filenames leak terms)
                stem = re.sub(r"[^a-z0-9]+", "-", Path(at["filename"]).stem.lower()).strip("-")[:40]
                (dest / "extracted" / f"att{i}_{stem or 'file'}.txt").write_text(at["text"])
        leaks += anon.leak_scan(a["subject"], a["body"], *[at["text"] for at in a["attachments"]])
        n += 1
    anon.save()
    return {"threads": n, "out_dir": str(out_dir), "leaks": sorted(set(leaks))[:20],
            "leak_count": len(set(leaks))}
