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

const fmt = (v: number, u: string | null) =>
  `${v >= 1000 ? (v / 1000).toFixed(1) + "k" : v}${u ?? ""}`;

export default function TppPage() {
  const { programId } = useProgram();
  const [tpp, setTpp] = useState<CurrentTpp | null>(null);
  const [versions, setVersions] = useState<TppVersion[]>([]);
  const [selected, setSelected] = useState<TppParam | null>(null);
  const [building, setBuilding] = useState(false);
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

      <div className="space-y-3">
        {tpp.params.map((p) => (
          <button
            key={p.id}
            onClick={() => setSelected(p)}
            className="block w-full rounded border border-neutral-800 bg-neutral-900 p-4 text-left hover:border-neutral-600"
          >
            <div className="flex items-baseline justify-between">
              <span className="text-sm font-medium">{p.label}</span>
              <span className="rounded bg-neutral-800 px-2 py-0.5 font-mono text-xs text-emerald-300">
                {p.operator} {fmt(p.threshold, p.units)}
              </span>
            </div>
            <p className="mt-1 line-clamp-2 text-xs text-neutral-400">{p.rationale}</p>
          </button>
        ))}
      </div>

      <div className="mt-8 rounded border border-neutral-800 bg-neutral-900 p-5">
        <h2 className="text-sm font-semibold">Design a new TPP</h2>
        <p className="mt-1 text-sm text-neutral-400">
          Work through a guided conversation with the TPP Builder agent (Opus) to craft a fresh
          Target Product Profile for this program. Finalizing creates the next version.
        </p>
        <button
          onClick={() => setBuilding(true)}
          className="mt-3 rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white"
        >
          Build a new TPP with Opus →
        </button>
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
    </div>
  );
}
