"use client";

import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { fetchMetrics, addTppParam, type MetricDef } from "@/lib/api";

export function TppAddCriterion({
  existingMetrics,
  onClose,
  onVersioned,
}: {
  existingMetrics: string[];
  onClose: () => void;
  onVersioned: (v: number) => void;
}) {
  const { programId } = useProgram();
  const [metrics, setMetrics] = useState<MetricDef[]>([]);
  const [metric, setMetric] = useState<string>("");
  const [operator, setOperator] = useState("<");
  const [threshold, setThreshold] = useState("");
  const [rationale, setRationale] = useState("");
  const [justification, setJustification] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMetrics(programId).then((all) => {
      const avail = all.filter((m) => !existingMetrics.includes(m.key));
      setMetrics(avail);
      if (avail[0]) {
        setMetric(avail[0].key);
        setOperator(avail[0].higher_is_better ? ">" : "<");
      }
    });
  }, [programId, existingMetrics]);

  const def = metrics.find((m) => m.key === metric);

  function pick(key: string) {
    setMetric(key);
    const d = metrics.find((m) => m.key === key);
    if (d) setOperator(d.higher_is_better ? ">" : "<");
  }

  async function save() {
    if (!metric || threshold === "") {
      setError("Pick a property and enter a threshold.");
      return;
    }
    if (!justification.trim()) {
      setError("A written justification is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await addTppParam(
        {
          axis: def?.kind === "adme" ? "adme" : "custom",
          label: def?.label ?? metric,
          metric,
          operator,
          threshold: Number(threshold),
          units: def?.units ?? "",
          rationale,
        },
        justification,
        programId,
      );
      onVersioned(r.new_version);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="w-full max-w-lg rounded-lg border border-borderStrong bg-panel p-6"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Add a TPP criterion</h2>
          <button onClick={onClose} className="text-inkMuted hover:text-ink">✕</button>
        </div>

        <label className="mb-1 block text-xs text-inkMuted">Property</label>
        <select value={metric} onChange={(e) => pick(e.target.value)}
          className="mb-3 w-full rounded border border-borderStrong bg-panel px-2 py-1.5 text-sm">
          <optgroup label="Assays">
            {metrics.filter((m) => m.kind === "assay").map((m) => (
              <option key={m.key} value={m.key}>{m.label} ({m.count ?? 0} molecules)</option>
            ))}
          </optgroup>
          <optgroup label="Computed (ADME / physchem)">
            {metrics.filter((m) => m.kind === "adme").map((m) => (
              <option key={m.key} value={m.key}>{m.label} ({m.count ?? 0})</option>
            ))}
          </optgroup>
          {metrics.some((m) => m.kind === "formula") && (
            <optgroup label="Derived (formulas)">
              {metrics.filter((m) => m.kind === "formula").map((m) => (
                <option key={m.key} value={m.key}>{m.label} ({m.count ?? 0})</option>
              ))}
            </optgroup>
          )}
          {metrics.some((m) => m.kind === "custom") && (
            <optgroup label="Custom">
              {metrics.filter((m) => m.kind === "custom").map((m) => (
                <option key={m.key} value={m.key}>{m.label} ({m.count ?? 0})</option>
              ))}
            </optgroup>
          )}
        </select>

        <div className="mb-3 flex items-center gap-2 text-sm">
          <span className="text-inkMuted">Criterion:</span>
          <select value={operator} onChange={(e) => setOperator(e.target.value)}
            className="rounded border border-borderStrong bg-panel px-2 py-1">
            <option value="<">&lt; (lower is better)</option>
            <option value=">">&gt; (higher is better)</option>
          </select>
          <input value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder="threshold"
            className="w-28 rounded border border-borderStrong bg-panel px-2 py-1 font-mono" />
          <span className="text-inkMuted">{def?.units}</span>
        </div>

        <label className="mb-1 block text-xs text-inkMuted">Rationale (optional)</label>
        <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} rows={2}
          placeholder="Why this criterion matters…"
          className="mb-3 w-full rounded border border-borderStrong bg-panel p-2 text-sm" />

        <div className="mb-2 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-700">
          ⚠ Adding a criterion updates the TPP globally and creates a new version.
        </div>
        <label className="mb-1 block text-xs text-inkMuted">Justification (required)</label>
        <textarea value={justification} onChange={(e) => setJustification(e.target.value)} rows={2}
          placeholder="Why add this now?"
          className="w-full rounded border border-borderStrong bg-panel p-2 text-sm" />

        {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
        <div className="mt-3">
          <button onClick={save} disabled={busy || !justification.trim() || threshold === ""}
            className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
            {busy ? "Adding…" : "Add as new version"}
          </button>
        </div>
      </div>
    </div>
  );
}
