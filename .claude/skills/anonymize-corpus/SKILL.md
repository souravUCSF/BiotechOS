---
name: anonymize-corpus
description: Anonymize a real email/document archive into a committable corpus by scrubbing ONLY the biological target identity, chemical structures, and residue/mutation callouts — keeping vendor names, people, domains, phones, and codes real. Use when onboarding a private CRO dataset into BiotechOS or re-running after the raw archive changes.
---

# Anonymize a document/email corpus (narrow scope)

Turns a real archive (`~/DataStore/<Org>/Emails/…`) into a de-identified corpus
under `data/corpus/`, safe to commit to a **private** repo. **One-way.** Raw
archive stays outside the repo.

## Scope — what gets changed (deliberately narrow)
1. **Target identity** — `TGTA/TGTA→TGTA`, `TGTA→TGTB`, `TGTA→Kinase-C` (alnum-aware
   boundaries so `CTGTA_CATX` etc. are caught), in body, subject, attachment
   filenames, AND folder slugs (paths must not leak the target either).
2. **Chemical structures** — SMILES strings → `[structure withheld]`.
3. **Chemical images** — dropped (only extracted *text* is kept; figures never re-rendered).
4. **Amino-acid residues / mutations / positions** — `V600E`, `Y340D/Y341E`,
   `Cys805`, "position 600" → `[mutation]`/`[residue]`/`[pos]` (these reveal the
   specific kinase even after the target rename).

**Preserved verbatim:** vendor names, people, email domains, phone numbers,
molecule/project codes, real numbers, prose, timelines, workflow. (This means the
committed corpus contains real business PII — appropriate only for a private repo.)

## Files
- Engine: `backend/biotechos/ingest/anonymize/__init__.py` — `anonymize_text()`, `build_corpus()`, `leak_scan()`.
- Reader: `backend/biotechos/ingest/mailbox.py` (`RealMailboxSource`).
- Config: `backend/biotechos/config.py` (`DATASTORE_ROOT`, `CORPUS_ORG`, `CORPUS_DIR`).

## Run
```bash
cd backend
export DATASTORE_ROOT=/path/to/archive CORPUS_ORG=Program A   # defaults: ~/DataStore, Program A
uv run python -c "from biotechos.ingest.anonymize import build_corpus; print(build_corpus())"
# then refresh the DB: uv run python -c "from biotechos.engine.corpus import store; print(store.ingest('demo'))"
```
`build_corpus(limit=N)` for a dry run.

## Adapt to a NEW dataset
Edit `ingest/anonymize/__init__.py`:
1. `_RAW_SUBS` — the dataset's real target → surrogate map (use `_B`/`_E` boundaries, NOT `\b`).
2. `LEAK_RE` — the target tokens the verifier must prove are gone.
3. `_MUT_RE` / `_RES3_RE` / `_POS_RE` — residue/mutation forms (keep the 3–4 digit
   guard so cell-line names like `T47D`, `A375`, `H358` are NOT caught).
4. If your codes/IDs themselves encode the target, extend the slug/filename scrub.

## Verify (always — paths AND contents)
```bash
cd /path/to/repo
{ find data/corpus -print; grep -rniE '.' data/corpus/ 2>/dev/null; } \
  | grep -iE '\b(REAL_TARGET1|REAL_TARGET2|V600E|Y340D)\b|Cys[- ]?805' | wc -l   # must be 0
grep -rniE '\b(TGTA|TGTB)\b' data/corpus/ | wc -l   # target remap landed (>0)
```

## Gotchas (learned)
- `\b` fails around `_` — use `_B`/`_E`.
- The target leaks in **attachment filenames** and **folder slugs**, not just body text — scrub all three.
- Mutation regex must be case-insensitive (`y340e`) but digit-guarded (3–4) so cell lines aren't caught.
- SMILES scrub must skip URL/tracking cruft (web punctuation) to avoid mislabeling junk as structures.
