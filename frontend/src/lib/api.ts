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
  alias?: string;
  label: string;
  kind: "assay" | "adme" | "custom" | "formula";
  modality: string | null;
  target: string | null;
  units: string;
  log: boolean;
  higher_is_better: boolean;
  count?: number;
  description?: string;
  formula?: string | null;
};

export async function fetchMetrics(programId: string): Promise<MetricDef[]> {
  const res = await fetch(`${API_BASE}/metrics?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /metrics failed: ${res.status}`);
  return res.json();
}

export type MoleculeValues = { molecule_id: number; name: string; values: Record<string, number | null> };

export async function fetchMoleculeValues(keys: string[], programId: string): Promise<MoleculeValues[]> {
  if (keys.length === 0) return [];
  const res = await fetch(
    `${API_BASE}/molecules/values?metrics=${encodeURIComponent(keys.join(","))}&program_id=${programId}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`GET /molecules/values failed: ${res.status}`);
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
    formula?: string;
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

export type FoldTargetKind = "pdb" | "uniprot" | "sequence";
export type FoldConfig = {
  program_id: string;
  target_kind: FoldTargetKind;
  target_value: string;
  pdb_id: string;
  constraints: string;
};

export async function fetchFoldConfig(programId: string): Promise<FoldConfig> {
  const res = await fetch(`${API_BASE}/fold-config?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /fold-config failed: ${res.status}`);
  return res.json();
}

export async function setFoldConfig(
  targetKind: FoldTargetKind,
  targetValue: string,
  constraints: string,
  programId: string,
): Promise<FoldConfig> {
  const res = await fetch(`${API_BASE}/fold-config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_kind: targetKind, target_value: targetValue,
      constraints, program_id: programId,
    }),
  });
  if (!res.ok) throw new Error(`POST /fold-config failed: ${res.status}`);
  return res.json();
}

export async function fetchMolecule(id: number): Promise<
  Molecule & { has_structure: boolean }
> {
  const res = await fetch(`${API_BASE}/molecule/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /molecule/${id} failed: ${res.status}`);
  return res.json();
}

export async function setFavorite(id: number, favorite: boolean): Promise<{ favorite: boolean }> {
  const res = await fetch(`${API_BASE}/molecule/${id}/favorite`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ favorite }),
  });
  if (!res.ok) throw new Error(`favorite toggle failed: ${res.status}`);
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

// --- Purchase-order document editor (/po/{id}) ---

export type POLineItem = {
  description: string;
  amount: number;
  quantity?: number | null;
};

export type PurchaseOrder = {
  id: number;
  program_id: string;
  vendor_name: string | null;
  status: string;              // draft | issued | invoiced | closed
  po_number: string | null;
  approved_at: string | null;
  line_items: POLineItem[];
};

export async function fetchPO(poId: number, programId?: string): Promise<PurchaseOrder> {
  const qs = programId ? `?program_id=${programId}` : "";
  const res = await fetch(`${API_BASE}/po/${poId}${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /po/${poId} failed: ${res.status}`);
  return res.json();
}

export async function updatePO(
  poId: number,
  lineItems: POLineItem[],
  vendorName: string,
  programId?: string,
): Promise<PurchaseOrder> {
  const res = await fetch(`${API_BASE}/po/${poId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      line_items: lineItems,
      vendor_name: vendorName,
      ...(programId ? { program_id: programId } : {}),
    }),
  });
  if (!res.ok) throw new Error(`POST /po/${poId} failed: ${res.status}`);
  return res.json();
}

export async function approvePO(
  poId: number,
  programId?: string,
): Promise<{ email: string; po_number: string; status: string }> {
  const qs = programId ? `?program_id=${programId}` : "";
  const res = await fetch(`${API_BASE}/po/${poId}/approve${qs}`, { method: "POST" });
  if (!res.ok) throw new Error(`approve PO failed: ${res.status}`);
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

export async function fetchTppVersion(version: number, programId: string): Promise<CurrentTpp> {
  const res = await fetch(`${API_BASE}/tpp/version/${version}?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /tpp/version failed: ${res.status}`);
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

// --- QueryOS / corpus knowledge ---
export type KnowledgeCitation = {
  n?: number; id?: number; subject?: string; email_from?: string; email_to?: string;
  sent_at?: string; doc_type?: string; snippet?: string | null; body?: string;
};
export type KnowledgeAnswer = {
  answer: string; used_llm: boolean; source: "facts" | "documents" | "none";
  fact_count: number; citations: KnowledgeCitation[];
};

export async function askKnowledge(question: string, programId: string): Promise<KnowledgeAnswer> {
  const res = await fetch(`${API_BASE}/knowledge/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, program_id: programId }),
  });
  if (!res.ok) throw new Error(`ask failed: ${res.status}`);
  return res.json();
}

export type CorpusSummary = { documents: number; facts: number; by_type: Record<string, number> };
export async function fetchCorpusSummary(programId: string): Promise<CorpusSummary> {
  const res = await fetch(`${API_BASE}/corpus/summary?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`corpus summary failed: ${res.status}`);
  return res.json();
}

// --- Current Inbox (Inbox v2, Phase 2) ---
export type InboxAttachment = { filename: string; protected: boolean; mimetype: string };
export type InboxEnvelope = {
  email_from: string | null;
  email_to: string | null;
  subject: string;
  date: string | null;
  direction: string | null;
  body_preview: string | null;
  attachments: InboxAttachment[];
};
export type InboxContext = {
  molecules?: { molecule_id: number; name: string; tpp_status: string }[];
  budget?: BudgetSnapshot;
  prior_quotes?: { amounts: string[]; documents: { id: number; subject: string; sent_at: string }[] };
  ledger?: { id: number; kind: string; title: string; created_at: string }[];
};
export type InboxV2Item = {
  id: number;
  kind: string;
  doc_type: string | null;
  title: string;
  summary: string | null;
  status: string;
  document_id: number | null;
  envelope: InboxEnvelope;
  extraction: Record<string, unknown>;
  analysis: { recommendation?: string; note?: string; decision_state?: string };
  proposed_action: { action?: string; label?: string; note?: string };
  context: InboxContext;
};

export type InboxApproveResult = ApproveResult & {
  promoted_facts?: number;
  molecules?: { name: string; created: boolean }[];
  reply_draft?: string;
  grounding?: { source: string; citations: KnowledgeCitation[] };
};

export async function fetchInbox(programId: string): Promise<InboxV2Item[]> {
  const res = await fetch(`${API_BASE}/inbox?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /inbox failed: ${res.status}`);
  return (await res.json()).items;
}

export async function approveInboxV2(itemId: number, programId: string): Promise<InboxApproveResult> {
  const res = await fetch(`${API_BASE}/inbox/${itemId}/approve?program_id=${programId}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`approve failed: ${res.status}`);
  return res.json();
}

export async function declineInbox(itemId: number, programId: string): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/inbox/${itemId}/decline?program_id=${programId}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`decline failed: ${res.status}`);
  return res.json();
}

// --- Mailbox (triaged inbox) ---
export type TriageCategory = "ignore" | "knowledge" | "processing" | "action";
export type MailItem = {
  id: number; from: string; subject: string; sent_at: string; doc_type: string;
  seen: boolean; category: TriageCategory; next_step: string; reason: string;
  needs_reply: boolean; confidence: number; preview: string;
};
export type Mailbox = { counts: Record<TriageCategory, number>; emails: MailItem[] };
export type MailEmail = {
  id: number; from: string; to: string; subject: string; sent_at: string;
  doc_type: string; body: string; triage: Partial<MailItem>;
};

export async function fetchMailbox(
  programId: string, category?: string, includeIgnored = false,
): Promise<Mailbox> {
  const p = new URLSearchParams({ program_id: programId, include_ignored: String(includeIgnored) });
  if (category) p.set("category", category);
  const res = await fetch(`${API_BASE}/mailbox?${p}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /mailbox failed: ${res.status}`);
  return res.json();
}

export async function fetchMailEmail(id: number): Promise<MailEmail> {
  const res = await fetch(`${API_BASE}/mailbox/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /mailbox/${id} failed: ${res.status}`);
  return res.json();
}

// ---- Data QC (data-email analysis → QC → deposit) ----
export type QCStep = { step: string; detail: string; status: "ok" | "warn" | "fail" };
export type DataChart = {
  kind: "dose_response" | "panel";
  compound?: string; target?: string; units?: string;
  points?: number[][];
  fit?: { ic50: number; hill: number; top: number; bottom: number; r2: number } | null;
  reported_ic50?: number | null; rederived_ic50?: number | null;
  fold?: number | null; flagged?: boolean;
  items?: { property: string; value: number; units: string; band: string; flagged: boolean }[];
};
export type DepositionRow = {
  molecule: string; standard_type: string; target?: string;
  value: number | string; units?: string; flags?: string[]; relation?: string;
};
export type DataAnalysisBody = {
  vendor_summary?: string;
  counts?: { datasets?: number; discrepancies?: number; warnings?: number };
  qc_steps: QCStep[];
  charts: DataChart[];
  deposition: DepositionRow[];
  read_source?: string;
};
export type DataAttachment = { filename: string; native_available: boolean };
export type DataAnalysis = {
  found?: boolean;
  id?: number;
  status: string;                       // pending | approved | dismissed
  verdict?: "pass" | "warn" | "fail";
  analysis?: DataAnalysisBody | null;
  attachments?: DataAttachment[];
};

export async function fetchDataAnalysis(docId: number, programId: string): Promise<DataAnalysis | null> {
  const res = await fetch(`${API_BASE}/data/analysis/${docId}?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) return null;
  const d = await res.json();
  return d && d.found === false ? { ...d, status: d.status ?? "pending" } : d;
}
export async function runDataAnalysis(
  docId: number, programId: string, source: "text" | "native" = "text", files?: string[],
): Promise<DataAnalysis> {
  const res = await fetch(`${API_BASE}/data/analysis/${docId}/run?program_id=${programId}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, files: files ?? null }),
  });
  if (!res.ok) throw new Error(`POST /data/analysis/${docId}/run failed: ${res.status}`);
  return res.json();
}
export async function approveDataAnalysis(analysisId: number, programId: string) {
  const res = await fetch(`${API_BASE}/data/${analysisId}/approve?program_id=${programId}`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /data/${analysisId}/approve failed: ${res.status}`);
  return res.json();
}
export async function dismissDataAnalysis(analysisId: number, programId: string) {
  const res = await fetch(`${API_BASE}/data/${analysisId}/dismiss?program_id=${programId}`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /data/${analysisId}/dismiss failed: ${res.status}`);
  return res.json();
}

// ---- Legal review (contract → house-standards review → execute/store) ----
export type LegalIssue = {
  severity: "high" | "medium" | "low";
  title: string; clause?: string | null; issue: string; recommendation?: string;
};
export type LegalReviewBody = {
  agreement_type: string; parties: string[]; term?: string | null;
  execution_status: "draft" | "in_revision" | "executed";
  summary: string; issues: LegalIssue[];
  counts: { high: number; medium: number; low: number };
  read_source?: string;
};
export type LegalReview = {
  found?: boolean;
  review: LegalReviewBody | null;
  document_text: string;
  attachments: DataAttachment[];
};

export async function fetchLegalReview(docId: number, programId: string): Promise<LegalReview | null> {
  const res = await fetch(`${API_BASE}/legal/review/${docId}?program_id=${programId}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}
export async function runLegalReview(
  docId: number, programId: string, source: "text" | "native" = "text", files?: string[],
): Promise<LegalReview> {
  const res = await fetch(`${API_BASE}/legal/review/${docId}/run?program_id=${programId}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, files: files ?? null }),
  });
  if (!res.ok) throw new Error(`POST /legal/review/${docId}/run failed: ${res.status}`);
  return res.json();
}
export function legalDocDownloadUrl(docId: number, programId: string): string {
  return `${API_BASE}/legal/document/${docId}/download?program_id=${programId}`;
}
