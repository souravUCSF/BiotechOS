"use client";

import { useProgram } from "@/lib/ProgramContext";

export function ProgramSwitcher() {
  const { programId, setProgramId, programs } = useProgram();

  return (
    <select
      value={programId}
      onChange={(e) => setProgramId(e.target.value)}
      className="rounded border border-borderStrong bg-panel px-3 py-1.5 text-sm text-ink"
    >
      {programs.length === 0 ? (
        <option value={programId}>{programId}</option>
      ) : (
        programs.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))
      )}
    </select>
  );
}
