---
name: anonymize-corpus
description: One-way anonymize a real email/document archive into a committable, shareable corpus — obfuscating molecule structures, target identity, vendor + person PII while preserving numbers, prose, timelines, and workflow. Use when onboarding a new private dataset (emails/quotes/invoices/CRO data) into BiotechOS, or re-running anonymization after the raw archive changes.
---

# Anonymize a document/email corpus

Turns a real archive (`~/DataStore/<Org>/Emails/...`) into a de-identified corpus
under `data/corpus/` that is safe to commit to GitHub. **One-way** (no reverse key).
The raw archive stays outside the repo; the `real→surrogate` maps stay gitignored
in `data/corpus_maps/`.

## What it guarantees
- **Targets** remapped (default TGTA/TGTA→TGTA, TGTA→TGTB, TGTA→Kinase-C).
- **Molecule/project codes** → surrogate, number-preserving + consistent (`CLO-00002→HLX-00002`, `PH-PGMA-…→AX-HLX-…`).
- **Vendors** → pseudonyms (company names + email domains).
- **People** → pseudonyms (built from sender display names; founder → "Sam Founder").
- **Structures/SMILES + figures** dropped (`[structure withheld]`); **numbers kept real**.
- **Paths too**: pseudonym org dir (`DemoOrg/`) + hashed, subject-derived slugs + neutralized attachment filenames — no real token in any file path.
- **Leak-scan = 0** for real tokens/domains/names in both paths and contents.

## Files
- Engine: `backend/biotechos/ingest/anonymize/__init__.py` — maps + `Anonymizer` + `build_corpus()`.
- Reader: `backend/biotechos/ingest/mailbox.py` — `RealMailboxSource` (raw) / `AnonymizedCorpusSource` (output).
- Config: `backend/biotechos/config.py` — `DATASTORE_ROOT`, `CORPUS_ORG`, `CORPUS_DIR`, `CORPUS_MAPS_DIR`, `MAILBOX_SOURCE`.
- Archive layout (in + out): `<root>/<Org>/Emails/{Inbox,Sent}/YYYY-MM/<slug>/{email.txt, metadata.json, attachments/, extracted/*.txt}`.

## Run it
```bash
cd backend
# optional: point at a different archive / org (defaults: ~/DataStore, Program A)
export DATASTORE_ROOT=/path/to/archive CORPUS_ORG=Program A
uv run python -c "from biotechos.ingest.anonymize import build_corpus; print(build_corpus())"
# → writes data/corpus/<ANON_ORG>/... ; prints {threads, out_dir, leak_count, leaks}
```
`build_corpus(limit=N)` for a quick dry run; `clean=True` (default) wipes `data/corpus/` first.

## Adapt to a NEW dataset (the part to edit)
In `ingest/anonymize/__init__.py`:
1. **`ANON_ORG`** — pseudonym company/org dir name for output paths.
2. **`_RAW_SUBS`** — ordered `(regex, replacement)`; add this dataset's **targets, vendors, sponsor code-abbreviations, founder/company names**. Use the alnum-aware boundaries `_B`/`_E` (NOT `\b`) so underscore-joined tokens like `FOO_BAR` are caught. Specific/multi-word entries first.
3. **`DOMAIN_SUBS`** — every real email domain → a `*.example` pseudo-domain.
4. **`code_alias()`** — prefix rewrites for the dataset's molecule/project code scheme (number-preserving).
5. **`LEAK_RE` + `DOMAIN_LEAK_RE`** — the tokens/domains the verifier must prove are gone.
6. Pseudonyms must NOT contain a real token as a substring (e.g. avoid "CellVista" if "Vendor 3" is a real vendor).

## Verify (always, after any map change)
`build_corpus()` returns `leak_count` from the in-pass scan. Then run an **independent** scan over the written files (catches path leaks + anything the in-pass scan's field list missed):
```bash
cd /path/to/repo
# real tokens/domains/names in BOTH paths and contents — must be 0
{ find data/corpus -print; grep -rniE '.' data/corpus/ 2>/dev/null; } \
  | grep -iE '\b(REAL_TARGET|REAL_VENDOR1|REAL_VENDOR2|REAL_PERSON)\b|(realdomain1|realdomain2)\.com' | wc -l
```
Also confirm the remap landed (e.g. TGTA/TGTB mentions > 0) and structures are gone.

## Gotchas (learned)
- `\b` fails around `_` — use `_B`/`_E`.
- Company/role display names ("Vendor 1 invoice") must be scrubbed by token subs, not registered as people; run vendor token subs **before** person-name subs.
- Multi-recipient `To:` lines and inline quoted headers in bodies — scrub every `local@domain` token (map domain, genericize local part), not just the first address.
- Attachment filenames + directory slugs leak too — neutralize both, not just body text.
- SMILES scrub must exclude URL/tracking cruft (web punctuation) to avoid mislabeling junk as structures.
- Maps persist in `data/corpus_maps/maps.json`; delete it for a fully fresh pseudonym assignment.
