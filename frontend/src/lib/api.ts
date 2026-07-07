import type { StateResponse, Program, Molecule } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8010";

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

export type Histogram = {
  metric: string;
  counts: number[];
  edges: number[];
  log_scale: boolean;
  threshold: number | null;
  operator: string | null;
  units: string | null;
};

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
