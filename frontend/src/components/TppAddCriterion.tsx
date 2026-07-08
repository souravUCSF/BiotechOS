"use client";

import { useEffect, useMemo, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { fetchMetrics, addTppParam, defineCustomMetric, type MetricDef } from "@/lib/api";

const ARITH = [
  { sym: "÷", op: "/" },
  { sym: "×", op: "*" },
  { sym: "−", op: "-" },
  { sym: "+", op: "+" },
];

// grouped <select> over the catalog, reused for single + composite pickers
function MetricSelect({
  metrics,
  value,
  onChange,
}: {
  metrics: MetricDef[];
  value: string;
  onChange: (key: string) => void;
}) {
  const groups: [string, MetricDef[]][] = [
    ["Assays", metrics.filter((m) => m.kind === "assay" && !m.key.startsWith("cell:"))],
    ["Anti-proliferation by cell line", metrics.filter((m) => m.key.startsWith("cell:"))],
    ["Computed (ADME / physchem)", metrics.filter((m) => m.kind === "adme")],
    ["Derived (formulas)", metrics.filter((m) => m.kind === "formula")],
    ["Custom", metrics.filter((m) => m.kind === "custom")],
  ];
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
      className="rounded border border-borderStrong bg-panel px-2 py-1.5 text-sm">
      <option value="" disabled>Select a property…</option>
      {groups.map(([label, ms]) => ms.length > 0 && (
        <optgroup key={label} label={label}>
          {ms.map((m) => <option key={m.key} value={m.key}>{m.label} ({m.count ?? 0})</option>)}
        </optgroup>
      ))}
    </select>
  );
}

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
  const [mode, setMode] = useState<"single" | "composite">("single");

  // single
  const [metric, setMetric] = useState("");
  // composite
  const [metricA, setMetricA] = useState("");
  const [arith, setArith] = useState("/");
  const [metricB, setMetricB] = useState("");

  const [operator, setOperator] = useState("<");
  const [threshold, setThreshold] = useState("");
  const [rationale, setRationale] = useState("");
  const [justification, setJustification] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMetrics(programId).then((all) => {
      const avail = all.filter((m) => m.kind === "formula" || !existingMetrics.includes(m.key));
      setMetrics(avail);
    });
  }, [programId, existingMetrics]);

  const byKey = useMemo(() => new Map(metrics.map((m) => [m.key, m])), [metrics]);
  const defA = byKey.get(metricA);
  const defB = byKey.get(metricB);
  const arithSym = ARITH.find((a) => a.op === arith)?.sym ?? arith;
  const compositeLabel = defA && defB ? `${defA.label} ${arithSym} ${defB.label}` : "";

  function pickSingle(key: string) {
    setMetric(key);
    const d = byKey.get(key);
    if (d) setOperator(d.higher_is_better ? ">" : "<");
  }

  async function save() {
    if (!justification.trim()) return setError("A written justification is required.");
    if (threshold === "") return setError("Enter a threshold.");
    setBusy(true);
    setError(null);
    try {
      let key = metric;
      let label = byKey.get(metric)?.label ?? metric;
      let units = byKey.get(metric)?.units ?? "";

      if (mode === "composite") {
        if (!defA || !defB || !defA.alias || !defB.alias)
          throw new Error("Pick both properties.");
        const formula = `${defA.alias} ${arith} ${defB.alias}`;
        label = compositeLabel;
        units = arith === "/" ? "ratio" : "";
        const created = await defineCustomMetric(
          { label, units, formula, higher_is_better: operator === ">" }, programId);
        key = created.key;
      } else if (!metric) {
        throw new Error("Pick a property.");
      }

      const r = await addTppParam(
        { axis: "custom", label, metric: key, operator, threshold: Number(threshold),
          units, rationale },
        justification, programId);
      onVersioned(r.new_version);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  const units = mode === "composite" ? (arith === "/" ? "ratio" : "") : (byKey.get(metric)?.units ?? "");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="w-full max-w-xl rounded-lg border border-borderStrong bg-panel p-6"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Add a TPP criterion</h2>
          <button onClick={onClose} className="text-inkMuted hover:text-ink">✕</button>
        </div>

        {/* mode toggle */}
        <div className="mb-4 inline-flex rounded border border-borderStrong text-sm">
          <button onClick={() => setMode("single")}
            className={`px-3 py-1 ${mode === "single" ? "bg-emerald-600 text-white" : "text-ink"}`}>
            Single property
          </button>
          <button onClick={() => setMode("composite")}
            className={`px-3 py-1 ${mode === "composite" ? "bg-emerald-600 text-white" : "text-ink"}`}>
            Composite (A ∘ B)
          </button>
        </div>

        {mode === "single" ? (
          <div className="mb-4">
            <label className="mb-1 block text-xs text-inkMuted">Property</label>
            <MetricSelect metrics={metrics} value={metric} onChange={pickSingle} />
          </div>
        ) : (
          <div className="mb-4">
            <label className="mb-1 block text-xs text-inkMuted">
              Build a value from two properties
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <MetricSelect metrics={metrics} value={metricA} onChange={setMetricA} />
              <select value={arith} onChange={(e) => setArith(e.target.value)}
                className="rounded border border-borderStrong bg-panel px-2 py-1.5 text-sm">
                {ARITH.map((a) => <option key={a.op} value={a.op}>{a.sym}</option>)}
              </select>
              <MetricSelect metrics={metrics} value={metricB} onChange={setMetricB} />
            </div>
            {compositeLabel && (
              <div className="mt-2 text-xs text-inkMuted">
                New property: <span className="font-medium text-ink">{compositeLabel}</span>
              </div>
            )}
          </div>
        )}

        <div className="mb-3 flex items-center gap-2 text-sm">
          <span className="text-inkMuted">Criterion:</span>
          <select value={operator} onChange={(e) => setOperator(e.target.value)}
            className="rounded border border-borderStrong bg-panel px-2 py-1">
            <option value="<">&lt; (lower is better)</option>
            <option value=">">&gt; (higher is better)</option>
          </select>
          <input value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder="threshold"
            className="w-28 rounded border border-borderStrong bg-panel px-2 py-1 font-mono" />
          <span className="text-inkMuted">{units}</span>
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
