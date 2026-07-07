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
    chembl_id           TEXT,
    name                TEXT,
    smiles              TEXT,
    inchi_key           TEXT,
    max_phase           REAL,
    held_out            INTEGER DEFAULT 0,   -- 1 = data withheld from initial seed (arrives via CRO doc)
    structure_cache_ref TEXT,                -- path to cached Boltz .cif/.pdb
    adme_json           TEXT,                -- predicted ADME blob (JSON)
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(program_id, chembl_id)
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
    assay_desc     TEXT,
    flags          TEXT,                 -- JSON list of QC flags
    created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_assays_molecule ON assays(molecule_id);
CREATE INDEX IF NOT EXISTS idx_assays_program ON assays(program_id);

CREATE TABLE IF NOT EXISTS tpp_params (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  TEXT NOT NULL REFERENCES programs(id),
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
