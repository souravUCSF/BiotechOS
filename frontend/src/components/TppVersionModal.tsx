"use client";

import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { fetchTppVersion, type CurrentTpp } from "@/lib/api";

const fmt = (v: number, u: string | null) =>
  `${v >= 1000 ? (v / 1000).toFixed(1) + "k" : v}${u ?? ""}`;

export function TppVersionModal({ version, onClose }: { version: number; onClose: () => void }) {
  const { programId } = useProgram();
  const [data, setData] = useState<CurrentTpp | null>(null);

  useEffect(() => {
    fetchTppVersion(version, programId).then(setData).catch(() => setData(null));
  }, [version, programId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-borderStrong bg-panel p-6"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-1 flex items-start justify-between">
          <h2 className="text-lg font-semibold">
            TPP v{version}
            {data?.version?.active ? (
              <span className="ml-2 rounded bg-emerald-600 px-2 py-0.5 text-xs text-white">active</span>
            ) : (
              <span className="ml-2 rounded bg-panel2 px-2 py-0.5 text-xs text-inkMuted">superseded</span>
            )}
          </h2>
          <button onClick={onClose} className="text-inkMuted hover:text-ink">✕</button>
        </div>
        {data?.version && (
          <div className="mb-4 text-xs text-inkMuted">
            {data.version.created_at} · {data.version.author}
            {data.version.notes ? <> · {data.version.notes}</> : null}
          </div>
        )}

        {!data ? (
          <p className="text-sm text-inkMuted">Loading…</p>
        ) : (
          <div className="overflow-hidden rounded border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-panel2 text-inkMuted">
                <tr>
                  <th className="px-3 py-2 font-medium">Parameter</th>
                  <th className="px-3 py-2 font-medium">Criterion</th>
                  <th className="px-3 py-2 font-medium">Rationale</th>
                </tr>
              </thead>
              <tbody>
                {data.params.map((p) => (
                  <tr key={p.id} className="border-t border-border">
                    <td className="px-3 py-2 align-top font-medium">{p.label}</td>
                    <td className="px-3 py-2 align-top font-mono text-emerald-700">
                      {p.operator} {fmt(p.threshold, p.units)}
                    </td>
                    <td className="px-3 py-2 align-top text-xs text-inkMuted">{p.rationale}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
