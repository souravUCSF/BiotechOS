"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useProgram } from "@/lib/ProgramContext";
import { useAppState } from "@/lib/useAppState";
import { fetchTppScores, type TppScores } from "@/lib/api";
import { Structure3D } from "@/components/Structure3D";
import { AdmePanel } from "@/components/AdmePanel";
import { PropertyScatter } from "@/components/PropertyScatter";
import { moleculeProperties } from "@/lib/properties";
import type { Molecule } from "@/lib/types";

import { API_BASE } from "@/lib/apiBase";
const fmt = (v: number | null) =>
  v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(1);

const STATUS_RANK = { pass: 0, near: 1, fail: 2, no_data: 3 } as Record<string, number>;

function AdvancingCard({ mol, status }: { mol: Molecule; status: string }) {
  const p = moleculeProperties(mol);
  return (
    <div className="rounded border border-neutral-800 bg-neutral-900 p-4">
      <div className="mb-2 flex items-center justify-between">
        <Link href={`/molecules/${mol.id}`} className="font-medium hover:text-emerald-400">
          {mol.name}
        </Link>
        <span
          className={`rounded px-2 py-0.5 text-xs ${
            status === "pass"
              ? "bg-emerald-600 text-white"
              : status === "near"
                ? "bg-amber-500 text-black"
                : "bg-neutral-800 text-neutral-400"
          }`}
        >
          {status === "pass" ? "MEETS TPP" : status.toUpperCase()}
        </span>
      </div>
      <Structure3D moleculeId={mol.id} />
      <div className="mt-2 flex justify-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`${API_BASE}/molecule/${mol.id}/structure2d`}
          alt={`${mol.name} 2D`}
          className="h-24"
        />
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-neutral-300">
        <div>TGTA IC50: <span className="font-mono">{fmt(p.tgta_ic50)}nM</span></div>
        <div>Selectivity: <span className="font-mono">{fmt(p.selectivity)}x</span></div>
        <div>Cellular: <span className="font-mono">{fmt(p.cell_ic50)}nM</span></div>
        <div>QED: <span className="font-mono">{p.QED ?? "—"}</span></div>
      </div>
      <div className="mt-3">
        <AdmePanel adme={mol.adme} />
      </div>
    </div>
  );
}

export default function MoleculesPage() {
  const { programId } = useProgram();
  const router = useRouter();
  const { state } = useAppState();
  const [scores, setScores] = useState<TppScores | null>(null);

  useEffect(() => {
    fetchTppScores(programId).then(setScores).catch(() => setScores(null));
  }, [programId]);

  if (!state) return <p className="text-neutral-400">Loading…</p>;

  const statusById = new Map(
    (scores?.molecules ?? []).map((m) => [m.molecule_id, m.status]),
  );
  const advancing = [...state.molecules]
    .sort(
      (a, b) =>
        (STATUS_RANK[statusById.get(a.id) ?? "no_data"] ?? 3) -
        (STATUS_RANK[statusById.get(b.id) ?? "no_data"] ?? 3),
    )
    .slice(0, 3);
  const meets = new Set(
    (scores?.molecules ?? [])
      .filter((m) => m.status === "pass")
      .map((m) => m.molecule_id),
  );

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">Molecule Tracking Dashboard</h1>
      <p className="mb-6 text-sm text-neutral-400">
        {state.molecules.length} active molecules · {state.program.target} vs.{" "}
        {state.program.anti_target}
      </p>

      <h2 className="mb-3 text-sm font-semibold text-neutral-300">Advancing molecules</h2>
      <div className="mb-8 grid gap-4 md:grid-cols-3">
        {advancing.map((mol) => (
          <AdvancingCard
            key={mol.id}
            mol={mol}
            status={statusById.get(mol.id) ?? "no_data"}
          />
        ))}
      </div>

      <h2 className="mb-3 text-sm font-semibold text-neutral-300">
        Compare all molecules — any property vs. any property
      </h2>
      <div className="mb-8">
        <PropertyScatter
          molecules={state.molecules}
          highlight={meets}
          onSelect={(id) => router.push(`/molecules/${id}`)}
        />
      </div>

      <h2 className="mb-3 text-sm font-semibold text-neutral-300">All molecules</h2>
      <div className="overflow-x-auto rounded border border-neutral-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-900 text-neutral-400">
            <tr>
              <th className="px-3 py-2">Compound</th>
              <th className="px-3 py-2">TGTA IC50</th>
              <th className="px-3 py-2">Selectivity</th>
              <th className="px-3 py-2">Cellular</th>
              <th className="px-3 py-2">MW</th>
              <th className="px-3 py-2">cLogP</th>
              <th className="px-3 py-2">Assays</th>
            </tr>
          </thead>
          <tbody>
            {state.molecules.map((mol) => {
              const p = moleculeProperties(mol);
              return (
                <tr key={mol.id} className="border-t border-neutral-800 hover:bg-neutral-900/50">
                  <td className="px-3 py-2 font-medium">
                    <Link href={`/molecules/${mol.id}`} className="hover:text-emerald-400">
                      {mol.name}
                    </Link>
                  </td>
                  <td className="px-3 py-2 font-mono">{fmt(p.tgta_ic50)}nM</td>
                  <td className="px-3 py-2 font-mono">{fmt(p.selectivity)}x</td>
                  <td className="px-3 py-2 font-mono">{fmt(p.cell_ic50)}nM</td>
                  <td className="px-3 py-2 font-mono">{p.MW ?? "—"}</td>
                  <td className="px-3 py-2 font-mono">{p.cLogP ?? "—"}</td>
                  <td className="px-3 py-2">{mol.assays.length}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
