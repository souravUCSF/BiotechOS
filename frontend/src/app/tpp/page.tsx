"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useProgram } from "@/lib/ProgramContext";
import { useAppState } from "@/lib/useAppState";
import {
  fetchTppScores,
  fetchMetrics,
  defineCustomMetric,
  type TppScores,
  type MetricDef,
  type Histogram,
} from "@/lib/api";
import { InteractiveHistogram } from "@/components/InteractiveHistogram";
import { moleculeProperties } from "@/lib/properties";

const STATUS_STYLE: Record<string, string> = {
  pass: "bg-emerald-600 text-white",
  near: "bg-amber-500 text-black",
  fail: "bg-panel2 text-inkMuted",
  no_data: "bg-panel text-neutral-700",
};
const fmt = (v: number | null | undefined) =>
  v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(1);

function DefinePropertyForm({ onDone }: { onDone: (key: string) => void }) {
  const { programId } = useProgram();
  const [label, setLabel] = useState("");
  const [units, setUnits] = useState("");
  const [higher, setHigher] = useState(false);
  const [log, setLog] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!label.trim()) return;
    setBusy(true);
    try {
      const r = await defineCustomMetric(
        { label: label.trim(), units, higher_is_better: higher, log },
        programId,
      );
      onDone(r.key);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 rounded border border-border bg-panel p-3">
      <div className="mb-2 text-xs font-medium text-ink">
        Define a new molecule property (no data yet — arrives later via CRO assays)
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <input value={label} onChange={(e) => setLabel(e.target.value)}
          placeholder="Property name (e.g. NanoBRET target engagement)"
          className="min-w-[16rem] flex-1 rounded border border-borderStrong bg-bg px-2 py-1" />
        <input value={units} onChange={(e) => setUnits(e.target.value)} placeholder="units"
          className="w-20 rounded border border-borderStrong bg-bg px-2 py-1" />
        <label className="flex items-center gap-1 text-xs text-inkMuted">
          <input type="checkbox" checked={higher} onChange={(e) => setHigher(e.target.checked)} /> higher is better
        </label>
        <label className="flex items-center gap-1 text-xs text-inkMuted">
          <input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> log scale
        </label>
        <button onClick={submit} disabled={busy || !label.trim()}
          className="rounded bg-emerald-600 px-3 py-1 text-sm text-white disabled:opacity-50">
          {busy ? "Adding…" : "Add property"}
        </button>
      </div>
    </div>
  );
}

export default function MoleculeDatabasePage() {
  const { programId } = useProgram();
  const { state } = useAppState();
  const [scores, setScores] = useState<TppScores | null>(null);
  const [metrics, setMetrics] = useState<MetricDef[]>([]);
  const [metric, setMetric] = useState<string>("assay:biochemical_ic50:TGTA");
  const [selectedBin, setSelectedBin] = useState<number | null>(null);
  const [binMemberIds, setBinMemberIds] = useState<number[]>([]);
  const [hist, setHist] = useState<Histogram | null>(null);
  const [showDefine, setShowDefine] = useState(false);

  const loadMetrics = useCallback(() => {
    fetchMetrics(programId).then(setMetrics).catch(() => setMetrics([]));
  }, [programId]);

  useEffect(() => {
    fetchTppScores(programId).then(setScores).catch(() => setScores(null));
    loadMetrics();
  }, [programId, loadMetrics]);

  // reset filter when metric changes
  useEffect(() => {
    setSelectedBin(null);
    setBinMemberIds([]);
  }, [metric]);

  const statusById = useMemo(
    () => new Map((scores?.molecules ?? []).map((m) => [m.molecule_id, m.status])),
    [scores],
  );
  const valueById = useMemo(() => {
    const m = new Map<number, number>();
    (hist?.members ?? []).forEach((x) => m.set(x.molecule_id, x.value));
    return m;
  }, [hist]);

  const metricDef = metrics.find((m) => m.key === metric);

  const rows = useMemo(() => {
    let mols = state?.molecules ?? [];
    if (selectedBin != null) {
      const set = new Set(binMemberIds);
      mols = mols.filter((mo) => set.has(mo.id));
    }
    return mols;
  }, [state, selectedBin, binMemberIds]);

  if (!state) return <p className="text-inkMuted">Loading…</p>;

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Molecule Database</h1>
        <div className="text-sm text-inkMuted">
          {scores && (
            <>
              <span className="font-medium text-emerald-700">{scores.meets_tpp.length}</span> meet the
              TPP · {state.molecules.length} molecules
            </>
          )}
        </div>
      </div>
      <p className="mb-5 text-sm text-inkMuted">
        Explore any property in the system. TPP criteria are shown up top; pick a bar in a
        histogram to filter the molecules below to that range.
      </p>

      {/* TPP snapshot */}
      {scores && scores.molecules[0] && (
        <div className="mb-6 flex flex-wrap gap-2">
          {scores.molecules[0].params.map((p) => (
            <span key={p.param_id} className="rounded border border-border bg-panel px-2 py-1 text-xs">
              {p.label}: <span className="font-mono text-emerald-700">{p.operator} {fmt(p.threshold)}{p.units}</span>
            </span>
          ))}
        </div>
      )}

      {/* property explorer */}
      <div className="mb-4 rounded border border-border bg-bg p-4">
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-inkMuted">
            Property:{" "}
            <select value={metric} onChange={(e) => setMetric(e.target.value)}
              className="rounded border border-borderStrong bg-panel px-2 py-1 text-sm text-ink">
              <optgroup label="Assays">
                {metrics.filter((m) => m.kind === "assay").map((m) => (
                  <option key={m.key} value={m.key}>{m.label} ({m.count ?? 0})</option>
                ))}
              </optgroup>
              <optgroup label="Computed (ADME / physchem)">
                {metrics.filter((m) => m.kind === "adme").map((m) => (
                  <option key={m.key} value={m.key}>{m.label} ({m.count ?? 0})</option>
                ))}
              </optgroup>
              {metrics.some((m) => m.kind === "custom") && (
                <optgroup label="Custom">
                  {metrics.filter((m) => m.kind === "custom").map((m) => (
                    <option key={m.key} value={m.key}>{m.label} ({m.count ?? 0})</option>
                  ))}
                </optgroup>
              )}
            </select>
          </label>
          <button onClick={() => setShowDefine((s) => !s)}
            className="text-xs text-emerald-700 hover:underline">
            + Define new property
          </button>
          {selectedBin != null && (
            <button onClick={() => { setSelectedBin(null); setBinMemberIds([]); }}
              className="ml-auto rounded border border-borderStrong px-2 py-1 text-xs text-ink hover:bg-panel2">
              Clear filter ✕
            </button>
          )}
        </div>

        {showDefine && <DefinePropertyForm onDone={(key) => { setShowDefine(false); loadMetrics(); setMetric(key); }} />}

        <div className="mt-4">
          <InteractiveHistogram
            metric={metric}
            selectedBin={selectedBin}
            onSelectBin={(bin, ids) => { setSelectedBin(bin); setBinMemberIds(ids); }}
            onData={setHist}
            height={140}
          />
        </div>
      </div>

      <div className="mb-2 text-sm text-inkMuted">
        {selectedBin != null
          ? `Showing ${rows.length} molecule${rows.length === 1 ? "" : "s"} in the selected range`
          : `All ${rows.length} molecules`}
      </div>

      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full text-left text-sm">
          <thead className="bg-panel text-inkMuted">
            <tr>
              <th className="px-3 py-2">Compound</th>
              <th className="px-3 py-2">{metricDef?.label ?? "Property"}</th>
              <th className="px-3 py-2">TGTA IC50</th>
              <th className="px-3 py-2">Selectivity</th>
              <th className="px-3 py-2">TPP status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((mo) => {
              const props = moleculeProperties(mo);
              const val = valueById.get(mo.id);
              const status = statusById.get(mo.id) ?? "no_data";
              return (
                <tr key={mo.id} className="border-t border-border hover:bg-panel2/60">
                  <td className="px-3 py-2 font-medium">
                    <Link href={`/molecules/${mo.id}`} className="hover:text-emerald-700">{mo.name}</Link>
                  </td>
                  <td className="px-3 py-2 font-mono">{val != null ? `${fmt(val)}${metricDef?.units ?? ""}` : "—"}</td>
                  <td className="px-3 py-2 font-mono">{fmt(props.tgta_ic50)}nM</td>
                  <td className="px-3 py-2 font-mono">{fmt(props.selectivity)}x</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[status]}`}>
                      {status === "pass" ? "MEETS TPP" : status.toUpperCase()}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
