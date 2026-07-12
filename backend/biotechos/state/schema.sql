-- BiotechOS state schema. Everything domain-level is partitioned by program_id
-- so multiple programs coexist and switching is a pure data operation.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS programs (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    target        TEXT,              -- e.g. TGTA/TGTA (CHEMBL1824)
    anti_target   TEXT,              -- e.g. TGTB (CHEMBL203)
    indication    TEXT,
    status        TEXT DEFAULT 'active',
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS molecules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id          TEXT NOT NULL REFERENCES programs(id),
    internal_ref        TEXT,                -- provenance only; never returned by the API
    name                TEXT,                -- proprietary compound code (e.g. BTX-1007); demo-facing
    smiles              TEXT,
    inchi_key           TEXT,                -- kept for internal dedup only, not API-exposed
    held_out            INTEGER DEFAULT 0,   -- 1 = data withheld from initial seed (arrives via CRO doc)
    favorite            INTEGER DEFAULT 0,   -- 1 = bookmarked/favorite (user-toggled)
    structure_cache_ref TEXT,                -- path to cached Boltz .cif/.pdb
    adme_json           TEXT,                -- predicted ADME blob (JSON)
    status              TEXT DEFAULT 'active',  -- active | candidate | dismissed | merged (registry lifecycle)
    merged_into         INTEGER,             -- if merged, the surviving molecules.id
    descriptor          TEXT,                -- freeform identity descriptor (when no SMILES/sequence)
    sequence            TEXT,                -- biologic sequence (peptide/protein), when applicable
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(program_id, internal_ref)
);
CREATE INDEX IF NOT EXISTS idx_molecules_program ON molecules(program_id);

CREATE TABLE IF NOT EXISTS assays (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id     TEXT NOT NULL REFERENCES programs(id),
    molecule_id    INTEGER NOT NULL REFERENCES molecules(id),
    modality       TEXT NOT NULL,        -- biochemical_ic50 | cellular_antiprolif | kinetics | adme | tox | xenograft | selectivity | nanobret | intact_ms | dsf
    target         TEXT,                 -- TGTA | TGTB | ... (for on/off-target)
    standard_type  TEXT,                 -- IC50 | Kd | Ki | GI50 | CL | TGI | kon | koff ...
    value          REAL,
    units          TEXT,
    reported_value REAL,                 -- as-reported (may differ from re-derived)
    raw_points     TEXT,                 -- JSON dose-response points for curve fits
    relation       TEXT,                 -- =, >, < ...
    pchembl        REAL,
    source         TEXT,                 -- chembl | cro_synthetic | ...
    cell_line      TEXT,                 -- DEPRECATED legacy column; superseded by system_type/system (kept read-only)
    -- Typed biological system (target-orthogonal): WHERE the measurement was made.
    system_type    TEXT,                 -- protein | cell_line | subcellular | matrix | organism | tissue
    system         TEXT,                 -- the system value (HEK293, plasma, TGTA, nude mouse, ...)
    species        TEXT,                 -- human | mouse | rat | ...
    conditions     TEXT,                 -- JSON exposure/dosing: {test_conc,incubation} | {dose,dose_units,route,regimen}
    source_document_id INTEGER,          -- provenance: the email/attachment this row came from
    assay_desc     TEXT,
    flags          TEXT,                 -- JSON list of QC flags
    created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_assays_molecule ON assays(molecule_id);
CREATE INDEX IF NOT EXISTS idx_assays_program ON assays(program_id);

-- A TPP is versioned: each edit or rebuild creates a new immutable version;
-- exactly one version per program is active (the live TPP).
CREATE TABLE IF NOT EXISTS tpp_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  TEXT NOT NULL REFERENCES programs(id),
    version     INTEGER NOT NULL,       -- 1, 2, 3 ...
    notes       TEXT,                   -- why this version exists (rationale / justification / build summary)
    author      TEXT DEFAULT 'founder',
    active      INTEGER DEFAULT 0,      -- 1 = current live TPP
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(program_id, version)
);
CREATE INDEX IF NOT EXISTS idx_tppver_program ON tpp_versions(program_id);

CREATE TABLE IF NOT EXISTS tpp_params (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  TEXT NOT NULL REFERENCES programs(id),
    version_id  INTEGER REFERENCES tpp_versions(id),  -- which TPP version this param belongs to
    axis        TEXT NOT NULL,          -- e.g. potency, selectivity, cellular, adme, tox
    label       TEXT NOT NULL,
    metric      TEXT NOT NULL,          -- which molecule field/modality this reads
    operator    TEXT NOT NULL,          -- '<' | '>' | '<=' | '>='
    threshold   REAL NOT NULL,
    near_frac   REAL DEFAULT 0.5,       -- within this fraction of threshold = "near"
    units       TEXT,
    weight      REAL DEFAULT 1.0,
    rationale   TEXT
);
CREATE INDEX IF NOT EXISTS idx_tpp_program ON tpp_params(program_id);
CREATE INDEX IF NOT EXISTS idx_tpp_version ON tpp_params(version_id);

-- User-defined molecule properties (metrics) — may have no data yet; data
-- arrives later via CRO assays matching (modality, target).
CREATE TABLE IF NOT EXISTS custom_metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  TEXT NOT NULL REFERENCES programs(id),
    key         TEXT NOT NULL,          -- e.g. assay:nanobret_ec50:TGTA
    label       TEXT NOT NULL,
    modality    TEXT,
    target      TEXT,
    units       TEXT,
    log         INTEGER DEFAULT 0,
    higher_is_better INTEGER DEFAULT 0,
    description TEXT,
    formula     TEXT,                  -- if set, a derived metric: arithmetic over other metric aliases
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(program_id, key)
);

-- Per-program folding configuration for Boltz co-folds: which protein / PDB to
-- fold against and any simple constraints. Drives the 3D reference structure too.
CREATE TABLE IF NOT EXISTS fold_settings (
    program_id  TEXT PRIMARY KEY REFERENCES programs(id),
    pdb_id      TEXT,
    constraints TEXT,
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id   TEXT NOT NULL REFERENCES programs(id),
    dept         TEXT,
    title        TEXT,
    status       TEXT,
    start_date   TEXT,
    end_date     TEXT,
    depends_on   TEXT,                  -- JSON list of task ids
    molecule_ids TEXT                   -- JSON list
);

CREATE TABLE IF NOT EXISTS inbox_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id      TEXT NOT NULL REFERENCES programs(id),
    kind            TEXT NOT NULL,      -- bio_cro_data | chem_update | vendor_quote
    title           TEXT,
    summary         TEXT,
    payload         TEXT,               -- JSON (the parsed content / dataset ref)
    proposed_action TEXT,               -- JSON describing what the OS proposes
    status          TEXT DEFAULT 'pending',  -- pending | approved | dismissed
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_inbox_program ON inbox_items(program_id);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  TEXT NOT NULL REFERENCES programs(id),
    kind        TEXT NOT NULL,          -- data_interpretation | go_no_go | po_approval | invoice_reconcile
    title       TEXT,
    content     TEXT,                   -- the signed artifact / rationale
    approved_by TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ledger_program ON ledger_entries(program_id);

CREATE TABLE IF NOT EXISTS competitive_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id   TEXT NOT NULL REFERENCES programs(id),
    axis         TEXT NOT NULL,         -- program | catalyst | financing | news
    title        TEXT,
    org          TEXT,
    stage        TEXT,
    event_date   TEXT,
    threat_score REAL,
    source       TEXT,
    url          TEXT,
    detail       TEXT
);

-- Financial / procurement loop --------------------------------------------
CREATE TABLE IF NOT EXISTS vendors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  TEXT NOT NULL REFERENCES programs(id),
    name        TEXT,
    email       TEXT,
    kind        TEXT                    -- CRO type
);

CREATE TABLE IF NOT EXISTS quotes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  TEXT NOT NULL REFERENCES programs(id),
    vendor_id   INTEGER REFERENCES vendors(id),
    description TEXT,
    line_items  TEXT,                   -- JSON
    amount      REAL,
    currency    TEXT DEFAULT 'USD',
    status      TEXT DEFAULT 'received',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  TEXT NOT NULL REFERENCES programs(id),
    quote_id    INTEGER REFERENCES quotes(id),
    vendor_id   INTEGER REFERENCES vendors(id),
    po_number   TEXT,
    amount      REAL,
    status      TEXT DEFAULT 'draft',   -- draft | issued | invoiced | closed
    email_draft_id TEXT,                -- Gmail draft id
    line_items  TEXT,                   -- JSON: [{description,quantity,amount}] on the PO doc
    vendor_name TEXT,                   -- editable vendor name on the PO doc
    approved_at TEXT,                   -- when the PO was issued
    source_document_id INTEGER,         -- source quote/email this PO derives from
    notes       TEXT,                   -- freeform notes on the PO
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS commitments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  TEXT NOT NULL REFERENCES programs(id),
    po_id       INTEGER REFERENCES purchase_orders(id),
    amount      REAL,
    status      TEXT DEFAULT 'committed'  -- committed | released
);

CREATE TABLE IF NOT EXISTS invoices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id   TEXT NOT NULL REFERENCES programs(id),
    po_id        INTEGER REFERENCES purchase_orders(id),
    amount       REAL,
    status       TEXT DEFAULT 'received',  -- received | matched | mismatch | paid
    match_notes  TEXT,
    source_document_id INTEGER,             -- source invoice email/attachment
    vendor_name  TEXT,
    invoice_number TEXT,
    paid_at      TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS budget (
    program_id  TEXT PRIMARY KEY REFERENCES programs(id),
    total       REAL DEFAULT 0,
    committed   REAL DEFAULT 0,
    actual      REAL DEFAULT 0,
    monthly_burn REAL DEFAULT 0
);

-- ===================================================================
-- Corpus / knowledge / identity layer (Inbox v2 — document-driven)
-- ===================================================================

-- Molecule identity: one canonical molecules.id, many names/aliases.
CREATE TABLE IF NOT EXISTS molecule_aliases (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id         TEXT NOT NULL REFERENCES programs(id),
    molecule_id        INTEGER NOT NULL REFERENCES molecules(id),
    alias              TEXT NOT NULL,          -- as written, e.g. "PH-PGMA-L2-2026-08B-7-0"
    alias_norm         TEXT NOT NULL,          -- normalized key, e.g. "CLO|3"
    alias_type         TEXT,                   -- internal | request_id | cro_project_code | vendor_code | common_name
    vendor             TEXT,
    source_document_id INTEGER,                -- REFERENCES documents(id)
    confidence         REAL DEFAULT 1.0,
    verified           INTEGER DEFAULT 0,
    created_at         TEXT DEFAULT (datetime('now')),
    UNIQUE(program_id, alias_norm, molecule_id)
);
CREATE INDEX IF NOT EXISTS idx_molalias_norm ON molecule_aliases(program_id, alias_norm);
CREATE INDEX IF NOT EXISTS idx_molalias_mol ON molecule_aliases(molecule_id);

-- Every ingested email + attachment (the corpus).
CREATE TABLE IF NOT EXISTS documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id     TEXT NOT NULL REFERENCES programs(id),
    source_ref     TEXT,                       -- mailbox slug / path
    org            TEXT,
    direction      TEXT,                       -- inbound | outbound
    email_from     TEXT,
    email_to       TEXT,
    subject        TEXT,
    sent_at        TEXT,
    doc_type       TEXT,                        -- quote|invoice|cro_data|project_update|query|vendor_capability|contract|logistics|other|noise|fyi
    triage         TEXT,                        -- actionable|fyi|noise
    raw_text       TEXT,                        -- email body + attachment text (anonymized if synthetic)
    extraction_json TEXT,                       -- typed extraction result
    created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_program ON documents(program_id);

-- Immutable log of every extracted claim.
CREATE TABLE IF NOT EXISTS observations (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id         TEXT NOT NULL REFERENCES programs(id),
    subject_type       TEXT NOT NULL,           -- vendor|molecule|material|contract|assay|budget
    subject_key        TEXT NOT NULL,
    predicate          TEXT NOT NULL,
    value              TEXT,
    source_document_id INTEGER REFERENCES documents(id),
    decision_state     TEXT DEFAULT 'proposed', -- proposed|under_consideration|agreed|superseded
    confidence         REAL DEFAULT 0.7,
    recorded_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_obs_subject ON observations(program_id, subject_type, subject_key, predicate);

-- Derived world model: current believed value per (subject, predicate). Bitemporal.
CREATE TABLE IF NOT EXISTS facts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id     TEXT NOT NULL REFERENCES programs(id),
    subject_type   TEXT NOT NULL,
    subject_key    TEXT NOT NULL,
    predicate      TEXT NOT NULL,
    value          TEXT,
    observation_id INTEGER REFERENCES observations(id),
    valid_from     TEXT DEFAULT (datetime('now')),
    valid_to       TEXT,                         -- NULL = current
    status         TEXT DEFAULT 'current'        -- current | superseded
);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(program_id, subject_type, subject_key, predicate, status);

-- Discovered attachment passwords, keyed by vendor domain. LOCAL ONLY.
CREATE TABLE IF NOT EXISTS vendor_credentials (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id         TEXT NOT NULL REFERENCES programs(id),
    domain             TEXT NOT NULL,
    password           TEXT NOT NULL,
    source_document_id INTEGER,
    confidence         REAL DEFAULT 0.8,
    created_at         TEXT DEFAULT (datetime('now'))
);

-- Full-text search over documents (keyword/BM25 retrieval for Q&A fallback).
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    subject, raw_text, content='documents', content_rowid='id'
);

-- ===================================================================
-- Entity graph (knowledge layer): entities + typed edges + aliases.
-- ===================================================================
CREATE TABLE IF NOT EXISTS entities (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id    TEXT NOT NULL REFERENCES programs(id),
    entity_type   TEXT NOT NULL,   -- vendor|person|program|contract|molecule|assay|cell_line|material|budget
    canonical_key TEXT NOT NULL,   -- normalized identity key (dedup key)
    display_name  TEXT NOT NULL,   -- as first seen / preferred label
    attrs_json    TEXT,            -- JSON blob of typed attributes (domain, email, ...)
    created_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(program_id, entity_type, canonical_key)
);
CREATE INDEX IF NOT EXISTS idx_entities_lookup ON entities(program_id, entity_type, canonical_key);

CREATE TABLE IF NOT EXISTS edges (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id     TEXT NOT NULL REFERENCES programs(id),
    src_entity_id  INTEGER NOT NULL REFERENCES entities(id),
    predicate      TEXT NOT NULL,   -- works_at|quoted|tests|offers_service|supplied|...
    dst_entity_id  INTEGER NOT NULL REFERENCES entities(id),
    observation_id INTEGER REFERENCES observations(id),
    source_document_id INTEGER REFERENCES documents(id),
    confidence     REAL DEFAULT 0.8,
    props_json     TEXT,            -- Phase-2 hook: commitment force/hedge/honored
    valid_from     TEXT DEFAULT (datetime('now')),
    valid_to       TEXT,            -- NULL = current
    status         TEXT DEFAULT 'current'   -- current | superseded
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(program_id, src_entity_id, predicate, status);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(program_id, dst_entity_id, predicate, status);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id         TEXT NOT NULL REFERENCES programs(id),
    entity_id          INTEGER NOT NULL REFERENCES entities(id),
    alias              TEXT NOT NULL,     -- as written
    alias_norm         TEXT NOT NULL,     -- normalized key
    source_document_id INTEGER,
    confidence         REAL DEFAULT 1.0,
    created_at         TEXT DEFAULT (datetime('now')),
    UNIQUE(program_id, entity_id, alias_norm)
);
CREATE INDEX IF NOT EXISTS idx_entalias_norm ON entity_aliases(program_id, alias_norm);

-- Suspected/confirmed decisions surfaced from observations (decisions queue).
CREATE TABLE IF NOT EXISTS decisions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id         TEXT NOT NULL REFERENCES programs(id),
    kind               TEXT,   -- price_agreement|vendor_selection|scope_change|timeline_commitment|go_no_go|contract_term|other
    subject_type       TEXT NOT NULL,
    subject_key        TEXT NOT NULL,
    predicate          TEXT NOT NULL,
    value              TEXT,
    source_document_id INTEGER REFERENCES documents(id),
    observation_id     INTEGER REFERENCES observations(id),
    status             TEXT DEFAULT 'suspected',  -- suspected|confirmed|dismissed|superseded
    confidence         REAL DEFAULT 0.6,
    rationale          TEXT,                       -- why suspected (snippet / heuristic note)
    decided_by         TEXT,
    decided_at         TEXT,
    ledger_entry_id    INTEGER REFERENCES ledger_entries(id),
    created_at         TEXT DEFAULT (datetime('now'))  -- event time (source sent_at)
);
CREATE INDEX IF NOT EXISTS idx_decisions_queue ON decisions(program_id, status, confidence);

-- Human review notes flagged on emails / decisions (for "check my flagged notes").
CREATE TABLE IF NOT EXISTS email_notes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id   TEXT NOT NULL REFERENCES programs(id),
    document_id  INTEGER,
    decision_id  INTEGER,
    source_ref   TEXT,
    note         TEXT NOT NULL,
    flagged      INTEGER DEFAULT 1,
    resolved     INTEGER DEFAULT 0,
    author       TEXT DEFAULT 'founder',
    created_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_email_notes_program ON email_notes(program_id, flagged, resolved);

-- Structured quote line items parsed from quote documents.
CREATE TABLE IF NOT EXISTS quote_lines (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id          TEXT NOT NULL REFERENCES programs(id),
    document_id         INTEGER,
    observation_id      INTEGER,
    decision_id         INTEGER,
    vendor              TEXT,
    scope               TEXT,            -- full line description (what the price is for)
    compound            TEXT,            -- compound/sample code if detected
    quantity            REAL,            -- numeric quantity (e.g. 10)
    unit                TEXT,            -- mg | g | mL | …
    amount              REAL NOT NULL,   -- price
    currency            TEXT DEFAULT 'USD',
    turnaround_raw      TEXT,            -- e.g. "2-3 weeks"
    turnaround_days_min INTEGER,
    turnaround_days_max INTEGER,
    status              TEXT DEFAULT 'suspected',  -- suspected | confirmed | dismissed
    sent_at             TEXT,            -- event time (email date) for as-of filtering
    method              TEXT DEFAULT 'regex',
    source_span         TEXT,
    flagged             INTEGER DEFAULT 0,
    flag_reasons        TEXT,
    service             TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_quote_lines_program ON quote_lines(program_id, vendor, amount);

-- Data QC analyses + legal reviews (inbox processors persist their runs here).
CREATE TABLE IF NOT EXISTS data_analyses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id    TEXT NOT NULL REFERENCES programs(id),
    document_id   INTEGER,
    status        TEXT DEFAULT 'pending',   -- pending | approved | dismissed
    verdict       TEXT,                     -- pass | warn | fail
    summary       TEXT,
    analysis_json TEXT,                      -- {vendor_summary, measurements, qc_steps, charts, deposition}
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_data_analyses ON data_analyses(program_id, document_id, status);

CREATE TABLE IF NOT EXISTS legal_reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id    TEXT NOT NULL REFERENCES programs(id),
    document_id   INTEGER,
    status        TEXT DEFAULT 'pending',
    summary       TEXT,
    review_json   TEXT,                      -- {agreement_type, parties, term, summary, issues[]}
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_legal_reviews ON legal_reviews(program_id, document_id, status);

-- Company cash + payment ledger (CFO loop).
CREATE TABLE IF NOT EXISTS company_cash (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    opening_balance REAL DEFAULT 500000,
    balance         REAL DEFAULT 500000,   -- cash actually paid out is deducted here
    currency        TEXT DEFAULT 'USD',
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cash_transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,          -- opening | po_payment
    amount        REAL NOT NULL,          -- signed: +deposit, −payment
    balance_after REAL,
    program_id    TEXT,
    po_id         INTEGER,
    invoice_id    INTEGER,
    description   TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

-- User-defined molecule groups (cohorts) for modeling on multiple molecules.
CREATE TABLE IF NOT EXISTS molecule_groups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id   TEXT NOT NULL REFERENCES programs(id),
    name         TEXT NOT NULL,
    molecule_ids TEXT,                    -- JSON list of molecules.id
    created_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_molecule_groups_program ON molecule_groups(program_id);
