"use client";

import { useCallback, useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import {
  fetchCurrentTpp,
  fetchTppVersions,
  type CurrentTpp,
  type TppVersion,
  type TppParam,
} from "@/lib/api";
import { TppParamModal } from "@/components/TppParamModal";
import { TppBuilderDialog } from "@/components/TppBuilderDialog";
import { TppAddCriterion } from "@/components/TppAddCriterion";

const fmt = (v: number, u: string | null) =>
  `${v >= 1000 ? (v / 1000).toFixed(1) + "k" : v}${u ?? ""}`;

export default function TppPage() {
  const { programId } = useProgram();
  const [tpp, setTpp] = useState<CurrentTpp | null>(null);
  const [versions, setVersions] = useState<TppVersion[]>([]);
  const [selected, setSelected] = useState<TppParam | null>(null);
  const [building, setBuilding] = useState(false);
  const [adding, setAdding] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchCurrentTpp(programId).then(setTpp).catch(() => setTpp(null));
    fetchTppVersions(programId).then(setVersions).catch(() => setVersions([]));
  }, [programId]);

  useEffect(() => {
    load();
  }, [load]);

  function onVersioned(v: number) {
    setSelected(null);
    setBuilding(false);
    setAdding(false);
    setFlash(`TPP updated → v${v} is now active. All molecules re-scored.`);
    load();
    setTimeout(() => setFlash(null), 6000);
  }

  if (!tpp) return <p className="text-neutral-400">Loading…</p>;

  return (
    <div className="max-w-3xl">
      <div className="mb-1 flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Target Product Profile</h1>
        {tpp.version && (
          <span className="rounded bg-emerald-700 px-2 py-0.5 text-xs text-white">
            v{tpp.version.version} · active
          </span>
        )}
      </div>
      <p className="mb-5 text-sm text-neutral-400">
        The current go/no-go criteria for this program. Click any criterion to see what it means,
        where the molecules sit, and to change it (which creates a new version).
      </p>

      {flash && (
        <div className="mb-4 rounded border border-emerald-700/50 bg-emerald-950/30 p-3 text-sm text-emerald-300">
          {flash}
        </div>
      )}

      {/* the TPP as a single cohesive table */}
      <div className="overflow-hidden rounded-lg border border-neutral-700">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-900 text-neutral-300">
            <tr>
              <th className="w-56 border-b border-neutral-700 px-4 py-3 font-semibold">Parameter</th>
              <th className="w-40 border-b border-neutral-700 px-4 py-3 font-semibold">Criterion</th>
              <th className="border-b border-neutral-700 px-4 py-3 font-semibold">Rationale</th>
            </tr>
          </thead>
          <tbody>
            {tpp.params.map((p) => (
              <tr
                key={p.id}
                onClick={() => setSelected(p)}
                className="cursor-pointer border-b border-neutral-800 last:border-b-0 hover:bg-neutral-900/60"
              >
                <td className="px-4 py-3 align-top font-medium text-neutral-100">{p.label}</td>
                <td className="px-4 py-3 align-top font-mono text-emerald-300">
                  {p.operator} {fmt(p.threshold, p.units)}
                </td>
                <td className="px-4 py-3 align-top text-xs text-neutral-400">{p.rationale}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          onClick={() => setAdding(true)}
          className="w-full border-t border-neutral-800 bg-neutral-950 px-4 py-2.5 text-left text-sm text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200"
        >
          + Add a criterion
        </button>
      </div>

      <p className="mt-2 text-xs text-neutral-600">
        Click any row to see what it means, where the molecules sit, and to change it.
      </p>

      {/* demoted: rebuild from scratch with Opus */}
      <hr className="my-8 border-neutral-800" />
      <div className="text-sm text-neutral-500">
        Or{" "}
        <button onClick={() => setBuilding(true)} className="text-neutral-300 underline hover:text-emerald-400">
          rebuild the whole TPP from scratch with Opus
        </button>{" "}
        — a guided conversation that finalizes into a new version.
      </div>

      {versions.length > 0 && (
        <div className="mt-8">
          <h2 className="mb-2 text-sm font-semibold text-neutral-300">Version history</h2>
          <ol className="space-y-2">
            {versions.map((v) => (
              <li
                key={v.id}
                className="rounded border border-neutral-800 bg-neutral-900 p-3 text-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">
                    v{v.version}{" "}
                    {v.active ? (
                      <span className="ml-1 rounded bg-emerald-700 px-1.5 py-0.5 text-xs text-white">active</span>
                    ) : null}
                  </span>
                  <span className="text-xs text-neutral-500">{v.created_at} · {v.author}</span>
                </div>
                {v.notes && <p className="mt-1 text-xs text-neutral-400">{v.notes}</p>}
              </li>
            ))}
          </ol>
        </div>
      )}

      {selected && (
        <TppParamModal param={selected} onClose={() => setSelected(null)} onVersioned={onVersioned} />
      )}
      {building && (
        <TppBuilderDialog onClose={() => setBuilding(false)} onCreated={onVersioned} />
      )}
      {adding && (
        <TppAddCriterion
          existingMetrics={tpp.params.map((p) => p.metric)}
          onClose={() => setAdding(false)}
          onVersioned={onVersioned}
        />
      )}
    </div>
  );
}
