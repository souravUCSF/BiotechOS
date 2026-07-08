# Claude-Status.md — BiotechOS

Project snapshot. **Read at session start; update at session end (and as you go).** Transient state and project-specific bugs live here; durable structure lives in `Architecture.md`.

_Last updated: 2026-07-08._

## Current goal

Building **Inbox v2** — a document-driven business layer (corpus + knowledge store + decision loop) per the approved plan `~/.claude/plans/abundant-mapping-platypus.md`. Three tabs: Current Inbox / QueryOS / Tasks.

## Inbox v2 progress (Phase 1)
- **Done & pushed (commit dc9d912):**
  - Schema: `documents`, `observations`, `facts` (bitemporal world model), `molecule_aliases`, `vendor_credentials`, `vendors` enrichment, `documents_fts` (FTS5); migrations on startup.
  - `engine/identity.py` — canonical molecule id + alias resolution (norm key collapses dash/zero-pad drift; InChIKey merge; inline-declaration learning; passport). Corpus-learned only, no external seed.
  - `ingest/mailbox.py` (Real/Anonymized sources over on-disk archive) + `ingest/decrypt.py` (password-protected attachments).
  - `ingest/anonymize/` — one-way anonymizer (TGTA/TGTA→TGTA, TGTA→TGTB, TGTA→Kinase-C; surrogate codes; vendor+person PII masking; drop structures/figures; keep numbers). **Leak-scan clean across 617 threads (paths + contents).** Output committed to `data/corpus/` (TGTA program's business corpus); maps gitignored in `data/corpus_maps/`. Raw archive external at `~/DataStore` (never committed).
  - `.claude/skills/anonymize-corpus` — reusable skill for new datasets.
- **Phase 1 COMPLETE (commit 729e0c8):** `engine/extract/` (triage + classifier[8 types] + decision_state + vendor_capability/quote/cro_data/query; harvests vendor cell-line+service facts from any vendor email); `engine/corpus/store.py` (ingest → documents+FTS5 + observations → promote agreed → bitemporal facts) + `qa.py` (facts-first grounded RAG, cited, "not found" allowed); API `/corpus/ingest` `/knowledge/ask` `/corpus/summary`; **QueryOS** tab. Verified: 617-thread corpus → "which cell lines can Vendor 22 test?" → CellLine-2/CellLine-1/PC9/HeLa/NCI-CellLine-1 with citations, de-identified. Ingest is fast (~3s); conn threaded through extract to avoid SQLite write-lock stalls; `busy_timeout=3000`.
- **Next — Phase 2 (Current Inbox):** rebuild `/` as email-envelope items (triaged; noise hidden) with extraction + analysis + context panel + decision branches (Quote→PO, Data→DB via `resolve_molecule(create=True)` merging surrogate-coded molecules into the BTX set, Query→reply); approval commits observations→facts + Decision Log. **Phase 3:** Tasks tab + invoice/contract/logistics agents.
- **Open:** molecule merge into BTX set (surrogate codes) happens in the Data→DB branch (Phase 2), not yet wired. Vendor-name masking kept (pseudonyms); flip if you want real names.

## Prior phase (metric catalog + Boltz) — done

## What's done (this phase)

- **Servers run:** backend :8010 (`uv run uvicorn …`), frontend :3000. Both verified rendering real data (Inbox, Molecule Dashboard).
- **TPP criterion builder redesigned:** single mode groups a specific "Anti-proliferation by cell line" section; composite mode builds `A [÷×−+] B` structurally. Scores end-to-end on 275 molecules.
- **Metric catalog curated:**
  - TGTA/TGTB **selectivity is now a composite** (`formula:tgta_vs_tgtb_selectivity = tgtb_ic50 / tgta_ic50`), removed as a raw input. Reproduces the old stored selectivity exactly (r=1.000).
  - Pooled **kinetics/xenograft/tox/adme panels decomposed** into 14 `meas:` measurement-specific metrics (kinact, mrt, tgi, cytotox, dili, t_half, bioavail, vdss, auc, cmax, ppb, stability, clearance [unit-filtered mL/min/kg], permeability [unit-filtered cm/s]). Pooled panels removed.
  - Composite property analysis done; user chose NOT to add extra composites (only the selectivity one and the pre-existing `cellular_biochemical_ratio` remain).
- **Molecule cards configurable from full catalog:** card fields are metric keys resolved via `/molecules/values`; configurator lists the whole grouped catalog; stale/legacy keys filtered so cards show exactly the checked boxes.
- **Folding target = PDB ID / UniProt ID / protein sequence** (per-program `fold_settings.target_kind`/`target_value`). TGTA program seeded with the user's verbatim 268-aa sequence.
- **Boltz run on the 3 favorites (BTX-1002 id=3, BTX-1050 id=51, BTX-1217 id=218):**
  - 3× structure-and-binding ($0.05 ea) + 3× ADME ($0.01 ea) = **$0.18 total**. Outputs in `/Users/Founder/docking/BiotechOS_cofold/`.
  - 9 `boltz:` metrics now in the catalog (ipTM, pTM, ligand_ipTM, structure_confidence, complex_pLDDT, binding_confidence, optimization_score, lipophilicity, permeability), stored in `molecules.boltz_json`. Solubility class stored as `solubility_class` (categorical, not a numeric metric).
  - Co-fold CIFs converted to PDB (gemmi) and serve the flip-card 3D viewer; verified rendering with no errors.

- **Card fields default to the TPP's metrics (done):** when no saved selection, cards pre-check exactly the current `tpp_params` metrics (deduped). Retired keys remapped via `RETIRED_KEY_MAP` in `molecules/page.tsx` (`assay:selectivity:TGTA/TGTB` → `formula:tgta_vs_tgtb_selectivity`) so they stay valid. Explicit user selections still persist and win.
- **Co-fold 3D label = ligand ipTM (done):** real Boltz co-folds label as `Boltz ligand ipTM X.XX` (from `boltz_json.ligand_iptm`, `structure._cofold_label`); falls back to "Boltz co-fold", and non-folded molecules still show "Predicted structure (co-fold pending)".

## Deferred / not yet done

- Wire `enqueue_fold` to actually submit Boltz on ingest (currently a no-op; `store_cofold_cif` helper exists for the CIF→PDB step).
- Fold ChEMBL→preferred-name mapping into ingest for fresh loads.
- Live Gmail vendor draft for the CFO loop.
- Second program to demo switching.

## Project-specific gotchas (this stack)

- **`/metrics` O(n²) hazard:** formula metrics resolve via `catalog()` per molecule → memoized by `_alias_map` lru_cache (cleared in `define_custom`). If you add another catalog-rebuilding call in the resolve path, watch for timeouts.
- **3Dmol + Boltz mmCIF:** 3Dmol's CIF reader throws `Cannot read properties of undefined (reading 'symmetries')` on Boltz's minimal CIF. Always convert to PDB (gemmi) before serving.
- **Playwright selector trap:** `page.locator('select').nth(0)` targets the nav ProgramSwitcher, not modal selects. Target by container/text, not index.
- **Migrations:** don't run only in ingest — they now also run on API startup (`@app.on_event("startup")` → `db.init_db(reset=False)`). New columns need an entry in `db.py` `_MIGRATIONS`.
- **`/molecules/values` param is `metrics=` (comma-joined keys), not `keys=`.**
- Backend must be restarted after `metrics.py`/engine edits (no `--reload`).

## Version control

Repo `souravUCSF/BiotechOS` (private), branch `main` (session's established workflow commits directly to main). This session's work committed + pushed 2026-07-07 as the checkpoint below. `backend/secrets.env` is gitignored; Boltz outputs live outside the repo at `/Users/Founder/docking/BiotechOS_cofold/`.
