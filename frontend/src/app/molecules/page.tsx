"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useProgram } from "@/lib/ProgramContext";
import { useAppState } from "@/lib/useAppState";
import {
  fetchTppScores,
  fetchMetrics,
  fetchMoleculeValues,
  createGroup,
  type TppScores,
  type MetricDef,
  type MoleculeValues,
} from "@/lib/api";
import { Structure3D } from "@/components/Structure3D";
import { PropertyScatter } from "@/components/PropertyScatter";
import { MoleculeDashboardConfig } from "@/components/MoleculeDashboardConfig";
import type { Molecule } from "@/lib/types";

import { API_BASE } from "@/lib/apiBase";
const fmt = (v: number | null) =>
  v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(1);

// Retired metric keys still referenced by older TPP versions -> their current
// catalog equivalents, so TPP-derived card defaults stay valid.
const RETIRED_KEY_MAP: Record<string, string> = {
  "assay:selectivity:TGTA/TGTB": "formula:tgta_vs_tgtb_selectivity",
};
const remapKey = (k: string) => RETIRED_KEY_MAP[k] ?? k;

function AdvancingCard({ mol, status, cardFields, values, metrics }: {
  mol: Molecule; status: string; cardFields: string[];
  values: Record<string, number | null>; metrics: MetricDef[];
}) {
  const [flipped, setFlipped] = useState(false);

  const fieldOf = (key: string) => {
    const meta = metrics.find((m) => m.key === key);
    const v = values[key];
    const units = meta?.units ? ` ${meta.units}` : "";
    return { label: meta?.label ?? key, value: v == null ? "—" : `${fmt(v)}${units}` };
  };

  return (
    <div className="rounded border border-border bg-panel p-4">
      <div className="mb-2 flex items-center justify-between">
        <Link href={`/molecules/${mol.id}`} className="font-medium hover:text-emerald-700">
          {mol.name}
        </Link>
        <span
          className={`rounded px-2 py-0.5 text-xs ${
            status === "pass"
              ? "bg-emerald-600 text-white"
              : status === "near"
                ? "bg-amber-500 text-black"
                : "bg-panel2 text-inkMuted"
          }`}
        >
          {status === "pass" ? "MEETS TPP" : status.toUpperCase()}
        </span>
      </div>

      {/* flip card: 2D chemical structure (front) ⇄ 3D protein co-fold (back) */}
      <div style={{ perspective: "1200px" }}>
        <div
          className="relative h-72 transition-transform duration-500"
          style={{ transformStyle: "preserve-3d", transform: flipped ? "rotateY(180deg)" : "none" }}
        >
          {/* FRONT — chemical structure, prominent */}
          <div className="absolute inset-0 flex flex-col" style={{ backfaceVisibility: "hidden" }}>
            <button
              onClick={() => setFlipped(true)}
              title="Click to flip to the 3D protein co-fold"
              className="flex flex-1 items-center justify-center overflow-hidden rounded border border-border bg-white"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`${API_BASE}/molecule/${mol.id}/structure2d`} alt={`${mol.name} 2D`} className="max-h-full max-w-full" />
            </button>
            <div className="mt-1 text-center text-[10px] text-inkFaint">
              click structure → flip to 3D docking
            </div>
          </div>
          {/* BACK — Boltz-docked protein structure */}
          <div
            className="absolute inset-0 flex flex-col"
            style={{ backfaceVisibility: "hidden", transform: "rotateY(180deg)" }}
          >
            <button onClick={() => setFlipped(false)} className="flex-1 cursor-pointer" title="Click to flip back">
              <Structure3D moleculeId={mol.id} className="h-full" />
            </button>
            <div className="mt-1 text-center text-[10px] text-inkFaint">click to flip back to structure</div>
          </div>
        </div>
      </div>

      {/* configurable data fields */}
      {cardFields.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-ink">
          {cardFields.map((key) => {
            const f = fieldOf(key);
            return (
              <div key={key}>{f.label}: <span className="font-mono">{f.value}</span></div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function MoleculesPage() {
  const { programId } = useProgram();
  const router = useRouter();
  const { state } = useAppState();
  const [scores, setScores] = useState<TppScores | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [cardFields, setCardFields] = useState<string[]>([]);
  const [cardFieldsLoaded, setCardFieldsLoaded] = useState(false); // localStorage read done?
  const cfKey = `moldash.cardFields.${programId}`;

  // scatter interactivity + configurable "All molecules" table
  const [brushIds, setBrushIds] = useState<number[]>([]);
  const [hoverId, setHoverId] = useState<number | null>(null);
  const [metricsCatalog, setMetricsCatalog] = useState<MetricDef[]>([]);
  const [tableColumns, setTableColumns] = useState<string[]>([
    "assay:biochemical_ic50:KRAS", "assay:cellular_antiprolif:KRAS",
    "assay:selectivity:KRAS/WT", "adme:MW", "adme:cLogP",
  ]);
  const [tableValues, setTableValues] = useState<MoleculeValues[]>([]);
  const [showTableColPicker, setShowTableColPicker] = useState(false);
  const tcKey = `moldash.tableCols.${programId}`;
  const [groupBusy, setGroupBusy] = useState(false);
  const [groupDlg, setGroupDlg] = useState<{ name: string } | null>(null);
  const [tableSearch, setTableSearch] = useState("");
  const [tSortKey, setTSortKey] = useState<string | null>(null);
  const [tSortDir, setTSortDir] = useState<"asc" | "desc">("asc");
  function tSortBy(key: string) {
    if (tSortKey === key) setTSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setTSortKey(key); setTSortDir("asc"); }
  }
  const tArrow = (k: string) => (tSortKey === k ? (tSortDir === "asc" ? " ↑" : " ↓") : "");
  async function confirmGroup() {
    const name = groupDlg?.name.trim();
    if (!name) return;
    setGroupBusy(true);
    try {
      await createGroup(programId, name, brushIds);
      setGroupDlg(null);
    } catch (e) { alert(String(e)); } finally { setGroupBusy(false); }
  }

  useEffect(() => {
    fetchTppScores(programId).then(setScores).catch(() => setScores(null));
    setCardFieldsLoaded(false);
    try {
      const saved = localStorage.getItem(cfKey);
      if (saved) setCardFields(JSON.parse(saved));
    } catch { /* ignore */ }
    setCardFieldsLoaded(true);
  }, [programId, cfKey]);

  // Default card fields to every metric used by the current TPP (retired keys
  // remapped), pre-checking the TPP-associated properties. Only applies when the
  // user has no saved selection for this program.
  useEffect(() => {
    if (!cardFieldsLoaded || !state) return;
    if (localStorage.getItem(cfKey)) return; // user has an explicit selection
    const tppFields = Array.from(
      new Set((state.tpp_params ?? []).map((p) => remapKey(p.metric))),
    );
    if (tppFields.length) setCardFields(tppFields);
  }, [cardFieldsLoaded, state, cfKey]);

  function updateCardFields(fields: string[]) {
    setCardFields(fields);
    try { localStorage.setItem(cfKey, JSON.stringify(fields)); } catch { /* ignore */ }
  }

  useEffect(() => {
    fetchMetrics(programId).then(setMetricsCatalog).catch(() => setMetricsCatalog([]));
    try {
      const saved = localStorage.getItem(tcKey);
      if (saved) setTableColumns(JSON.parse(saved));
    } catch { /* ignore */ }
  }, [programId, tcKey]);

  // Drop any saved card fields that aren't real catalog keys (e.g. legacy
  // alias-based keys) so the card only ever shows currently-checked metrics.
  useEffect(() => {
    if (metricsCatalog.length === 0) return;
    const valid = new Set(metricsCatalog.map((m) => m.key));
    const cleaned = cardFields.filter((k) => valid.has(k));
    if (cleaned.length !== cardFields.length) updateCardFields(cleaned);
  }, [metricsCatalog]); // eslint-disable-line react-hooks/exhaustive-deps

  // Only render fields that are both checked AND known to the catalog.
  const validCardFields = useMemo(() => {
    const valid = new Set(metricsCatalog.map((m) => m.key));
    return cardFields.filter((k) => valid.has(k));
  }, [cardFields, metricsCatalog]);

  useEffect(() => {
    fetchMoleculeValues(tableColumns, programId).then(setTableValues).catch(() => setTableValues([]));
  }, [tableColumns, programId]);

  const tableValsByMol = useMemo(() => {
    const m = new Map<number, Record<string, number | null>>();
    tableValues.forEach((r) => m.set(r.molecule_id, r.values));
    return m;
  }, [tableValues]);

  // "All molecules" table: search by name + sort by any column
  const tableRows = useMemo(() => {
    let list = state?.molecules ?? [];
    const q = tableSearch.trim().toLowerCase();
    if (q) list = list.filter((mo) => mo.name.toLowerCase().includes(q));
    if (!tSortKey) return list;
    const arr = [...list];
    arr.sort((a, b) => {
      let av: number | string | null | undefined;
      let bv: number | string | null | undefined;
      if (tSortKey === "name") { av = a.name.toLowerCase(); bv = b.name.toLowerCase(); }
      else { av = (tableValsByMol.get(a.id) ?? {})[tSortKey]; bv = (tableValsByMol.get(b.id) ?? {})[tSortKey]; }
      const an = av == null, bn = bv == null;
      if (an && bn) return 0;
      if (an) return 1;
      if (bn) return -1;
      if (typeof av === "string" && typeof bv === "string")
        return tSortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return tSortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return arr;
  }, [state, tableSearch, tSortKey, tSortDir, tableValsByMol]);

  // values for the configurable card fields (resolved metric keys)
  const [cardValues, setCardValues] = useState<MoleculeValues[]>([]);
  useEffect(() => {
    if (cardFields.length === 0) { setCardValues([]); return; }
    fetchMoleculeValues(cardFields, programId).then(setCardValues).catch(() => setCardValues([]));
  }, [cardFields, programId]);
  const cardValsByMol = useMemo(() => {
    const m = new Map<number, Record<string, number | null>>();
    cardValues.forEach((r) => m.set(r.molecule_id, r.values));
    return m;
  }, [cardValues]);

  function setTableCols(cols: string[]) {
    setTableColumns(cols);
    try { localStorage.setItem(tcKey, JSON.stringify(cols)); } catch { /* ignore */ }
  }
  const metricLabel = (k: string) => metricsCatalog.find((m) => m.key === k)?.label ?? k;
  const metricUnits = (k: string) => metricsCatalog.find((m) => m.key === k)?.units ?? "";

  if (!state) return <p className="text-inkMuted">Loading…</p>;

  const statusById = new Map(
    (scores?.molecules ?? []).map((m) => [m.molecule_id, m.status]),
  );
  const favorites = state.molecules.filter((m) => m.favorite);
  const meets = new Set(
    (scores?.molecules ?? [])
      .filter((m) => m.status === "pass")
      .map((m) => m.molecule_id),
  );

  return (
    <div>
      {/* create-group dialog (system-styled, centered) */}
      {groupDlg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => !groupBusy && setGroupDlg(null)}>
          <div className="w-full max-w-sm rounded-lg border border-border bg-panel p-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 text-sm font-semibold text-ink">Create a group</div>
            <div className="mb-2 text-xs text-inkMuted">{brushIds.length} selected molecule(s)</div>
            <label className="mb-1 block text-xs text-inkMuted">Group name</label>
            <input autoFocus value={groupDlg.name} onChange={(e) => setGroupDlg({ name: e.target.value })}
              onKeyDown={(e) => { if (e.key === "Enter" && groupDlg.name.trim()) confirmGroup(); }}
              className="mb-3 w-full rounded border border-borderStrong bg-panel2 px-2 py-1.5 text-sm text-ink" />
            <div className="flex justify-end gap-2">
              <button onClick={() => setGroupDlg(null)} disabled={groupBusy} className="rounded border border-borderStrong px-3 py-1.5 text-sm text-ink hover:bg-panel2 disabled:opacity-50">Cancel</button>
              <button onClick={confirmGroup} disabled={groupBusy || !groupDlg.name.trim()} className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
                {groupBusy ? "Creating…" : "Create group"}
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="mb-1 flex items-center gap-2">
        <h1 className="text-xl font-semibold">Molecule Tracking Dashboard</h1>
        <button
          onClick={() => setShowConfig(true)}
          title="Dashboard configuration"
          className="text-inkMuted hover:text-ink"
          aria-label="Dashboard configuration"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
      </div>
      <p className="mb-6 text-sm text-inkMuted">
        {state.molecules.length} active molecules · {state.program.target} vs.{" "}
        {state.program.anti_target}
      </p>

      <h2 className="mb-3 text-sm font-semibold text-ink">
        Favorite molecules{favorites.length > 0 ? ` (${favorites.length})` : ""}
      </h2>
      {favorites.length === 0 ? (
        <div className="mb-8 rounded border border-dashed border-borderStrong p-6 text-center text-sm text-inkMuted">
          No favorites yet. Open a molecule and click the ⚑ bookmark next to its name to feature it here.
        </div>
      ) : (
        <div className="mb-8 grid gap-4 md:grid-cols-3">
          {favorites.map((mol) => (
            <AdvancingCard
              key={mol.id}
              mol={mol}
              status={statusById.get(mol.id) ?? "no_data"}
              cardFields={validCardFields}
              values={cardValsByMol.get(mol.id) ?? {}}
              metrics={metricsCatalog}
            />
          ))}
        </div>
      )}

      {showConfig && (
        <MoleculeDashboardConfig
          cardFields={cardFields}
          onCardFields={updateCardFields}
          onClose={() => setShowConfig(false)}
        />
      )}

      <h2 className="mb-3 text-sm font-semibold text-ink">
        Compare all molecules — any property vs. any property
      </h2>
      <div className="mb-4">
        <PropertyScatter
          molecules={state.molecules}
          highlight={meets}
          externalHoverId={hoverId}
          onHoverId={setHoverId}
          onBrush={setBrushIds}
          onSelect={(id) => router.push(`/molecules/${id}`)}
        />
      </div>

      {/* brushed selection */}
      {brushIds.length > 0 && (
        <div className="mb-8 rounded border border-blue-300 bg-blue-50 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium text-ink">Selected molecules ({brushIds.length})</span>
            <div className="flex items-center gap-3">
              <button onClick={() => setGroupDlg({ name: "Selection" })} disabled={groupBusy}
                className="rounded bg-sky-600 px-3 py-1 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-50">
                ＋ Create group
              </button>
              <button onClick={() => setBrushIds([])} className="text-xs text-inkMuted hover:text-ink">Clear ✕</button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {brushIds.map((id) => {
              const mol = state.molecules.find((m) => m.id === id);
              if (!mol) return null;
              return (
                <Link key={id} href={`/molecules/${id}`}
                  onMouseEnter={() => setHoverId(id)} onMouseLeave={() => setHoverId(null)}
                  className="flex items-center gap-2 rounded border border-border bg-panel px-2 py-1 hover:border-borderStrong">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={`${API_BASE}/molecule/${id}/structure2d`} alt="" className="h-10 w-14 object-contain" />
                  <span className="text-xs font-medium">{mol.name}</span>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      <h2 className="mb-3 text-sm font-semibold text-ink">All molecules</h2>
      <div className="relative overflow-x-auto rounded border border-border">
        <table className="w-full text-left text-sm">
          <thead className="bg-panel2 text-inkMuted">
            <tr>
              <th className="px-3 py-2 font-medium">
                <button onClick={() => tSortBy("name")} className="hover:text-ink">Compound{tArrow("name")}</button>
                <input
                  value={tableSearch}
                  onChange={(e) => setTableSearch(e.target.value)}
                  placeholder="🔍 search…"
                  className="mt-1 block w-40 rounded border border-borderStrong bg-panel px-2 py-0.5 text-xs font-normal"
                />
              </th>
              {tableColumns.map((key) => (
                <th key={key} className="group px-3 py-2 font-medium">
                  <span className="inline-flex items-center gap-1">
                    <button onClick={() => tSortBy(key)} className="hover:text-ink">{metricLabel(key)}{tArrow(key)}</button>
                    <button onClick={() => setTableCols(tableColumns.filter((c) => c !== key))}
                      title="Remove column"
                      className="text-inkFaint opacity-0 group-hover:opacity-100 hover:text-red-600">✕</button>
                  </span>
                </th>
              ))}
              <th className="px-3 py-2">
                <button onClick={() => setShowTableColPicker((s) => !s)}
                  className="rounded border border-borderStrong px-2 py-0.5 text-xs text-ink hover:bg-panel">
                  + Column
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {tableRows.map((mol) => {
              const vals = tableValsByMol.get(mol.id) ?? {};
              return (
                <tr key={mol.id}
                  onMouseEnter={() => setHoverId(mol.id)} onMouseLeave={() => setHoverId(null)}
                  className={`border-t border-border ${hoverId === mol.id ? "bg-amber-50" : "hover:bg-panel2/60"}`}>
                  <td className="px-3 py-2 font-medium">
                    <Link href={`/molecules/${mol.id}`} className="hover:text-emerald-700">
                      {mol.name}
                    </Link>
                  </td>
                  {tableColumns.map((key) => {
                    const v = vals[key];
                    return <td key={key} className="px-3 py-2 font-mono">{v != null ? `${fmt(v)}${metricUnits(key)}` : "—"}</td>;
                  })}
                  <td />
                </tr>
              );
            })}
          </tbody>
        </table>
        {showTableColPicker && (
          <div className="absolute right-2 top-10 z-20 max-h-80 w-72 overflow-y-auto rounded border border-borderStrong bg-panel p-2 shadow-lg">
            <div className="mb-1 px-1 text-xs font-medium text-inkMuted">Add a column</div>
            {metricsCatalog.filter((m) => !tableColumns.includes(m.key)).map((m) => (
              <button key={m.key} onClick={() => { setTableCols([...tableColumns, m.key]); setShowTableColPicker(false); }}
                className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-panel2">
                <span>{m.label}</span><span className="text-xs text-inkFaint">{m.count ?? 0}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
