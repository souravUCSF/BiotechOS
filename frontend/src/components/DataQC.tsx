"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchDataAnalysis, runDataAnalysis, approveDataAnalysis, dismissDataAnalysis,
  type DataAnalysis, type DataChart, type QCStep,
} from "@/lib/api";

const VERDICT: Record<string, string> = {
  pass: "bg-emerald-500/15 text-emerald-300", warn: "bg-amber-500/15 text-amber-300",
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

function SourcePicker({ da, mode, setMode, sel, setSel }: {
  da: DataAnalysis; mode: "text" | "native"; setMode: (m: "text" | "native") => void;
  sel: string[]; setSel: (s: string[]) => void;
}) {
  const atts = da.attachments ?? [];
  const anyNative = atts.some((a) => a.native_available);
  return (
    <div className="mb-2 rounded border border-border bg-black/20 p-2 text-xs">
      <div className="mb-1 font-semibold text-inkMuted">Read from</div>
      <label className="mr-3 inline-flex items-center gap-1 text-ink">
        <input type="radio" checked={mode === "text"} onChange={() => setMode("text")} /> Anonymized text
      </label>
      <label className={`inline-flex items-center gap-1 ${anyNative ? "text-ink" : "text-inkFaint"}`}>
        <input type="radio" checked={mode === "native"} disabled={!anyNative} onChange={() => setMode("native")} /> Native attachment
      </label>
      {mode === "native" && (
        <div className="mt-1 space-y-0.5">
          {atts.map((a) => (
            <label key={a.filename} className={`flex items-center gap-1.5 ${a.native_available ? "text-ink" : "text-inkFaint"}`}>
              <input type="checkbox" disabled={!a.native_available}
                checked={sel.includes(a.filename)}
                onChange={(e) => setSel(e.target.checked ? [...sel, a.filename] : sel.filter((f) => f !== a.filename))} />
              📎 {a.filename}
              {!a.native_available && <span className="text-[10px]">(no binary / needs LibreOffice)</span>}
            </label>
          ))}
          <div className="text-[10px] text-amber-400">⚠ sends the real file to Anthropic; extracted identities are re-anonymized before storing.</div>
        </div>
      )}
    </div>
  );
}

export function DataQC({ docId, programId }: { docId: number; programId: string }) {
  const [da, setDa] = useState<DataAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"text" | "native">("text");
  const [sel, setSel] = useState<string[]>([]);

  const load = useCallback(() => {
    fetchDataAnalysis(docId, programId).then(setDa).catch(() => setDa(null));
  }, [docId, programId]);
  useEffect(load, [load]);
  useEffect(() => { setMode("text"); setSel([]); }, [docId]);

  async function run() {
    setBusy(true);
    try { setDa(await runDataAnalysis(docId, programId, mode, mode === "native" ? sel : undefined)); }
    finally { setBusy(false); }
  }
  async function approve() { if (!da?.id) return; setBusy(true); try { await approveDataAnalysis(da.id, programId); load(); } finally { setBusy(false); } }
  async function dismiss() { if (!da?.id) return; setBusy(true); try { await dismissDataAnalysis(da.id, programId); load(); } finally { setBusy(false); } }

  if (!da) return null;
  if (!da.found) {
    return (
      <div className="mb-4 rounded-lg border border-borderStrong bg-panel2 p-3">
        <div className="mb-2 text-sm font-semibold text-ink">🧪 Data QC</div>
        {busy ? <Running mode={mode} /> : (
          <div className="mb-2 text-xs text-inkMuted">No analysis yet for this data email.</div>
        )}
        <SourcePicker da={da} mode={mode} setMode={setMode} sel={sel} setSel={setSel} />
        <button onClick={run} disabled={busy || (mode === "native" && sel.length === 0)}
          className="mt-1 rounded bg-sky-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          {busy ? "Analyzing…" : "Analyze data"}
        </button>
      </div>
    );
  }
  const a = da.analysis!;
  const rs = (a as { read_source?: string }).read_source || "anonymized text";
  const analyzedThisSource = mode === "native" ? rs.startsWith("native") : rs.startsWith("anonymized");
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
      {busy && <Running mode={mode} />}
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

      {/* proposed deposition */}
      {a.deposition.length > 0 && (
        <div className="mb-3">
          <div className="mb-1 text-xs font-semibold text-inkMuted">Proposed deposition ({a.deposition.length})</div>
          <div className="overflow-hidden rounded border border-border text-xs">
            <table className="w-full text-left">
              <thead className="bg-panel text-inkMuted">
                <tr><th className="px-2 py-1">Compound</th><th className="px-2 py-1">Assay</th>
                  <th className="px-2 py-1 text-right">Value</th><th className="px-2 py-1">Flags</th></tr>
              </thead>
              <tbody>
                {a.deposition.map((d, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="px-2 py-1 font-mono text-ink">{d.molecule}</td>
                    <td className="px-2 py-1 text-inkMuted">{d.standard_type}{d.target ? ` · ${d.target}` : ""}</td>
                    <td className="px-2 py-1 text-right font-mono text-ink">{d.value} {d.units}</td>
                    <td className="px-2 py-1 text-amber-300">{d.flags?.length ? "⚠" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {da.status === "pending" ? (
        <div>
          <SourcePicker da={da} mode={mode} setMode={setMode} sel={sel} setSel={setSel} />
          <div className="flex gap-2">
            <button onClick={run} disabled={busy || (mode === "native" && sel.length === 0)}
              className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
              {analyzedThisSource ? "Re-analyze" : "Analyze"} ({mode === "native" ? "native" : "text"})
            </button>
            <button onClick={approve} disabled={busy}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
              Approve → deposit to DB
            </button>
            <button onClick={dismiss} disabled={busy}
              className="rounded border border-borderStrong px-3 py-1.5 text-sm text-ink">Dismiss</button>
          </div>
        </div>
      ) : (
        <div className="text-xs text-emerald-400 capitalize">✓ {da.status}</div>
      )}
    </div>
  );
}
