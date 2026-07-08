"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { fetchMolecule } from "@/lib/api";
import { Structure3D } from "@/components/Structure3D";
import { AdmePanel } from "@/components/AdmePanel";
import type { Molecule } from "@/lib/types";

import { API_BASE } from "@/lib/apiBase";

export default function MoleculeDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const molId = Number(id);
  const [mol, setMol] = useState<(Molecule & { has_structure: boolean }) | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMolecule(molId).then(setMol).catch((e) => setError(String(e)));
  }, [molId]);

  if (error) return <p className="text-red-600">Error: {error}</p>;
  if (!mol) return <p className="text-inkMuted">Loading…</p>;

  // group assays by modality for the "all available data" view
  const byModality: Record<string, typeof mol.assays> = {};
  for (const a of mol.assays) (byModality[a.modality] ??= []).push(a);

  return (
    <div className="max-w-5xl">
      <Link href="/molecules" className="text-sm text-inkMuted hover:text-ink">
        ← Dashboard
      </Link>
      <h1 className="mb-4 mt-2 text-xl font-semibold">{mol.name}</h1>

      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <Structure3D moleculeId={mol.id} />
          <div className="mt-2 flex justify-center rounded border border-border bg-panel p-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`${API_BASE}/molecule/${mol.id}/structure2d`} alt="2D" className="h-40" />
          </div>
        </div>
        <div>
          <h2 className="mb-2 text-sm font-semibold text-ink">Predicted ADME</h2>
          <AdmePanel adme={mol.adme} />
          <div className="mt-4 rounded border border-border bg-panel p-3 text-xs text-inkMuted">
            <div className="mb-1 font-mono text-[11px] text-inkMuted">SMILES</div>
            <div className="break-all font-mono text-ink">{mol.smiles}</div>
          </div>
          <a
            href={`${API_BASE}/molecule/${mol.id}/data.csv`}
            className="mt-4 inline-block rounded border border-borderStrong px-3 py-1.5 text-sm text-ink hover:bg-panel2"
          >
            ↓ Download raw data (CSV)
          </a>
        </div>
      </div>

      <h2 className="mb-3 mt-8 text-sm font-semibold text-ink">
        All available data ({mol.assays.length} measurements across {Object.keys(byModality).length} modalities)
      </h2>
      <div className="space-y-4">
        {Object.entries(byModality).map(([modality, assays]) => (
          <div key={modality} className="rounded border border-border">
            <div className="border-b border-border bg-panel px-3 py-2 text-xs font-medium uppercase text-inkMuted">
              {modality} ({assays.length})
            </div>
            <div className="max-h-64 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-inkMuted">
                  <tr>
                    <th className="px-3 py-1">Target</th>
                    <th className="px-3 py-1">Type</th>
                    <th className="px-3 py-1">Value</th>
                    <th className="px-3 py-1">Units</th>
                    <th className="px-3 py-1">Assay</th>
                  </tr>
                </thead>
                <tbody>
                  {assays.slice(0, 40).map((a) => (
                    <tr key={a.id} className="border-t border-neutral-900">
                      <td className="px-3 py-1">{a.target ?? "—"}</td>
                      <td className="px-3 py-1">{a.standard_type ?? "—"}</td>
                      <td className="px-3 py-1 font-mono">{a.value ?? "—"}</td>
                      <td className="px-3 py-1">{a.units ?? "—"}</td>
                      <td className="px-3 py-1 text-inkMuted">
                        {a.assay_desc ? a.assay_desc.slice(0, 70) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
