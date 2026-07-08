"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useProgram } from "@/lib/ProgramContext";
import { useAppState } from "@/lib/useAppState";
import {
  fetchTppScores,
  fetchMetrics,
  fetchMoleculeValues,
  defineCustomMetric,
  type TppScores,
  type MetricDef,
  type MoleculeValues,
} from "@/lib/api";
import { InteractiveHistogram } from "@/components/InteractiveHistogram";
import { SparkDensity } from "@/components/SparkDensity";

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
  const [showDefine, setShowDefine] = useState(false);
  const [favoritesOnly, setFavoritesOnly] = useState(false);

  // configurable table columns (persisted per program as the default view)
  const DEFAULT_COLUMNS = [
    "assay:biochemical_ic50:TGTA",
    "assay:selectivity:TGTA/TGTB",
    "assay:cellular_antiprolif:TGTA",
  ];
  const [columns, setColumns] = useState<string[]>(DEFAULT_COLUMNS);
  const [valueRows, setValueRows] = useState<MoleculeValues[]>([]);
  const [showColPicker, setShowColPicker] = useState(false);
  const colKey = `moldb.columns.${programId}`;

  const loadMetrics = useCallback(() => {
    fetchMetrics(programId).then(setMetrics).catch(() => setMetrics([]));
  }, [programId]);

  useEffect(() => {
    fetchTppScores(programId).then(setScores).catch(() => setScores(null));
    loadMetrics();
    // restore saved default view
    try {
      const saved = localStorage.getItem(colKey);
      if (saved) setColumns(JSON.parse(saved));
    } catch { /* ignore */ }
  }, [programId, loadMetrics, colKey]);

  // fetch the value matrix whenever the visible columns change
  useEffect(() => {
    fetchMoleculeValues(columns, programId).then(setValueRows).catch(() => setValueRows([]));
  }, [columns, programId]);

  const valuesByMol = useMemo(() => {
    const m = new Map<number, Record<string, number | null>>();
    valueRows.forEach((r) => m.set(r.molecule_id, r.values));
    return m;
  }, [valueRows]);

  const metricLabel = useCallback(
    (key: string) => metrics.find((mm) => mm.key === key)?.label ?? key,
    [metrics],
  );
  const metricUnits = useCallback(
    (key: string) => metrics.find((mm) => mm.key === key)?.units ?? "",
    [metrics],
  );

  function addColumn(key: string) {
    if (!columns.includes(key)) setColumns([...columns, key]);
    setShowColPicker(false);
  }
  function removeColumn(key: string) {
    setColumns(columns.filter((c) => c !== key));
  }
  function saveDefaultView() {
    try { localStorage.setItem(colKey, JSON.stringify(columns)); } catch { /* ignore */ }
    setFlashSaved(true);
    setTimeout(() => setFlashSaved(false), 2500);
  }
  const [flashSaved, setFlashSaved] = useState(false);

  const PRESETS: { name: string; cols: string[] }[] = [
    { name: "Potency & selectivity", cols: DEFAULT_COLUMNS },
    { name: "ADME / physchem", cols: ["adme:MW", "adme:cLogP", "adme:TPSA", "adme:QED"] },
    { name: "In-vitro panel", cols: [
      "assay:biochemical_ic50:TGTA", "assay:biochemical_ic50:TGTB",
      "assay:cellular_antiprolif:TGTA", "assay:tox:*"] },
  ];

  // reset filter when metric changes
  useEffect(() => {
    setSelectedBin(null);
    setBinMemberIds([]);
  }, [metric]);

  const statusById = useMemo(
    () => new Map((scores?.molecules ?? []).map((m) => [m.molecule_id, m.status])),
    [scores],
  );
  const rows = useMemo(() => {
    let mols = state?.molecules ?? [];
    if (favoritesOnly) mols = mols.filter((mo) => mo.favorite);
    if (selectedBin != null) {
      const set = new Set(binMemberIds);
      mols = mols.filter((mo) => set.has(mo.id));
    }
    return mols;
  }, [state, selectedBin, binMemberIds, favoritesOnly]);

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

      {/* at-a-glance density: where most molecules sit for each TPP criterion */}
      {scores && scores.molecules[0] && (
        <div className="mb-4 flex flex-wrap gap-x-8 gap-y-3 rounded border border-border bg-panel p-4">
          {scores.molecules[0].params.map((p) => (
            <SparkDensity key={p.param_id} metric={p.metric} label={p.label} />
          ))}
        </div>
      )}

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
            height={140}
          />
        </div>
      </div>

      {/* table controls: default view presets + save */}
      <div className="mb-2 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-inkMuted">
          {selectedBin != null
            ? `Showing ${rows.length} molecule${rows.length === 1 ? "" : "s"} in the selected range`
            : `${favoritesOnly ? "Favorites" : "All"} · ${rows.length} molecules`}
        </span>
        <label className="flex items-center gap-1 text-xs text-inkMuted">
          <input type="checkbox" checked={favoritesOnly} onChange={(e) => setFavoritesOnly(e.target.checked)} />
          ⚑ Favorites only
        </label>
        <span className="ml-auto text-xs text-inkMuted">Default view:</span>
        <select
          onChange={(e) => { const pr = PRESETS.find((x) => x.name === e.target.value); if (pr) setColumns(pr.cols); }}
          value=""
          className="rounded border border-borderStrong bg-panel px-2 py-1 text-xs"
        >
          <option value="" disabled>Presets…</option>
          {PRESETS.map((pr) => <option key={pr.name} value={pr.name}>{pr.name}</option>)}
        </select>
        <button onClick={saveDefaultView}
          className="rounded border border-borderStrong px-2 py-1 text-xs text-ink hover:bg-panel2">
          {flashSaved ? "✓ Saved" : "Save as default"}
        </button>
      </div>

      <div className="relative overflow-x-auto rounded border border-border">
        <table className="w-full text-left text-sm">
          <thead className="bg-panel2 text-inkMuted">
            <tr>
              <th className="px-3 py-2 font-medium">Compound</th>
              {columns.map((key) => (
                <th key={key} className="group px-3 py-2 font-medium">
                  <span className="inline-flex items-center gap-1">
                    {metricLabel(key)}
                    <button
                      onClick={() => removeColumn(key)}
                      title="Remove column"
                      className="text-inkFaint opacity-0 group-hover:opacity-100 hover:text-red-600"
                    >
                      ✕
                    </button>
                  </span>
                </th>
              ))}
              <th className="px-3 py-2">
                <button
                  onClick={() => setShowColPicker((s) => !s)}
                  className="rounded border border-borderStrong px-2 py-0.5 text-xs text-ink hover:bg-panel"
                  title="Add a column from the database"
                >
                  + Column
                </button>
              </th>
              <th className="px-3 py-2 font-medium">TPP status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((mo) => {
              const status = statusById.get(mo.id) ?? "no_data";
              const vals = valuesByMol.get(mo.id) ?? {};
              return (
                <tr key={mo.id} className="border-t border-border hover:bg-panel2/60">
                  <td className="px-3 py-2 font-medium">
                    <Link href={`/molecules/${mo.id}`} className="hover:text-emerald-700">{mo.name}</Link>
                  </td>
                  {columns.map((key) => {
                    const v = vals[key];
                    return (
                      <td key={key} className="px-3 py-2 font-mono">
                        {v != null ? `${fmt(v)}${metricUnits(key)}` : "—"}
                      </td>
                    );
                  })}
                  <td />
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

        {/* column picker popover */}
        {showColPicker && (
          <div className="absolute right-2 top-10 z-20 max-h-80 w-72 overflow-y-auto rounded border border-borderStrong bg-panel p-2 shadow-lg">
            <div className="mb-1 px-1 text-xs font-medium text-inkMuted">Add a column</div>
            {metrics.filter((m) => !columns.includes(m.key)).map((m) => (
              <button key={m.key} onClick={() => addColumn(m.key)}
                className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-panel2">
                <span>{m.label}</span>
                <span className="text-xs text-inkFaint">{m.count ?? 0}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
