import type { StateResponse, Program } from "./types";

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
