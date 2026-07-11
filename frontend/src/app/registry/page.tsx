"use client";

// Compound registry — confirm the identity of provisional (unconfirmed) molecules.
// Fetches /registry/* directly (not via lib/api.ts) to stay isolated from concurrent edits.
import { useCallback, useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { API_BASE } from "@/lib/apiBase";

type Sug = { molecule_id: number; name: string; reason: string };
type Alias = { alias: string; alias_type: string | null; vendor: string | null; verified: number };
type Doc = { id: number; subject: string; email_from: string; sent_at: string };
type Candidate = {
  id: number; name: string; smiles: string | null; structure_status: string; has_structure: boolean;
  bucket: "needs_link" | "needs_new"; vendors: string[]; aliases: Alias[];
  documents: Doc[]; assay_count: number; suggestions: Sug[];
};

// structure thumbnail that quietly disappears if the molecule has no renderable structure
function Thumb({ src, size = 44 }: { src: string; size?: number }) {
  const [ok, setOk] = useState(true);
  if (!ok) return <div style={{ width: size, height: size }} className="shrink-0 rounded border border-border bg-panel2" />;
  return (
    <img src={src} width={size} height={size} alt="" onError={() => setOk(false)}
      className="shrink-0 rounded border border-border bg-white" />
  );
}

// merge target autocomplete: search existing molecules by name/alias, pick, then Merge
function MergePicker({ programId, disabled, onMerge, preset }:
  { programId: string; disabled: boolean; onMerge: (id: number) => void; preset?: { id: number; name: string } }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<{ id: number; name: string; has_structure: number }[]>([]);
  const [sel, setSel] = useState<{ id: number; name: string } | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (preset) { setSel(preset); setQ(preset.name); } }, [preset]);
  useEffect(() => {
    if (!q.trim()) { setRes([]); return; }
    const t = setTimeout(() => {
      fetch(`${API_BASE}/molecules/search?program_id=${programId}&q=${encodeURIComponent(q.trim())}`)
        .then((r) => r.json()).then((d) => setRes(d.results || [])).catch(() => setRes([]));
    }, 200);
    return () => clearTimeout(t);
  }, [q, programId]);
  return (
    <div className="relative flex items-center gap-1">
      <input value={q} onChange={(e) => { setQ(e.target.value); setSel(null); setOpen(true); }}
        onFocus={() => setOpen(true)} placeholder="merge into…"
        className="w-40 rounded border border-border bg-panel2 px-2 py-1 text-xs text-ink" />
      {open && res.length > 0 && !sel && (
        <div className="absolute left-0 top-full z-20 mt-1 max-h-48 w-60 overflow-y-auto rounded border border-border bg-panel shadow-lg">
          {res.map((m) => (
            <button key={m.id} onClick={() => { setSel({ id: m.id, name: m.name }); setQ(m.name); setOpen(false); }}
              className="block w-full px-2 py-1 text-left text-xs text-ink hover:bg-panel2">
              {m.name} <span className="text-inkMuted">#{m.id}{m.has_structure ? " · struct" : ""}</span>
            </button>
          ))}
        </div>
      )}
      <button disabled={disabled || !sel} onClick={() => sel && onMerge(sel.id)}
        className="rounded border border-sky-500/40 px-2 py-1 text-xs text-sky-400 disabled:opacity-40">Merge</button>
    </div>
  );
}

export default function RegistryPage() {
  const { programId } = useProgram();
  const [items, setItems] = useState<Candidate[]>([]);
  const [smiles, setSmiles] = useState<Record<number, string>>({});
  const [err, setErr] = useState<Record<number, string>>({});
  const [mergePreset, setMergePreset] = useState<Record<number, { id: number; name: string } | undefined>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [total, setTotal] = useState(0);            // molecules remaining to register
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [detail, setDetail] = useState<any | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // server-side search: default = structure-less orphans; a query also surfaces
  // detected molecules that already have a structure (never the ChEMBL seed set).
  useEffect(() => {
    setLoading(true);
    const t = setTimeout(() => {
      const url = `${API_BASE}/registry/candidates?program_id=${programId}`
        + (q.trim() ? `&q=${encodeURIComponent(q.trim())}` : "");
      fetch(url, { cache: "no-store" })
        .then((r) => r.json()).then((d) => { setItems(d.candidates || []); setTotal(d.total ?? 0); })
        .catch(() => setItems([])).finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [programId, q]);

  const drop = (id: number) => { setItems((xs) => xs.filter((x) => x.id !== id)); setTotal((t) => Math.max(0, t - 1)); };
  function openDetail(id: number) {
    setDetail(null); setDetailLoading(true);
    fetch(`${API_BASE}/registry/${id}/detail?program_id=${programId}`, { cache: "no-store" })
      .then((r) => r.json()).then(setDetail).catch(() => setDetail(null)).finally(() => setDetailLoading(false));
  }
  async function post(url: string, body?: unknown) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined });
  }
  async function register(c: Candidate) {
    const val = (smiles[c.id] || "").trim();
    if (!val) { setErr((e) => ({ ...e, [c.id]: "A valid SMILES or a unique descriptor is required." })); return; }
    setBusy(c.id); setErr((e) => ({ ...e, [c.id]: "" }));
    try {
      const r = await post(`${API_BASE}/registry/${c.id}/confirm`, { program_id: programId, value: val });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { setErr((e) => ({ ...e, [c.id]: j.detail || "Could not register." })); return; }
      if (j.duplicate) {   // not unique → pre-populate the merge with the match
        setErr((e) => ({ ...e, [c.id]: j.message }));
        setMergePreset((m) => ({ ...m, [c.id]: { id: j.duplicate.molecule_id, name: j.duplicate.name } }));
        return;
      }
      drop(c.id);
    } finally { setBusy(null); }
  }
  async function merge(c: Candidate, targetId: number) {
    setBusy(c.id);
    try {
      const r = await post(`${API_BASE}/registry/${c.id}/merge`, { program_id: programId, target_id: targetId, vendor: c.vendors[0] ?? null });
      if (r.ok) drop(c.id); else { const j = await r.json().catch(() => ({})); setErr((e) => ({ ...e, [c.id]: j.detail || "Could not merge." })); }
    } finally { setBusy(null); }
  }
  async function dismiss(c: Candidate) {
    setBusy(c.id);
    try { await post(`${API_BASE}/registry/${c.id}/dismiss?program_id=${programId}`); drop(c.id); }
    finally { setBusy(null); }
  }

  const needsLink = items.filter((c) => c.bucket === "needs_link");
  const needsNew = items.filter((c) => c.bucket === "needs_new");

  const card = (c: Candidate) => {
    const typed = smiles[c.id]?.trim();
    const aka = c.aliases.filter((a) => a.alias !== c.name).map((a) => a.alias);
    return (
      <div key={c.id} className="rounded border border-border bg-panel p-3">
        <div className="flex items-start gap-3">
          {/* structure thumbnail: live preview of typed SMILES, else the stored structure */}
          {typed
            ? <Thumb src={`${API_BASE}/structure/svg?smiles=${encodeURIComponent(typed)}`} />
            : c.has_structure
              ? <Thumb src={`${API_BASE}/molecule/${c.id}/structure2d`} />
              : <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded border border-dashed border-border text-[9px] text-inkMuted">no struct</div>}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-ink">{c.name}</span>
              <span className={`rounded px-1.5 py-0.5 text-[10px] ${c.structure_status === "known"
                ? "bg-emerald-500/15 text-emerald-400" : "bg-amber-500/15 text-amber-500"}`}>
                {c.structure_status === "known" ? "structure known" : "structure pending"}
              </span>
              <button onClick={() => openDetail(c.id)}
                className="text-xs text-sky-400 underline-offset-2 hover:underline"
                title="see the data + correspondence behind this molecule">
                · {c.assay_count} assays · what is this?
              </button>
            </div>
            {(aka.length > 0 || c.vendors.length > 0) && (
              <div className="mt-0.5 text-xs text-inkMuted">
                {aka.length > 0 && <>aka <span className="text-ink">{aka.join(", ")}</span></>}
                {aka.length > 0 && c.vendors.length > 0 && " · "}
                {c.vendors.length > 0 && <>used by {c.vendors.join(", ")}</>}
              </div>
            )}

            {/* actions */}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input value={smiles[c.id] ?? ""} placeholder="SMILES, sequence, or descriptor *" required
                onChange={(e) => { setSmiles((s) => ({ ...s, [c.id]: e.target.value })); setErr((x) => ({ ...x, [c.id]: "" })); }}
                className={`w-60 rounded border bg-panel2 px-2 py-1 text-xs font-mono text-ink ${
                  err[c.id] ? "border-red-500" : "border-border"}`} />
              <button disabled={busy === c.id} onClick={() => register(c)}
                className="rounded bg-emerald-700 px-2 py-1 text-xs text-white disabled:opacity-50">Register as new</button>
              <span className="text-inkMuted">|</span>
              {c.suggestions.map((s) => (
                <button key={s.molecule_id} disabled={busy === c.id} onClick={() => merge(c, s.molecule_id)}
                  title={s.reason}
                  className="flex items-center gap-1 rounded border border-sky-500/40 px-2 py-1 text-xs text-sky-400 disabled:opacity-50">
                  <Thumb src={`${API_BASE}/molecule/${s.molecule_id}/structure2d`} size={20} />
                  Merge → {s.name}
                </button>
              ))}
              <MergePicker programId={programId} disabled={busy === c.id} preset={mergePreset[c.id]} onMerge={(id) => merge(c, id)} />
              <button disabled={busy === c.id} onClick={() => dismiss(c)}
                className="ml-auto rounded border border-border px-2 py-1 text-xs text-inkMuted disabled:opacity-50">Dismiss</button>
            </div>
            {err[c.id] && <div className="mt-1 text-xs text-red-500">{err[c.id]}</div>}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="p-6">
      <div className="mb-1 flex items-center gap-3">
        <h1 className="text-lg font-semibold text-ink">Compound registry</h1>
        <span title="molecules remaining to register"
          className="inline-flex min-w-6 items-center justify-center rounded-full bg-red-600 px-2 py-0.5 text-sm font-bold text-white">
          {total}
        </span>
        <span className="text-sm text-inkMuted">to register</span>
      </div>
      <p className="mb-3 max-w-2xl text-sm text-inkMuted">
        Orphan molecules seen in comms, held until you confirm what they are. Ones that look like a
        variant/alias of an existing molecule are grouped first for quick linking; the rest are new.
      </p>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name / vendor / alias…"
        className="mb-4 w-72 rounded border border-border bg-panel px-3 py-1.5 text-sm text-ink" />

      {loading && <div className="text-sm text-inkMuted">Loading…</div>}
      {!loading && items.length === 0 && (
        <div className="text-sm text-inkMuted">No molecules{q.trim() ? " match your search" : " to sort"}.</div>
      )}

      {needsLink.length > 0 && (
        <section className="mb-6">
          <h2 className="mb-2 text-sm font-semibold text-sky-400">
            Likely a link to an existing molecule <span className="text-inkMuted">({needsLink.length})</span>
          </h2>
          <div className="flex flex-col gap-3">{needsLink.map(card)}</div>
        </section>
      )}
      {needsNew.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-ink">
            New — needs registration <span className="text-inkMuted">({needsNew.length})</span>
          </h2>
          <div className="flex flex-col gap-3">{needsNew.map(card)}</div>
        </section>
      )}

      {/* drill-down: what data + correspondence a candidate came from */}
      {(detail || detailLoading) && (
        <div className="fixed inset-0 z-30 flex items-start justify-center overflow-y-auto bg-black/40 p-8"
          onClick={() => setDetail(null)}>
          <div className="w-full max-w-3xl rounded bg-panel p-5" onClick={(e) => e.stopPropagation()}>
            {detailLoading && <div className="text-sm text-inkMuted">Loading…</div>}
            {detail && (
              <>
                <div className="mb-1 flex items-center justify-between">
                  <div className="text-base font-semibold text-ink">{detail.molecule?.name}</div>
                  <button onClick={() => setDetail(null)} className="text-inkMuted hover:text-ink">✕</button>
                </div>
                {detail.aliases?.length > 0 && (
                  <div className="mb-3 text-xs text-inkMuted">
                    aliases: {detail.aliases.map((a: {alias: string; vendor: string | null}) =>
                      a.alias + (a.vendor ? ` (${a.vendor})` : "")).join(", ")}
                  </div>
                )}

                <div className="mb-1 text-sm font-semibold text-ink">Assay data ({detail.assays?.length ?? 0})</div>
                <div className="mb-4 max-h-52 overflow-y-auto rounded border border-border">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-panel2 text-inkMuted">
                      <tr><th className="px-2 py-1 text-left">Modality</th><th className="px-2 text-left">Target</th>
                        <th className="px-2 text-left">System</th>
                        <th className="px-2 text-left">Type</th><th className="px-2 text-right">Value</th>
                        <th className="px-2 text-left">Units</th><th className="px-2 text-left">Source</th></tr>
                    </thead>
                    <tbody>
                      {(detail.assays ?? []).map((a: Record<string, unknown>, i: number) => (
                        <tr key={i} className="border-t border-border/60">
                          <td className="px-2 py-0.5">{String(a.modality ?? "")}</td>
                          <td className="px-2">{String(a.target ?? "")}</td>
                          <td className="px-2 text-inkMuted">{a.system ? `${a.system_type ?? ""}: ${a.system}` : ""}</td>
                          <td className="px-2">{String(a.standard_type ?? "")}</td>
                          <td className="px-2 text-right font-mono">{String(a.value ?? "")}</td>
                          <td className="px-2">{String(a.units ?? "")}</td>
                          <td className="px-2 text-inkMuted">{String(a.source ?? "")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {(() => {
                  const docs = (detail.documents ?? []) as Record<string, unknown>[];
                  const hasAssays = (detail.assays?.length ?? 0) > 0;
                  const withData = docs.filter((d) => d.has_data);
                  const rest = docs.filter((d) => !d.has_data);
                  const card = (d: Record<string, unknown>) => (
                    <div key={String(d.id)} className="rounded border border-border p-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-ink">{String(d.subject ?? "(no subject)")}</span>
                        <span className="text-inkMuted">{String(d.sent_at ?? "").slice(0, 10)} · {String(d.doc_type ?? "")}</span>
                      </div>
                      <div className="text-inkMuted">from {String(d.email_from ?? "")}</div>
                      {d.snippet ? <div className="mt-1 text-inkMuted">…{String(d.snippet)}</div> : null}
                    </div>
                  );
                  if (docs.length === 0)
                    return <div className="text-xs text-inkMuted">No matching emails found for this code.</div>;
                  if (!hasAssays)
                    return (<>
                      <div className="mb-1 text-sm font-semibold text-ink">Correspondence ({docs.length})</div>
                      <div className="flex flex-col gap-2">{docs.map(card)}</div>
                    </>);
                  return (<>
                    {withData.length > 0 && (<>
                      <div className="mb-1 text-sm font-semibold text-ink">Correspondence with data ({withData.length})</div>
                      <div className="mb-4 flex flex-col gap-2">{withData.map(card)}</div>
                    </>)}
                    {rest.length > 0 && (<>
                      <div className="mb-1 text-sm font-semibold text-inkMuted">Other correspondence ({rest.length})</div>
                      <div className="flex flex-col gap-2">{rest.map(card)}</div>
                    </>)}
                  </>);
                })()}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
