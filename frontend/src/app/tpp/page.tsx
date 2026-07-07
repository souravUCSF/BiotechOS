"use client";

import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { fetchTppScores, type TppScores, type MoleculeScore } from "@/lib/api";
import { ParamHistogram } from "@/components/ParamHistogram";

const STATUS_STYLE: Record<string, string> = {
  pass: "bg-emerald-600/90 text-white",
  near: "bg-amber-500/90 text-black",
  fail: "bg-neutral-800 text-neutral-500",
  no_data: "bg-neutral-900 text-neutral-700",
};

const fmt = (v: number | null, units: string | null) =>
  v == null ? "—" : `${v >= 1000 ? (v / 1000).toFixed(1) + "k" : v.toFixed(1)}${units ?? ""}`;

export default function TppTrackerPage() {
  const { programId } = useProgram();
  const [scores, setScores] = useState<TppScores | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTppScores(programId).then(setScores).catch((e) => setError(String(e)));
  }, [programId]);

  if (error) return <p className="text-red-400">Error: {error}</p>;
  if (!scores) return <p className="text-neutral-400">Loading…</p>;

  // parameter columns come from the first molecule's param list
  const params = scores.molecules[0]?.params ?? [];
  const sorted = [...scores.molecules].sort((a, b) => {
    const order = { pass: 0, near: 1, fail: 2, no_data: 3 } as Record<string, number>;
    return order[a.status] - order[b.status];
  });

  return (
    <div>
      <div className="mb-4 flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">TPP Tracker</h1>
        <div className="text-sm text-neutral-400">
          <span className="font-medium text-emerald-400">{scores.meets_tpp.length}</span>{" "}
          molecule{scores.meets_tpp.length === 1 ? "" : "s"} meet the TPP:{" "}
          <span className="text-emerald-300">{scores.meets_tpp.join(", ") || "none"}</span>
        </div>
      </div>

      {/* per-parameter population histograms vs. threshold */}
      <div className="mb-6 grid gap-4" style={{ gridTemplateColumns: `repeat(${params.length}, minmax(0, 1fr))` }}>
        {params.map((p) => (
          <div key={p.param_id} className="rounded border border-neutral-800 bg-neutral-900 p-3">
            <div className="mb-2 text-xs font-medium text-neutral-300">{p.label}</div>
            <ParamHistogram metric={p.metric} />
          </div>
        ))}
      </div>

      {/* molecule × parameter grid */}
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-900 text-neutral-400">
            <tr>
              <th className="px-3 py-2">Compound</th>
              <th className="px-3 py-2">Overall</th>
              {params.map((p) => (
                <th key={p.param_id} className="px-3 py-2">
                  {p.label}
                  <span className="ml-1 text-[10px] text-neutral-600">
                    {p.operator} {fmt(p.threshold, p.units)}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((mol: MoleculeScore) => (
              <tr key={mol.molecule_id} className="border-t border-neutral-800">
                <td className="px-3 py-2 font-medium">{mol.name}</td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[mol.status]}`}>
                    {mol.status === "pass" ? "MEETS TPP" : mol.status.toUpperCase()}
                  </span>
                </td>
                {mol.params.map((p) => (
                  <td key={p.param_id} className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[p.status]}`}>
                      {fmt(p.value, p.units)}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
