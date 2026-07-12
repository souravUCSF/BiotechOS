export type Assay = {
  id: number;
  program_id: string;
  molecule_id: number;
  modality: string;
  target: string | null;
  standard_type: string | null;
  value: number | null;
  units: string | null;
  reported_value: number | null;
  raw_points: string | null;
  relation: string | null;
  pchembl: number | null;
  source: string | null;
  assay_desc: string | null;
  flags: string | null;
  source_document_id: number | null;
};

export type Molecule = {
  id: number;
  program_id: string;
  name: string; // proprietary compound code, e.g. BTX-1007
  smiles: string;
  held_out: number;
  favorite?: number;
  structure_cache_ref: string | null;
  adme_json: string | null;
  adme?: Record<string, number> | null;
  assays: Assay[];
};

export type TppParam = {
  id: number;
  program_id: string;
  axis: string;
  label: string;
  metric: string;
  operator: string;
  threshold: number;
  near_frac: number;
  units: string | null;
  weight: number;
  rationale: string | null;
};

export type InboxItem = {
  id: number;
  program_id: string;
  kind: string;
  title: string;
  summary: string | null;
  payload: string | null;
  proposed_action: string | null;
  status: string;
  created_at: string;
};

export type LedgerEntry = {
  id: number;
  program_id: string;
  kind: string;
  title: string;
  content: string | null;
  approved_by: string | null;
  created_at: string;
};

export type CompetitiveItem = {
  id: number;
  program_id: string;
  axis: string;
  title: string;
  org: string | null;
  stage: string | null;
  event_date: string | null;
  threat_score: number | null;
  source: string | null;
  url: string | null;
  detail: string | null;
};

export type Budget = {
  program_id: string;
  total: number;
  committed: number;
  actual: number;
  monthly_burn: number;
};

export type Program = {
  id: string;
  name: string;
  target: string;
  anti_target: string;
  indication: string;
  status: string;
};

export type StateResponse = {
  program: Program;
  molecules: Molecule[];
  tpp_params: TppParam[];
  inbox_items: InboxItem[];
  ledger_entries: LedgerEntry[];
  competitive_items: CompetitiveItem[];
  budget: Budget | null;
};
