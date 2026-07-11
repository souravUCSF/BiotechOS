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
    cell_line      TEXT,                 -- normalized cell line for cellular assays (CellLine-2, CellLine-1, ...)
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
