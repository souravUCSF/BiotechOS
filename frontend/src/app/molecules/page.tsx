"use client";

import { useAppState } from "@/lib/useAppState";
import type { Molecule } from "@/lib/types";

function modalityCounts(mol: Molecule) {
  const counts: Record<string, number> = {};
  for (const a of mol.assays) counts[a.modality] = (counts[a.modality] ?? 0) + 1;
  return counts;
}

export default function MoleculesPage() {
  const { state, error, loading } = useAppState();

  if (loading) return <p className="text-neutral-400">Loading…</p>;
  if (error) return <p className="text-red-400">Error: {error}</p>;
  if (!state) return null;

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">Molecule Tracking Dashboard</h1>
      <p className="mb-6 text-sm text-neutral-400">
        {state.molecules.length} active molecules · {state.program.target} vs.{" "}
        {state.program.anti_target}
      </p>

      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-900 text-neutral-400">
            <tr>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">ChEMBL ID</th>
              <th className="px-3 py-2">Phase</th>
              <th className="px-3 py-2">Assays</th>
              <th className="px-3 py-2">Modalities</th>
            </tr>
          </thead>
          <tbody>
            {state.molecules.map((mol) => {
              const counts = modalityCounts(mol);
              return (
                <tr key={mol.id} className="border-t border-neutral-800">
                  <td className="px-3 py-2 font-medium">{mol.name}</td>
                  <td className="px-3 py-2 text-neutral-400">{mol.chembl_id}</td>
                  <td className="px-3 py-2">{mol.max_phase}</td>
                  <td className="px-3 py-2">{mol.assays.length}</td>
                  <td className="px-3 py-2 text-xs text-neutral-400">
                    {Object.entries(counts)
                      .map(([k, v]) => `${k}:${v}`)
                      .join("  ")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-4 text-xs text-neutral-600">
        Boltz co-fold + 3D viewer, ADME cards, and compare-any-property view land in Day 3.
      </p>
    </div>
  );
}
