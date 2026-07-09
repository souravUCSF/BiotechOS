# BiotechOS evals

Regression evals for the fuzzy components: QueryOS Q&A, extraction/classification,
identity resolution, decisions. Cases are JSONL (one per line) in this folder;
you author them. Grading is **LLM-judge-primary** for free-text (qa), with cheap
deterministic guardrails (groundedness, must-include/exclude) that can hard-fail.

## Run
```bash
cd backend
uv run python -m biotechos.evals run                 # all suites
uv run python -m biotechos.evals run qa classify     # subset
uv run python -m biotechos.evals run qa --repeat 3    # judge N times, majority
uv run python -m biotechos.evals baseline             # set the regression baseline
```
Each run prints a scorecard, diffs against `baseline.json`, and saves a JSON to
`results/` (gitignored). Requires `ANTHROPIC_API_KEY` for the judge; without it,
qa falls back to deterministic guardrails.

## Authoring helpers (curate, don't write blind)
```bash
# print the current answer + citations for a question → edit into a qa case
uv run python -m biotechos.evals capture "which cell lines can Vendor 2 test?"
# dump N corpus docs with the system's predicted labels → correct them
uv run python -m biotechos.evals sample classify --n 20 > /tmp/stub.jsonl
uv run python -m biotechos.evals sample fields   --n 20 >> /tmp/stub.jsonl
```

## Case schemas (append to the matching `<suite>.jsonl`)

**qa.jsonl** — judge compares the system answer to `reference_answer`; guardrails enforce include/exclude, source, citations, groundedness.
```json
{"id":"qa-x","question":"…","reference_answer":"the gold answer",
 "expect_source":"facts|documents|none","must_include":["…"],"must_not_include":["…"],
 "min_citations":1,"rubric":"extra grading guidance"}
```

**classify.jsonl** — exact-match on triage/doc_type. Reference a doc by `doc_subject` (substring) or `doc_id`.
```json
{"id":"cl-x","doc_subject":"Program A CDA","expect":{"triage":"actionable","doc_type":"contract"}}
```

**fields.jsonl** — exact for scalars (vendor/total), set-recall for lists (cell_lines/services).
```json
{"id":"fx-x","doc_subject":"…","expect":{"vendor":"Vendor 1","services":["intact_ms"]},"min_recall":1.0}
```

**identity.jsonl** — resolution status + optional same-molecule check.
```json
{"id":"id-x","token":"btx_1000","expect_status":"resolved","expect_same_as":"BTX-1000"}
{"id":"id-y","token":"ZZZ-99999","expect_status":"unresolved"}
```

**decision.jsonl** — inbox recommendation exact-match.
```json
{"id":"dec-x","doc_subject":"…IntactMS Assays","expect_recommendation":"review_quote"}
```

## Notes
- `doc_subject` is a substring match against `documents.subject`; use a distinctive
  string so it resolves to the doc you mean.
- Corpus content is target/structure-anonymized but vendor/person/codes are real,
  so cases use real vendor names (Vendor 1, Vendor 2, …).
- Commit `*.jsonl` + `baseline.json`; `results/` is gitignored.
