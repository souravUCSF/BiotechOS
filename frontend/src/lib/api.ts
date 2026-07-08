import type { StateResponse, Program, Molecule, TppParam } from "./types";
export type { TppParam };

import { API_BASE } from "./apiBase";

export async function fetchState(programId: string): Promise<StateResponse> {
  const res = await fetch(`${API_BASE}/state?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /state failed: ${res.status}`);
  return res.json();
}

export async function fetchPrograms(): Promise<Program[]> {
  const res = await fetch(`${API_BASE}/programs`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /programs failed: ${res.status}`);
  return res.json();
}

export type ParamScore = {
  param_id: number;
  label: string;
  axis: string;
  metric: string;
  status: "pass" | "near" | "fail" | "no_data";
  value: number | null;
  threshold: number;
  operator: string;
  units: string | null;
};

export type MoleculeScore = {
  molecule_id: number;
  name: string;
  status: "pass" | "near" | "fail" | "no_data";
  params: ParamScore[];
};

export type TppScores = {
  molecules: MoleculeScore[];
  meets_tpp: string[];
};

export type HistogramMember = { molecule_id: number; name: string; value: number; bin: number };

export type Histogram = {
  metric: string;
  counts: number[];
  edges: number[];
  log_scale: boolean;
  threshold: number | null;
  operator: string | null;
  units: string | null;
  members?: HistogramMember[];
};

export type MetricDef = {
  key: string;
  label: string;
  kind: "assay" | "adme" | "custom";
  modality: string | null;
  target: string | null;
  units: string;
  log: boolean;
  higher_is_better: boolean;
  count?: number;
  description?: string;
};

export async function fetchMetrics(programId: string): Promise<MetricDef[]> {
  const res = await fetch(`${API_BASE}/metrics?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /metrics failed: ${res.status}`);
  return res.json();
}

export async function defineCustomMetric(
  body: {
    label: string;
    units?: string;
    log?: boolean;
    higher_is_better?: boolean;
    target?: string;
    description?: string;
  },
  programId: string,
): Promise<{ key: string; label: string }> {
  const res = await fetch(`${API_BASE}/metrics/custom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, program_id: programId }),
  });
  if (!res.ok) throw new Error(`define metric failed: ${res.status}`);
  return res.json();
}

export async function fetchTppScores(programId: string): Promise<TppScores> {
  const res = await fetch(`${API_BASE}/tpp/scores?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /tpp/scores failed: ${res.status}`);
  return res.json();
}

export async function fetchHistogram(metric: string, programId: string): Promise<Histogram> {
  const res = await fetch(
    `${API_BASE}/tpp/histogram?metric=${metric}&program_id=${programId}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`GET /tpp/histogram failed: ${res.status}`);
  return res.json();
}

export type RadarItem = {
  axis: string;
  title: string;
  org: string | null;
  stage: string | null;
  status?: string | null;
  event_date?: string | null;
  threat_score: number | null;
  source: string | null;
  url: string | null;
  detail?: string | null;
};

export type Radar = {
  generated_at: string;
  live: boolean;
  axes: {
    program: RadarItem[];
    catalyst: RadarItem[];
    financing: RadarItem[];
    news: RadarItem[];
  };
};

export async function fetchCompetitive(programId: string): Promise<Radar> {
  const res = await fetch(`${API_BASE}/competitive?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /competitive failed: ${res.status}`);
  return res.json();
}

export async function fetchMolecule(id: number): Promise<
  Molecule & { has_structure: boolean }
> {
  const res = await fetch(`${API_BASE}/molecule/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /molecule/${id} failed: ${res.status}`);
  return res.json();
}

export async function fetchDemoBrief(): Promise<string> {
  const res = await fetch(`${API_BASE}/tpp/demo-brief`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /tpp/demo-brief failed: ${res.status}`);
  return (await res.json()).brief;
}

export type Rederivation = {
  has_curve: boolean;
  flagged?: boolean;
  reported_ic50?: number;
  fitted_ic50?: number;
  fold_difference?: number;
  note?: string;
  fit?: { ic50: number; hill: number; top: number; bottom: number; r2: number };
  raw_points?: { concentration_nM: number[]; pct_inhibition: number[] };
};

export type BudgetSnapshot = {
  total: number;
  committed: number;
  actual: number;
  available: number;
  monthly_burn: number;
  runway_months: number | null;
};

export type FinancialResult = {
  po_number?: string;
  amount?: number;
  email?: string;
  email_used_llm?: boolean;
  matched?: boolean;
  note?: string;
  budget: BudgetSnapshot;
};

export type ApproveResult = {
  item_id: number;
  kind: string;
  loaded: number;
  crossed: string[];
  memo: { molecule: string; text: string; used_llm: boolean } | null;
  rederivation: Rederivation | null;
  financial?: FinancialResult;
};

export type BudgetResponse = {
  budget: BudgetSnapshot;
  purchase_orders: Array<{
    id: number;
    po_number: string;
    vendor_name: string;
    amount: number;
    status: string;
  }>;
  invoices: Array<{ id: number; amount: number; status: string; match_notes: string }>;
  quotes: Array<{ id: number; vendor_name: string; description: string; amount: number; status: string }>;
};

export async function fetchBudget(programId: string): Promise<BudgetResponse> {
  const res = await fetch(`${API_BASE}/budget?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /budget failed: ${res.status}`);
  return res.json();
}

export async function fetchRederivation(itemId: number, programId: string): Promise<Rederivation> {
  const res = await fetch(
    `${API_BASE}/inbox/${itemId}/rederivation?program_id=${programId}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`rederivation failed: ${res.status}`);
  return res.json();
}

export async function approveInbox(itemId: number, programId: string): Promise<ApproveResult> {
  const res = await fetch(`${API_BASE}/inbox/${itemId}/approve?program_id=${programId}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`approve failed: ${res.status}`);
  return res.json();
}

export async function resetDemo(programId: string): Promise<{ reset: boolean; inbox_items: number }> {
  const res = await fetch(`${API_BASE}/demo/reset?program_id=${programId}`, { method: "POST" });
  if (!res.ok) throw new Error(`reset failed: ${res.status}`);
  return res.json();
}

export async function buildTpp(
  brief: string,
  programId: string,
): Promise<{ used_llm: boolean; model: string; params: unknown[] }> {
  const res = await fetch(`${API_BASE}/tpp/build`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brief, program_id: programId }),
  });
  if (!res.ok) throw new Error(`POST /tpp/build failed: ${res.status}`);
  return res.json();
}

// --- TPP versioning + conversational builder ---

export type TppVersion = {
  id: number;
  program_id: string;
  version: number;
  notes: string | null;
  author: string;
  active: number;
  created_at: string;
};

export type CurrentTpp = {
  version: TppVersion | null;
  params: TppParam[];
};

export type ChatMessage = { role: "user" | "assistant"; content: string };

export async function fetchCurrentTpp(programId: string): Promise<CurrentTpp> {
  const res = await fetch(`${API_BASE}/tpp/current?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /tpp/current failed: ${res.status}`);
  return res.json();
}

export async function fetchTppVersions(programId: string): Promise<TppVersion[]> {
  const res = await fetch(`${API_BASE}/tpp/versions?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /tpp/versions failed: ${res.status}`);
  return res.json();
}

export async function updateTppParam(
  paramId: number,
  changes: Record<string, unknown>,
  justification: string,
  programId: string,
): Promise<{ new_version: number }> {
  const res = await fetch(`${API_BASE}/tpp/param/${paramId}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ changes, justification, program_id: programId }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `update failed: ${res.status}`);
  return res.json();
}

export async function addTppParam(
  spec: Record<string, unknown>,
  justification: string,
  programId: string,
): Promise<{ new_version: number }> {
  const res = await fetch(`${API_BASE}/tpp/param/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ spec, justification, program_id: programId }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `add failed: ${res.status}`);
  return res.json();
}

export async function tppBuilderGreeting(): Promise<string> {
  const res = await fetch(`${API_BASE}/tpp/builder/greeting`, { cache: "no-store" });
  return (await res.json()).greeting;
}

export async function tppBuilderChat(
  messages: ChatMessage[],
  programId: string,
  apiKey?: string,
): Promise<{ reply: string; used_llm: boolean }> {
  const res = await fetch(`${API_BASE}/tpp/builder/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, program_id: programId, api_key: apiKey || null }),
  });
  if (!res.ok) throw new Error(`chat failed: ${res.status}`);
  return res.json();
}

export async function tppBuilderFinalize(
  messages: ChatMessage[],
  programId: string,
  apiKey?: string,
): Promise<{ version: number; used_llm: boolean; params: TppParam[] }> {
  const res = await fetch(`${API_BASE}/tpp/builder/finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, program_id: programId, api_key: apiKey || null }),
  });
  if (!res.ok) throw new Error(`finalize failed: ${res.status}`);
  return res.json();
}
