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
  addManualMolecule,
  createGroup,
  fetchGroups,
  setFavorite,
  type MoleculeGroup,
  type TppScores,
  type MetricDef,
  type MoleculeValues,
  type ManualAssayInput,
} from "@/lib/api";
import { InteractiveHistogram } from "@/components/InteractiveHistogram";
import { SparkDensity } from "@/components/SparkDensity";
import { API_BASE } from "@/lib/apiBase";

const STATUS_STYLE: Record<string, string> = {
  pass: "bg-emerald-600 text-white",
  near: "bg-amber-500 text-black",
  fail: "bg-panel2 text-inkMuted",
  no_data: "bg-panel text-neutral-700",
};
const fmt = (v: number | null | undefined) =>
  v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(1);

function DefinePropertyForm({ onDone, aliases }: { onDone: (key: string) => void; aliases: string[] }) {
  const { programId } = useProgram();
  const [label, setLabel] = useState("");
  const [units, setUnits] = useState("");
  const [higher, setHigher] = useState(false);
  const [log, setLog] = useState(false);
  const [formula, setFormula] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!label.trim()) return;
    setBusy(true);
    try {
      const r = await defineCustomMetric(
        { label: label.trim(), units, higher_is_better: higher, log, formula: formula.trim() || undefined },
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
        Define a new molecule property
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <input value={label} onChange={(e) => setLabel(e.target.value)}
          placeholder="Property name (e.g. Cellular/biochemical ratio)"
          className="min-w-[16rem] flex-1 rounded border border-borderStrong bg-bg px-2 py-1" />
        <input value={units} onChange={(e) => setUnits(e.target.value)} placeholder="units"
          className="w-20 rounded border border-borderStrong bg-bg px-2 py-1" />
        <label className="flex items-center gap-1 text-xs text-inkMuted">
          <input type="checkbox" checked={higher} onChange={(e) => setHigher(e.target.checked)} /> higher is better
        </label>
        <label className="flex items-center gap-1 text-xs text-inkMuted">
          <input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> log scale
        </label>
      </div>
      <div className="mt-2">
        <input value={formula} onChange={(e) => setFormula(e.target.value)}
          placeholder="Optional formula, e.g.  cell_ic50 / tgta_ic50   (leave blank for an empty property)"
          className="w-full rounded border border-borderStrong bg-bg px-2 py-1 font-mono text-sm" />
        <div className="mt-1 text-[11px] text-inkFaint">
          Arithmetic over other properties (+ − × ÷, parentheses, log10/abs). Available:{" "}
          <span className="font-mono">{aliases.join(", ")}</span>
        </div>
      </div>
      <div className="mt-2">
        <button onClick={submit} disabled={busy || !label.trim()}
          className="rounded bg-emerald-600 px-3 py-1 text-sm text-white disabled:opacity-50">
          {busy ? "Adding…" : "Add property"}
        </button>
      </div>
    </div>
  );
}

// Manually add a molecule + data straight into the database (active, bypasses registry).
function AddMoleculeModal({ programId, onClose, onAdded }:
  { programId: string; onClose: () => void; onAdded: () => void }) {
  const [name, setName] = useState("");
  const [smiles, setSmiles] = useState("");
  const [aliases, setAliases] = useState("");
  const [rows, setRows] = useState<ManualAssayInput[]>([
    { modality: "generic_numeric", standard_type: "", value: null, units: "", target: "" },
  ]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function setRow(i: number, patch: Partial<ManualAssayInput>) {
    setRows((xs) => xs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }
  async function submit() {
    if (!name.trim()) { setErr("Name is required."); return; }
    setBusy(true); setErr("");
    try {
      await addManualMolecule({
        program_id: programId, name: name.trim(),
        smiles: smiles.trim() || undefined,
        aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean),
        assays: rows.filter((r) => r.value != null && String(r.value) !== "")
          .map((r) => ({ ...r, value: Number(r.value) })),
      });
      onAdded(); onClose();
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  const inp = "rounded border border-borderStrong bg-panel px-2 py-1 text-sm";
  return (
    <div className="fixed inset-0 z-30 flex items-start justify-center overflow-y-auto bg-black/50 p-8" onClick={onClose}>
      <div className="w-full max-w-5xl rounded-lg border border-border bg-panel p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <div className="text-base font-semibold text-ink">Add a molecule manually</div>
          <button onClick={onClose} className="text-inkMuted hover:text-ink">✕</button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs text-inkMuted">Compound name / code *
            <input value={name} onChange={(e) => setName(e.target.value)} className={inp} placeholder="e.g. BTX-2001" /></label>
          <label className="flex flex-col gap-1 text-xs text-inkMuted">Aliases (comma-separated)
            <input value={aliases} onChange={(e) => setAliases(e.target.value)} className={inp} placeholder="CRO code, common name…" /></label>
          <label className="col-span-2 flex flex-col gap-1 text-xs text-inkMuted">SMILES (optional — validated)
            <input value={smiles} onChange={(e) => setSmiles(e.target.value)} className={`${inp} font-mono`} placeholder="CC(=O)…" /></label>
        </div>
        <div className="mt-4 mb-1 text-xs font-semibold text-inkMuted">Data</div>
        <div className="mb-1 grid grid-cols-[1fr_1fr_1fr_80px_80px_1fr_24px] gap-1.5 text-[10px] text-inkFaint">
          <span className="cursor-help justify-self-start underline decoration-dotted" title="Assay family. e.g. biochemical_ic50, cellular_antiprolif, selectivity, admet. Use generic_numeric as the catch-all for any plain numeric readout that doesn't fit a family.">modality</span>
          <span className="cursor-help justify-self-start underline decoration-dotted" title="Measurement type. e.g. IC50, EC50, Ki, Kd, %inhibition, Papp, half-life. Free text.">type</span>
          <span className="cursor-help justify-self-start underline decoration-dotted" title="Biological target or entity measured. e.g. TGTA, TGTB. Leave blank if not applicable.">target</span>
          <span className="cursor-help justify-self-start underline decoration-dotted" title="The numeric result.">value</span>
          <span className="cursor-help justify-self-start underline decoration-dotted" title="Units of the value. e.g. nM, µM, %, mL/min/kg, h.">units</span>
          <span className="cursor-help justify-self-start underline decoration-dotted" title="Test system / context. e.g. a cell line (HeLa), tissue, microsome, or buffer. Leave blank if none.">system</span>
          <span />
        </div>
        <div className="space-y-1.5">
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_1fr_80px_80px_1fr_24px] items-center gap-1.5">
              <input value={r.modality ?? ""} onChange={(e) => setRow(i, { modality: e.target.value })} className={inp} placeholder="cellular_antiprolif" />
              <input value={r.standard_type ?? ""} onChange={(e) => setRow(i, { standard_type: e.target.value })} className={inp} placeholder="IC50" />
              <input value={r.target ?? ""} onChange={(e) => setRow(i, { target: e.target.value })} className={inp} placeholder="TGTA" />
              <input value={r.value == null ? "" : String(r.value)} onChange={(e) => setRow(i, { value: e.target.value === "" ? null : Number(e.target.value) })} className={`${inp} text-right`} placeholder="10" />
              <input value={r.units ?? ""} onChange={(e) => setRow(i, { units: e.target.value })} className={inp} placeholder="nM" />
              <input value={r.system ?? ""} onChange={(e) => setRow(i, { system: e.target.value, system_type: e.target.value ? "cell_line" : r.system_type })} className={inp} placeholder="HeLa" />
              <button onClick={() => setRows((xs) => xs.filter((_, j) => j !== i))} className="text-inkFaint hover:text-red-500" title="remove">✕</button>
            </div>
          ))}
        </div>
        <button onClick={() => setRows((xs) => [...xs, { modality: "generic_numeric", standard_type: "", value: null, units: "", target: "", system: "" }])}
          className="mt-1 text-xs text-sky-500 hover:underline">+ add data row</button>
        <div className="mt-3">
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-inkFaint">Examples — how different data looks in this format</div>
          <table className="w-full text-left text-[11px] text-inkMuted">
            <thead className="text-inkFaint">
              <tr>
                <th className="py-0.5 pr-2 font-normal">what you have</th>
                <th className="px-2 py-0.5 font-normal">modality</th><th className="px-2 py-0.5 font-normal">type</th>
                <th className="px-2 py-0.5 font-normal">target</th><th className="px-2 py-0.5 font-normal">value</th>
                <th className="px-2 py-0.5 font-normal">units</th><th className="px-2 py-0.5 font-normal">system</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {[
                ["2D proliferation IC50 in HeLa", "cellular_antiprolif", "IC50", "TGTA", "10", "nM", "HeLa"],
                ["Enzyme inhibition (biochemical)", "biochemical_ic50", "IC50", "TGTA", "3.4", "nM", ""],
                ["Kinase selectivity ratio", "selectivity", "ratio", "TGTA/TGTB", "120", "×", ""],
                ["Microsomal stability", "admet", "CLint", "", "18", "µL/min/mg", "HLM"],
                ["Solubility (kinetic)", "generic_numeric", "solubility", "", "62", "µM", "PBS pH7.4"],
                ["Plasma protein binding", "generic_numeric", "%bound", "", "98.5", "%", "human plasma"],
              ].map((r, i) => (
                <tr key={i} className="border-t border-border/60">
                  <td className="py-0.5 pr-2 font-sans text-inkFaint">{r[0]}</td>
                  {r.slice(1).map((c, j) => <td key={j} className="px-2 py-0.5">{c || <span className="text-inkFaint">—</span>}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-1 text-[10px] text-inkFaint">Use <code>generic_numeric</code> for any plain readout that doesn&apos;t fit a named family. Leave <code>target</code>/<code>system</code> blank when they don&apos;t apply.</div>
        </div>
        {err && <div className="mt-2 text-xs text-red-600">{err}</div>}
        <div className="mt-4 flex gap-2">
          <button onClick={submit} disabled={busy}
            className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
            {busy ? "Adding…" : "Add to database"}
          </button>
          <button onClick={onClose} className="rounded border border-borderStrong px-3 py-1.5 text-sm text-ink">Cancel</button>
        </div>
      </div>
    </div>
  );
}

export default function MoleculeDatabasePage() {
  const { programId } = useProgram();
  const { state, reload } = useAppState();
  const [showAdd, setShowAdd] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [groupBusy, setGroupBusy] = useState(false);
  const [groups, setGroups] = useState<MoleculeGroup[]>([]);
  const [viewGroup, setViewGroup] = useState<number | null>(null);

  useEffect(() => {
    fetchGroups(programId).then(setGroups).catch(() => setGroups([]));
  }, [programId, groupBusy]);   // refetch after a group is created (groupBusy flips)

  function toggleSel(id: number) {
    setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }
  async function makeGroup() {
    if (selected.size === 0) return;
    const name = window.prompt(`Name this group of ${selected.size} molecule(s):`);
    if (!name || !name.trim()) return;
    setGroupBusy(true);
    try { await createGroup(programId, name.trim(), [...selected]); setSelected(new Set());
      alert(`Group "${name.trim()}" created with ${selected.size} molecule(s).`); }
    catch (e) { alert(String(e)); }
    finally { setGroupBusy(false); }
  }
  const [scores, setScores] = useState<TppScores | null>(null);
  const [metrics, setMetrics] = useState<MetricDef[]>([]);
  const [metric, setMetric] = useState<string>("assay:biochemical_ic50:TGTA");
  const [selectedBin, setSelectedBin] = useState<number | null>(null);
  const [binMemberIds, setBinMemberIds] = useState<number[]>([]);
  const [showDefine, setShowDefine] = useState(false);
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [favOverride, setFavOverride] = useState<Map<number, boolean>>(new Map());
  const [search, setSearch] = useState("");
  const [aliasIds, setAliasIds] = useState<Set<number> | null>(null);

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

  const isFav = (mo: { id: number; favorite?: number | boolean }) =>
    favOverride.has(mo.id) ? favOverride.get(mo.id)! : !!mo.favorite;
  function toggleFav(id: number, current: boolean) {
    const next = !current;
    setFavOverride((m) => new Map(m).set(id, next));  // optimistic: flag flips instantly
    setFavorite(id, next).catch((e) => {              // persist in background, revert on failure
      setFavOverride((m) => new Map(m).set(id, current));
      alert(String(e));
    });
  }
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
  // per-molecule, per-metric TPP status (only for metrics that are TPP criteria)
  const paramStatusByMol = useMemo(() => {
    const m = new Map<number, Record<string, string>>();
    (scores?.molecules ?? []).forEach((mol) => {
      const byMetric: Record<string, string> = {};
      mol.params.forEach((p) => { byMetric[p.metric] = p.status; });
      m.set(mol.molecule_id, byMetric);
    });
    return m;
  }, [scores]);
  const DOT_STYLE: Record<string, string> = {
    pass: "bg-emerald-500", near: "bg-amber-400", fail: "bg-red-500",
  };
  // alias-aware search: match listed names client-side (instant) + fetch alias matches
  // from the registry search (matches molecule_aliases), union the two.
  useEffect(() => {
    const q = search.trim();
    if (!q) { setAliasIds(null); return; }
    const t = setTimeout(() => {
      fetch(`${API_BASE}/molecules/search?program_id=${programId}&q=${encodeURIComponent(q)}&limit=500`,
        { cache: "no-store" })
        .then((r) => r.json())
        .then((ms: { id: number }[]) => setAliasIds(new Set(ms.map((m) => m.id))))
        .catch(() => setAliasIds(new Set()));
    }, 250);
    return () => clearTimeout(t);
  }, [search, programId]);

  const rows = useMemo(() => {
    let mols = state?.molecules ?? [];
    if (viewGroup != null) {
      const g = groups.find((x) => x.id === viewGroup);
      const set = new Set(g?.molecule_ids ?? []);
      mols = mols.filter((mo) => set.has(mo.id));
    }
    if (favoritesOnly) mols = mols.filter((mo) => (favOverride.has(mo.id) ? favOverride.get(mo.id) : mo.favorite));
    if (selectedBin != null) {
      const set = new Set(binMemberIds);
      mols = mols.filter((mo) => set.has(mo.id));
    }
    const q = search.trim().toLowerCase();
    if (q) {
      mols = mols.filter((mo) =>
        mo.name.toLowerCase().includes(q) || (aliasIds?.has(mo.id) ?? false));
    }
    return mols;
  }, [state, selectedBin, binMemberIds, favoritesOnly, favOverride, search, aliasIds, viewGroup, groups]);

  // sortable columns: click a header to sort by name / a metric value / TPP status
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  function sortByCol(key: string) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  }
  const arrow = (k: string) => (sortKey === k ? (sortDir === "asc" ? " ↑" : " ↓") : "");
  const STATUS_ORDER: Record<string, number> = { pass: 0, near: 1, fail: 2, no_data: 3 };
  const sortedRows = useMemo(() => {
    if (!sortKey) return rows;
    const arr = [...rows];
    arr.sort((a, b) => {
      let av: number | string | null | undefined;
      let bv: number | string | null | undefined;
      if (sortKey === "name") { av = a.name.toLowerCase(); bv = b.name.toLowerCase(); }
      else if (sortKey === "status") {
        av = STATUS_ORDER[statusById.get(a.id) ?? "no_data"];
        bv = STATUS_ORDER[statusById.get(b.id) ?? "no_data"];
      } else {
        av = (valuesByMol.get(a.id) ?? {})[sortKey];
        bv = (valuesByMol.get(b.id) ?? {})[sortKey];
      }
      const an = av == null, bn = bv == null;
      if (an && bn) return 0;
      if (an) return 1;   // nulls always last
      if (bn) return -1;
      if (typeof av === "string" && typeof bv === "string")
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return arr;
  }, [rows, sortKey, sortDir, valuesByMol, statusById]);

  if (!state) return <p className="text-inkMuted">Loading…</p>;

  return (
    <div>
      {showAdd && <AddMoleculeModal programId={programId} onClose={() => setShowAdd(false)} onAdded={reload} />}
      <div className="mb-1 flex items-baseline justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">Molecule Database</h1>
          <button onClick={() => setShowAdd(true)}
            className="rounded border border-borderStrong px-2 py-1 text-xs text-ink hover:bg-panel2">
            + Add molecule
          </button>
        </div>
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
        <div className="mb-6 flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-ink">TPP:</span>
          {scores.molecules[0].params.map((p) => {
            const shown = columns.includes(p.metric);
            return (
              <button key={p.param_id} onClick={() => addColumn(p.metric)} disabled={shown}
                title={shown ? "Already a column" : "Add as a column in the table below"}
                className={`rounded border px-2 py-1 text-xs ${shown ? "border-border bg-panel opacity-60" : "border-border bg-panel hover:border-emerald-500/60 hover:bg-panel2"}`}>
                {p.label}: <span className="font-mono text-emerald-700">{p.operator} {fmt(p.threshold)}{p.units}</span>
                {!shown && <span className="ml-1 text-inkFaint">＋</span>}
              </button>
            );
          })}
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

        {showDefine && (
          <DefinePropertyForm
            aliases={metrics.filter((m) => m.kind !== "formula" && m.alias).map((m) => m.alias!)}
            onDone={(key) => { setShowDefine(false); loadMetrics(); setMetric(key); }}
          />
        )}

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
            : search.trim()
              ? `${rows.length} match${rows.length === 1 ? "" : "es"} for “${search.trim()}”`
              : viewGroup != null
                ? `Group “${groups.find((g) => g.id === viewGroup)?.name ?? ""}” · ${rows.length} molecules`
                : `${favoritesOnly ? "Favorites" : "All"} · ${rows.length} molecules`}
        </span>
        <label className="flex items-center gap-1 text-xs text-inkMuted">
          <input type="checkbox" checked={favoritesOnly} onChange={(e) => setFavoritesOnly(e.target.checked)} />
          ⚑ Favorites only
        </label>
        <label className="ml-auto flex items-center gap-1 text-xs text-inkMuted">Group:
          <select
            value={viewGroup ?? ""}
            onChange={(e) => setViewGroup(e.target.value ? Number(e.target.value) : null)}
            className="rounded border border-borderStrong bg-panel px-2 py-1 text-xs"
            title="Filter the database to a saved group"
          >
            <option value="">All molecules</option>
            {groups.map((g) => <option key={g.id} value={g.id}>{g.name} ({g.molecule_ids.length})</option>)}
          </select>
        </label>
        <span className="text-xs text-inkMuted">Default view:</span>
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

      {/* selection action bar — create a group from the checked molecules */}
      {selected.size > 0 && (
        <div className="mb-2 flex items-center gap-3 rounded-lg border border-sky-400/50 bg-sky-50 px-3 py-2 text-sm">
          <span className="font-medium text-sky-800">{selected.size} selected</span>
          <button onClick={makeGroup} disabled={groupBusy}
            className="rounded bg-sky-600 px-3 py-1 text-sm font-medium text-white disabled:opacity-50">
            {groupBusy ? "Creating…" : "＋ Create group"}
          </button>
          <button onClick={() => setSelected(new Set())} className="text-xs text-inkMuted hover:text-ink">clear</button>
        </div>
      )}

      <div className="relative overflow-x-auto rounded border border-border">
        <table className="w-full text-left text-sm">
          <thead className="bg-panel2 text-inkMuted">
            <tr>
              <th className="w-8 px-2 py-2">
                <input type="checkbox" title="Select all shown"
                  checked={rows.length > 0 && rows.every((mo) => selected.has(mo.id))}
                  onChange={(e) => setSelected(e.target.checked ? new Set(rows.map((mo) => mo.id)) : new Set())} />
              </th>
              <th className="px-3 py-2 font-medium">
                <button onClick={() => sortByCol("name")} className="hover:text-ink">Compound{arrow("name")}</button>
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="🔍 search name or alias…"
                  className="mt-1 block w-44 rounded border border-borderStrong bg-panel px-2 py-0.5 text-xs font-normal"
                />
              </th>
              {columns.map((key) => (
                <th key={key} className="group px-3 py-2 font-medium">
                  <span className="inline-flex items-center gap-1">
                    <button onClick={() => sortByCol(key)} className="hover:text-ink">{metricLabel(key)}{arrow(key)}</button>
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
              <th className="px-3 py-2 font-medium">
                <button onClick={() => sortByCol("status")} className="hover:text-ink">TPP status{arrow("status")}</button>
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((mo) => {
              const status = statusById.get(mo.id) ?? "no_data";
              const vals = valuesByMol.get(mo.id) ?? {};
              const pStatus = paramStatusByMol.get(mo.id) ?? {};
              return (
                <tr key={mo.id} className={`border-t border-border hover:bg-panel2/60 ${selected.has(mo.id) ? "bg-sky-50" : ""}`}>
                  <td className="px-2 py-2">
                    <input type="checkbox" checked={selected.has(mo.id)} onChange={() => toggleSel(mo.id)} />
                  </td>
                  <td className="px-3 py-2 font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      <button onClick={() => toggleFav(mo.id, isFav(mo))}
                        title={isFav(mo) ? "Unfavorite" : "Mark as favorite"}
                        className={`text-sm leading-none ${isFav(mo) ? "text-amber-500" : "text-inkFaint hover:text-amber-500"}`}>
                        {isFav(mo) ? "⚑" : "⚐"}
                      </button>
                      <Link href={`/molecules/${mo.id}`} className="hover:text-emerald-700">{mo.name}</Link>
                    </span>
                  </td>
                  {columns.map((key) => {
                    const v = vals[key];
                    const dot = DOT_STYLE[pStatus[key]];  // only set when this column is a TPP criterion with data
                    return (
                      <td key={key} className="px-3 py-2 font-mono">
                        <span className="inline-flex items-center gap-1.5">
                          {dot && <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`}
                            title={`TPP: ${pStatus[key] === "pass" ? "meets" : pStatus[key] === "near" ? "approaching" : "off"}`} />}
                          {v != null ? `${fmt(v)}${metricUnits(key)}` : "—"}
                        </span>
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
