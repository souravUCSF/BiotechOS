"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchDataAnalysis, runDataAnalysis, approveDataAnalysis, setEmailIgnored,
  type DataAnalysis, type DataChart, type QCStep, type DepositionRow,
} from "@/lib/api";

// a deposition cell that turns into an input on double-click
function EditCell({ value, onCommit, align = "left", mono = false, className = "" }: {
  value: string | number | null | undefined; onCommit: (v: string) => void;
  align?: "left" | "right"; mono?: boolean; className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(String(value ?? ""));
  useEffect(() => { setV(String(value ?? "")); }, [value]);
  const base = `px-2 py-1 ${align === "right" ? "text-right" : ""} ${mono ? "font-mono" : ""} ${className}`;
  if (editing) {
    return (
      <td className={base}>
        <input autoFocus value={v} onChange={(e) => setV(e.target.value)}
          onBlur={() => { onCommit(v); setEditing(false); }}
          onKeyDown={(e) => { if (e.key === "Enter") { onCommit(v); setEditing(false); } if (e.key === "Escape") setEditing(false); }}
          className={`w-full rounded border border-sky-400 bg-white px-1 py-0.5 ${align === "right" ? "text-right" : ""} ${mono ? "font-mono" : ""}`} />
      </td>
    );
  }
  return (
    <td className={`${base} cursor-text hover:bg-sky-50`} onDoubleClick={() => setEditing(true)}
      title="double-click to edit">{value === "" || value == null ? "—" : String(value)}</td>
  );
}

const VERDICT: Record<string, string> = {
  pass: "bg-emerald-500/15 text-emerald-800", warn: "bg-amber-500/15 text-amber-300",
  fail: "bg-rose-500/15 text-rose-300",
};
const STEP_ICON: Record<string, string> = { ok: "✓", warn: "⚠", fail: "✕" };
const STEP_COLOR: Record<string, string> = {
  ok: "text-emerald-400", warn: "text-amber-400", fail: "text-rose-400",
};

// --- dose-response chart: raw points + re-fitted 4PL curve + reported vs re-derived IC50 ---
function DoseResponse({ c }: { c: DataChart }) {
  const pts = (c.points as number[][]) || [];
  const fit = (c.fit as { ic50: number; hill: number; top: number; bottom: number; r2: number }) || null;
  if (!pts.length || !fit) return null;
  const W = 360, H = 190, PAD = 34;
  const xs = pts.map((p) => p[0]).filter((x) => x > 0);
  const lo = Math.log10(Math.min(...xs)), hi = Math.log10(Math.max(...xs));
  const lx = (x: number) => PAD + ((Math.log10(x) - lo) / Math.max(hi - lo, 1e-6)) * (W - 2 * PAD);
  const ly = (y: number) => H - PAD - ((y - -10) / 120) * (H - 2 * PAD);
  const fourpl = (x: number) => fit.bottom + (fit.top - fit.bottom) / (1 + (x / fit.ic50) ** fit.hill);
  const curve: string[] = [];
  for (let i = 0; i <= 60; i++) {
    const x = 10 ** (lo + (hi - lo) * (i / 60));
    curve.push(`${lx(x).toFixed(1)},${ly(fourpl(x)).toFixed(1)}`);
  }
  const rep = c.reported_ic50 as number | null, red = c.rederived_ic50 as number | null;
  const flagged = !!c.flagged;
  return (
    <div>
      <div className="mb-1 text-xs text-inkMuted">
        Dose-response · {String(c.compound)} {c.target ? `(${c.target})` : ""} — R²={fit.r2}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#334155" />
        <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="#334155" />
        {red != null && red > 0 && (
          <line x1={lx(red)} y1={PAD} x2={lx(red)} y2={H - PAD}
            stroke={flagged ? "#fb7185" : "#38bdf8"} strokeDasharray="3 3" />
        )}
        {rep != null && rep > 0 && (
          <line x1={lx(rep)} y1={PAD} x2={lx(rep)} y2={H - PAD} stroke="#94a3b8" strokeDasharray="2 4" />
        )}
        <polyline fill="none" stroke={flagged ? "#fb7185" : "#38bdf8"} strokeWidth={1.5} points={curve.join(" ")} />
        {pts.map((p, i) => <circle key={i} cx={lx(p[0])} cy={ly(p[1])} r={2.5} fill="#e2e8f0" />)}
      </svg>
      <div className="flex gap-3 text-[11px]">
        <span className="text-inkMuted">▬ vendor {rep ?? "—"} {String(c.units || "")}</span>
        <span className={flagged ? "text-rose-300" : "text-sky-300"}>
          ▬ re-derived {red ?? "—"} {String(c.units || "")} {c.fold ? `(${c.fold}×)` : ""}
        </span>
      </div>
    </div>
  );
}

// --- ADME panel: each property with its interpretive band + flag ---
function AdmePanel({ c }: { c: DataChart }) {
  const items = (c.items as { property: string; value: number; units: string; band: string; flagged: boolean }[]) || [];
  return (
    <div>
      <div className="mb-1 text-xs text-inkMuted">ADME panel · {String(c.compound)}</div>
      <div className="space-y-1">
        {items.map((it, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-32 shrink-0 text-inkMuted">{it.property}</span>
            <span className="w-24 shrink-0 font-mono text-ink">{it.value} {it.units}</span>
            <span className={`rounded px-1.5 py-0.5 ${it.flagged ? "bg-amber-500/15 text-amber-300" : "bg-white/5 text-inkMuted"}`}>
              {it.band || "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Chart({ c }: { c: DataChart }) {
  if (c.kind === "dose_response") return <DoseResponse c={c} />;
  if (c.kind === "panel") return <AdmePanel c={c} />;
  return null;
}

function Running({ mode }: { mode: "text" | "native" }) {
  return (
    <div className="mb-2 flex items-center gap-2 rounded border border-sky-500/30 bg-sky-500/10 px-2 py-1.5 text-xs text-sky-300">
      <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-sky-400 border-t-transparent" />
      <span>Analyzing {mode === "native" ? "native attachment" : "anonymized text"}…
        {mode === "native" && " reading the file — this can take up to a minute."}</span>
    </div>
  );
}


export function DataQC({ docId, programId, onIgnored }: { docId: number; programId: string; onIgnored?: () => void }) {
  const [da, setDa] = useState<DataAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [dep, setDep] = useState<DepositionRow[]>([]);   // editable copy of the proposed deposition
  const [approveMsg, setApproveMsg] = useState("");

  const load = useCallback(() => {
    fetchDataAnalysis(docId, programId).then(setDa).catch(() => setDa(null));
  }, [docId, programId]);
  useEffect(load, [load]);
  // sync the editable deposition whenever a fresh analysis loads
  useEffect(() => { setDep(da?.analysis?.deposition ?? []); setApproveMsg(""); }, [da]);

  function editDep(i: number, field: keyof DepositionRow, raw: string) {
    setDep((rows) => rows.map((r, j) => {
      if (j !== i) return r;
      const v = field === "value" ? (raw.trim() === "" ? "" : (isNaN(Number(raw)) ? raw : Number(raw))) : raw;
      return { ...r, [field]: v };
    }));
  }

  // native-only: QC reads the real attachment (Sonnet + LibreOffice); no anonymized-text path
  const nativeFiles = (da?.attachments ?? []).filter((x) => x.native_available).map((x) => x.filename);
  const hasNative = nativeFiles.length > 0;

  async function run() {
    setBusy(true);
    try { setDa(await runDataAnalysis(docId, programId, "native", nativeFiles)); }
    finally { setBusy(false); }
  }
  async function ignore() {
    setBusy(true);
    try { await setEmailIgnored(docId, true, programId); onIgnored?.(); }
    finally { setBusy(false); }
  }
  async function approve() {
    if (!da?.id) return; setBusy(true);
    try {
      const r = await approveDataAnalysis(da.id, programId, dep);
      const parts = [`${r.deposited} measurement(s) deposited`];
      if (r.new_candidates > 0)
        parts.push(`${r.new_candidates} new compound(s) sent to the Registry — approve them there before they appear in the Molecule Database`);
      setApproveMsg(parts.join(" · "));
      load();
    } finally { setBusy(false); }
  }

  if (!da) return null;
  if (!da.found) {
    return (
      <div className="mb-4 rounded-lg border border-borderStrong bg-panel2 p-3">
        <div className="mb-2 text-sm font-semibold text-ink">🧪 Data QC</div>
        {busy ? <Running mode="native" /> : hasNative ? (
          <div className="mb-2 text-xs text-inkMuted">Reads the native attachment: {nativeFiles.join(", ")}</div>
        ) : (
          <div className="mb-2 text-xs text-inkMuted">No native attachment on this email to QC (needs a readable file / LibreOffice).</div>
        )}
        <button onClick={run} disabled={busy || !hasNative}
          className="mt-1 rounded bg-sky-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          {busy ? "Analyzing…" : "Analyze native attachment"}
        </button>
      </div>
    );
  }
  const a = da.analysis!;
  return (
    <div className="mb-4 rounded-lg border border-borderStrong bg-panel2 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-semibold text-ink">🧪 Data QC</span>
        <span className={`rounded px-2 py-0.5 text-xs ${VERDICT[da.verdict ?? "warn"]}`}>{da.verdict}</span>
        <span className="text-xs text-inkMuted">
          {a.counts?.datasets} dataset(s){a.counts?.discrepancies ? ` · ${a.counts.discrepancies} discrepancy` : ""}{a.counts?.warnings ? ` · ${a.counts.warnings} warning` : ""}
        </span>
        <span className="ml-auto text-xs text-inkFaint capitalize">{da.status}</span>
      </div>
      {busy && <Running mode="native" />}
      {a.vendor_summary && <div className="mb-2 text-xs text-inkMuted">Vendor says: “{a.vendor_summary}”</div>}

      {/* traceable QC steps */}
      <div className="mb-3 space-y-0.5">
        {a.qc_steps.map((s: QCStep, i) => (
          <div key={i} className="flex gap-2 text-xs">
            <span className={`shrink-0 ${STEP_COLOR[s.status]}`}>{STEP_ICON[s.status]}</span>
            <span className="text-inkMuted"><b className="text-ink">{s.step}:</b> {s.detail}</span>
          </div>
        ))}
      </div>

      {/* charts */}
      {a.charts.length > 0 && (
        <div className="mb-3 grid gap-3 sm:grid-cols-2">
          {a.charts.map((c, i) => (
            <div key={i} className="rounded border border-border bg-black/20 p-2"><Chart c={c} /></div>
          ))}
        </div>
      )}

      {/* proposed deposition — every extracted measurement; double-click a cell to edit */}
      {dep.length > 0 && (
        <div className="mb-3">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold text-inkMuted">
            Proposed deposition ({dep.length})
            <span className="font-normal text-inkFaint">· double-click any cell to edit before approving</span>
          </div>
          <div className="overflow-x-auto rounded border border-border text-xs">
            <table className="w-full text-left">
              <thead className="bg-panel text-inkMuted">
                <tr>
                  <th className="px-2 py-1">Compound</th>
                  <th className="px-2 py-1">Modality</th>
                  <th className="px-2 py-1">Target</th>
                  <th className="px-2 py-1">System</th>
                  <th className="px-2 py-1">Type</th>
                  <th className="px-2 py-1 text-right">Value</th>
                  <th className="px-2 py-1">Units</th>
                  <th className="px-2 py-1">Flags</th>
                </tr>
              </thead>
              <tbody>
                {dep.map((d, i) => (
                  <tr key={i} className="border-t border-border">
                    <EditCell value={d.molecule} mono className="text-ink" onCommit={(v) => editDep(i, "molecule", v)} />
                    <EditCell value={d.modality} className="text-inkMuted" onCommit={(v) => editDep(i, "modality", v)} />
                    <EditCell value={d.target} className="text-ink" onCommit={(v) => editDep(i, "target", v)} />
                    <td className="px-2 py-1 text-inkMuted">{d.system ? `${d.system_type ?? ""}: ${d.system}` : "—"}</td>
                    <EditCell value={d.standard_type} className="text-inkMuted" onCommit={(v) => editDep(i, "standard_type", v)} />
                    <EditCell value={d.value} align="right" mono className="text-ink" onCommit={(v) => editDep(i, "value", v)} />
                    <EditCell value={d.units} className="text-inkMuted" onCommit={(v) => editDep(i, "units", v)} />
                    <td className="px-2 py-1 text-amber-300" title={d.flags?.join(", ")}>{d.flags?.length ? "⚠" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {da.status === "pending" ? (
        <div>
          <div className="flex gap-2">
            <button onClick={run} disabled={busy || !hasNative}
              className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
              Re-analyze native</button>
            <button onClick={approve} disabled={busy}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
              Approve → deposit to DB
            </button>
            <button onClick={ignore} disabled={busy}
              title="Ignore for now — sets this data email aside; it drops out of the inbox counters"
              className="rounded border border-borderStrong px-3 py-1.5 text-sm text-ink">🚫 Ignore for now</button>
          </div>
        </div>
      ) : (
        <div>
          <div className="text-xs capitalize text-emerald-800">✓ {da.status}</div>
          {approveMsg && <div className="mt-1 rounded border border-amber-400/40 bg-amber-50/40 px-2 py-1 text-xs text-amber-900">{approveMsg}</div>}
        </div>
      )}
    </div>
  );
}
