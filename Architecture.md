# Architecture.md — BiotechOS

Big-picture design and rationale. Read for structural work; update when the big picture changes (not for routine debugging — those go in `Claude-Status.md`).

## What this is

An operating system for running preclinical drug programs. Thesis: **the OS synthesizes, drafts, computes, and tracks; the human decides and signs** — so 1 FTE can run multiple programs. Started as a hackathon demo (TGTA kinase inhibitor program); being hardened into a real tool. Everything is partitioned by `program_id` so multi-program is a data property, not a bolt-on.

## Stack

- **Backend:** Python / FastAPI + SQLite. Run: `cd backend && uv run uvicorn biotechos.api.main:app --host 0.0.0.0 --port 8010`. (Port 8000 collides with a local service — always 8010. `--host 0.0.0.0` is required so non-localhost hostnames work.)
- **Frontend:** Next.js 16 + Tailwind v4 (`@theme` tokens; Pico-inspired light theme). Run on :3000. `next.config.ts` needs `allowedDevOrigins` for cross-origin hostnames (claw.local etc.). **NOTE:** `frontend/AGENTS.md` warns this Next.js has breaking changes vs training data — read `node_modules/next/dist/docs/` before writing Next code.
- **API base** derived at runtime from `window.location.hostname` (`src/lib/apiBase.ts`) so the app works from any hostname; CORS is `allow_origin_regex=".*"`.
- **LLM:** Anthropic SDK, keyless deterministic fallback. Models: TPP builder = `claude-opus-4-8`, artifacts = `claude-sonnet-4-6`, extraction = `claude-haiku-4-5`. Real key pasted into `backend/secrets.env` (GITIGNORED — never commit/echo). Boltz key lives there too.

## Core data model (`state/schema.sql`, keyed by `program_id`)

`programs`, `molecules` (SMILES, `favorite`, `adme_json` = RDKit-predicted physchem, `boltz_json` = Boltz-predicted props), `assays` (long-format: `modality`, `target`, `standard_type`, `value`, `units`, `cell_line`), `tpp_versions` + `tpp_params` (versioned TPP), `custom_metrics` (user-defined / derived-formula metrics), `fold_settings` (per-program folding target), plus inbox / ledger / competitive / financial tables. Migrations are non-destructive (`db.py` `_MIGRATIONS`, applied on `init_db(reset=False)` and on API startup).

## The metric catalog — the spine of everything

`engine/metrics.py` is the single source of truth for "what properties exist." Every property a molecule can have is a **metric** with a `key`, `alias` (short token for formulas), `label`, `kind`, `units`, and direction (`higher_is_better`). The TPP, Molecule Database, dashboard cards, and scatter axes ALL read the same catalog. Key schemes:

- `assay:{modality}:{target}` — pooled median over an assay modality (e.g. `assay:biochemical_ic50:TGTA`). Curated in `ASSAY_SPEC`; off-target ChEMBL IDs are never surfaced.
- `meas:{slug}` — **measurement-specific** axis reading one `standard_type` (optionally unit-filtered). Decomposed replacements for the old pooled kinetics/xenograft/tox/adme panels (which mixed incommensurable units and were meaningless as thresholds). Defined in `MEASUREMENT_SPEC`. Current set: kinact, mrt, tgi, cytotox, dili, t_half, bioavail, vdss, auc, cmax, ppb, stability, clearance (unit-filtered to in-vivo mL/min/kg), permeability (unit-filtered to cm/s).
- `cell:{cellline}` — anti-proliferation in a specific cell line (CellLine-2, MCF7, A549, …), from `assays.cell_line` (backfilled by regex from assay descriptions).
- `adme:{field}` — RDKit-computed physchem from SMILES (MW, cLogP=Crippen, TPSA=Ertl, QED, HBD/HBA/RotB/rings/Lipinski), stored in `molecules.adme_json`.
- `boltz:{field}` — Boltz-2.1 predicted (SAB confidence + binding + ADME), stored in `molecules.boltz_json`. Fields in `BOLTZ_META`.
- `formula:{slug}` — **derived/composite** metric: safe-AST arithmetic (`+ - * / **`, `log10/log/abs/sqrt`, None-propagating) over other metrics' aliases. E.g. TGTA/TGTB selectivity = `tgtb_ic50 / tgta_ic50`. Stored in `custom_metrics.formula`.
- `custom:*` — user-defined empty metric awaiting data.

`resolve(conn, program_id, molecule_id, key)` turns any key + molecule into a scalar (median for assays). `catalog()` assembles all groups + per-metric coverage counts. **Perf note:** formula resolution builds an alias map via `catalog()`; `_alias_map` is `lru_cache`-memoized (cleared in `define_custom`) — without it `/metrics` is O(n²) and times out.

### Why decomposition matters (design principle)
Pooling many `standard_type`s into one median produces a number that isn't a scientifically valid go/no-go threshold. The rule: **a TPP-thresholdable metric must resolve to one commensurable quantity.** Hence the `meas:` and `cell:` decompositions. When adding a panel, decompose it rather than pooling.

## TPP (`engine/tpp.py`, `tpp_builder.py`)

Executable spec: each `tpp_param` is a predicate (metric, operator, threshold) over a molecule. `score()` → pass/near/fail per axis; a molecule PASSES only with data on ALL axes (partial data ≠ pass). TPP is **versioned**: any edit/add/rebuild creates a new immutable `tpp_versions` row (one active per program) with a written justification. Conversational Opus builder authors a fresh TPP; it's demoted below a divider under the primary single-table view. Composite criteria are built structurally (pick property A, operator, property B) — not freetext.

## Structure / Boltz (`engine/structure.py`)

- Folding target is per-program (`fold_settings`): `target_kind` ∈ {pdb, uniprot, sequence} + `target_value`. Only a PDB target fetches a reference from RCSB; UniProt/sequence fold from sequence via Boltz. TGTA program's target is a verbatim 268-aa kinase-domain sequence.
- Boltz CLI = `boltz-api` (~/.local/bin). SAB = `predictions:structure-and-binding` ($0.05/complex); ADME = `predictions:adme` ($0.01/molecule). **Always run `estimate-cost` and report before submitting.** Payload: `entities:[{type,chain_ids,value}]` + `binding` block. Results: `metrics.json` (ptm/iptm/ligand_iptm/structure_confidence/complex_plddt + binding_confidence/optimization_score) + CIF.
- `get_cached_structure` returns `(text, is_placeholder, label, fmt)`. **3Dmol can't parse Boltz's minimal mmCIF (missing symmetry records)** → co-fold CIFs are converted to PDB via `gemmi` (`store_cofold_cif`) and served as PDB; `X-Structure-Format` header tells the viewer. Real co-folds live at `structure_path(mol_id)` and take priority over the reference placeholder.

## Frontend surfaces (all `program_id`-scoped, read from `/state` + specific endpoints)

Inbox (Monday-morning triaged items → approve → state mutates → Decision Log; includes re-derivation catch with dose-response overlay), TPP, Molecule Database (rename of tracker; click-to-filter histograms, any-property columns), Molecule Dashboard (config gear sets folding target + which metrics show on cards; flip cards 2D↔3D co-fold; favorite molecules; brush-select scatter with structure tooltips), Competitive Radar, CFO/Budget, Decision Log. Card fields and table columns are **metric keys** resolved via `/molecules/values`; the config only offers real catalog keys and stale keys are filtered so cards show exactly what's checked.

## De-identification (demo framing = "our proprietary molecules")

BTX-#### codes; `internal_ref`/`inchi_key` never returned by API; ChEMBL target IDs mapped to preferred names (`engine/target_names.py`); raw `CHEMBL\d+` tokens stripped from assay descriptions. Never surface ChEMBL anywhere.

## Candidate library extractions

- The metric-catalog engine (`metrics.py`) is the strongest reuse candidate — a general "data-driven property catalog + safe-formula resolver over a long-format assay table."
- The versioned-spec pattern (`tpp_versions`/`tpp_params`) generalizes to any human-signed, versioned decision spec.
