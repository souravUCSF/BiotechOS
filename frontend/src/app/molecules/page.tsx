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
  type TppScores,
  type MetricDef,
  type MoleculeValues,
} from "@/lib/api";
import { Structure3D } from "@/components/Structure3D";
import { PropertyScatter } from "@/components/PropertyScatter";
import { MoleculeDashboardConfig, CARD_FIELD_OPTIONS } from "@/components/MoleculeDashboardConfig";
import { moleculeProperties } from "@/lib/properties";
import type { Molecule } from "@/lib/types";

import { API_BASE } from "@/lib/apiBase";
const fmt = (v: number | null) =>
  v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(1);

const DEFAULT_CARD_FIELDS = ["tgta_ic50", "selectivity", "cell_ic50", "QED"];

function AdvancingCard({ mol, status, cardFields }: { mol: Molecule; status: string; cardFields: string[] }) {
  const p = moleculeProperties(mol);
  const [flipped, setFlipped] = useState(false);

  const fieldOf = (key: string) => {
    const opt = CARD_FIELD_OPTIONS.find((f) => f.key === key);
    const v = (p as Record<string, number | null>)[key];
    return { label: opt?.label ?? key, value: v == null ? "—" : `${fmt(v)}${opt?.units ?? ""}` };
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
  const [cardFields, setCardFields] = useState<string[]>(DEFAULT_CARD_FIELDS);
  const cfKey = `moldash.cardFields.${programId}`;

  // scatter interactivity + configurable "All molecules" table
  const [brushIds, setBrushIds] = useState<number[]>([]);
  const [hoverId, setHoverId] = useState<number | null>(null);
  const [metricsCatalog, setMetricsCatalog] = useState<MetricDef[]>([]);
  const [tableColumns, setTableColumns] = useState<string[]>([
    "assay:biochemical_ic50:TGTA", "assay:selectivity:TGTA/TGTB",
    "assay:cellular_antiprolif:TGTA", "adme:MW", "adme:cLogP",
  ]);
  const [tableValues, setTableValues] = useState<MoleculeValues[]>([]);
  const [showTableColPicker, setShowTableColPicker] = useState(false);
  const tcKey = `moldash.tableCols.${programId}`;

  useEffect(() => {
    fetchTppScores(programId).then(setScores).catch(() => setScores(null));
    try {
      const saved = localStorage.getItem(cfKey);
      if (saved) setCardFields(JSON.parse(saved));
    } catch { /* ignore */ }
  }, [programId, cfKey]);

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

  useEffect(() => {
    fetchMoleculeValues(tableColumns, programId).then(setTableValues).catch(() => setTableValues([]));
  }, [tableColumns, programId]);

  const tableValsByMol = useMemo(() => {
    const m = new Map<number, Record<string, number | null>>();
    tableValues.forEach((r) => m.set(r.molecule_id, r.values));
    return m;
  }, [tableValues]);

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
              cardFields={cardFields}
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
            <button onClick={() => setBrushIds([])} className="text-xs text-inkMuted hover:text-ink">Clear ✕</button>
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
              <th className="px-3 py-2 font-medium">Compound</th>
              {tableColumns.map((key) => (
                <th key={key} className="group px-3 py-2 font-medium">
                  <span className="inline-flex items-center gap-1">
                    {metricLabel(key)}
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
            {state.molecules.map((mol) => {
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
