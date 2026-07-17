"use client";

import { useCallback, useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { API_BASE } from "@/lib/apiBase";
import { MolViewer } from "@/components/Structure3D";
import {
  fetchGroups, fetchModelingSubject, runContactMap, ligplotUrl,
  estimateGenerate, startGenerate, pollGenerate, fetchCachedGenerate, fetchSeedData, exportGenerate, adoptGenerate,
  fetchFoldBacklog, runFoldBacklog,
  type MoleculeGroup, type ModelingMember, type ContactMap, type FoldBacklog,
} from "@/lib/api";

const INTERACTIONS = ["Hydrophobic", "HBDonor", "HBAcceptor", "PiStacking", "Cationic", "Anionic", "VdWContact"];
const DEFAULT_INTERACTIONS = ["Hydrophobic", "HBDonor", "HBAcceptor", "PiStacking", "Cationic", "Anionic"];
const INTER_COLOR: Record<string, string> = {
  Hydrophobic: "bg-amber-400", HBDonor: "bg-sky-500", HBAcceptor: "bg-sky-700",
  PiStacking: "bg-violet-500", Cationic: "bg-rose-500", Anionic: "bg-emerald-600", VdWContact: "bg-slate-400",
};

// ---------------- Fold-backlog banner ----------------
function FoldBacklogBanner({ programId }: { programId: string }) {
  const [bl, setBl] = useState<FoldBacklog | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>("");
  const load = useCallback(() => { fetchFoldBacklog(programId).then(setBl).catch(() => setBl(null)); }, [programId]);
  useEffect(() => { load(); }, [load]);
  if (!bl || bl.count === 0) return null;
  const run = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await runFoldBacklog(programId);
      setMsg(r.enqueued ? `Started co-folding ${r.enqueued} molecule(s) — spaced to respect rate limits; refresh over time.` : `Not started (${r.reason}).`);
      setTimeout(load, 1500);
    } catch { setMsg("Failed to start."); } finally { setBusy(false); }
  };
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <span className="font-medium text-ink">{bl.count} molecule(s)</span>
          <span className="text-inkMuted"> in this program have a SMILES/sequence but no co-fold.</span>
          {bl.total_usd && <span className="text-inkMuted"> Est. Boltz cost to fold all: <span className="font-medium text-ink">${num(bl.total_usd)}</span> (${num(bl.per_cofold_usd)}/co-fold).</span>}
        </div>
        <button onClick={run} disabled={busy || !bl.boltz_available}
          className="shrink-0 rounded bg-emerald-700 px-3 py-1 font-medium text-white hover:bg-emerald-600 disabled:opacity-40">
          {busy ? "Starting…" : "Fold backlog"}
        </button>
      </div>
      {!bl.boltz_available && <div className="mt-1 text-xs text-inkFaint">Boltz API key not set — folding unavailable.</div>}
      {msg && <div className="mt-1 text-xs text-inkMuted">{msg}</div>}
      <div className="mt-1 text-xs text-inkFaint">A background sweep also co-folds the backlog automatically over time.</div>
    </div>
  );
}

// ---------------- Contact-map widget ----------------
function ContactMapWidget({ programId, members }: { programId: string; members: ModelingMember[] }) {
  const cofolded = members.filter((m) => m.has_cofold);
  const [inters, setInters] = useState<string[]>(DEFAULT_INTERACTIONS);
  const [cm, setCm] = useState<ContactMap | null>(null);
  const [busy, setBusy] = useState(false);
  const [ligplot, setLigplot] = useState<{ id: number; name: string } | null>(null);

  async function run() {
    if (cofolded.length === 0) return;
    setBusy(true);
    try { setCm(await runContactMap(programId, cofolded.map((m) => m.id), inters)); }
    finally { setBusy(false); }
  }
  function toggle(i: string) { setInters((s) => s.includes(i) ? s.filter((x) => x !== i) : [...s, i]); }

  // auto-show the contact map on page load / when the co-folded set changes
  const cofoldKey = cofolded.map((m) => m.id).join(",");
  useEffect(() => {
    if (cofolded.length) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cofoldKey, programId]);

  return (
    <div className="rounded-lg border border-border bg-panel p-4">
      <div className="mb-2 text-sm font-semibold text-ink">🔬 Interaction contact map (ProLIF)</div>
      <div className="mb-2 text-xs text-inkMuted">
        Protein–ligand interactions from each molecule co-folded in the same receptor.
        {members.length - cofolded.length > 0 && ` ${members.length - cofolded.length} member(s) have no co-fold and are excluded.`}
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {INTERACTIONS.map((i) => (
          <label key={i} className="flex items-center gap-1 text-xs text-inkMuted">
            <input type="checkbox" checked={inters.includes(i)} onChange={() => toggle(i)} /> {i}
          </label>
        ))}
        <button onClick={run} disabled={busy || cofolded.length === 0}
          className="ml-auto rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
          {busy ? "Running…" : `Run (${cofolded.length} co-folded)`}
        </button>
      </div>

      {cm && cm.molecules.length > 0 && (
        <div className="overflow-x-auto rounded border border-border">
          <table className="text-xs">
            <thead className="bg-panel2 text-inkMuted">
              <tr>
                <th className="sticky left-0 bg-panel2 px-2 py-1 text-left">Molecule</th>
                {cm.residues.map((r) => (
                  <th key={r} className="px-1 py-1 text-center font-normal" title={`${r} · in ${cm.frequency.find((f) => f.residue === r)?.count ?? 0} molecule(s)`}>
                    <span className="inline-block -rotate-45 origin-center whitespace-nowrap">{r.replace(".A", "")}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cm.molecules.map((m) => (
                <tr key={m.id} className="border-t border-border hover:bg-panel2/50">
                  <td className="sticky left-0 bg-panel px-2 py-1 font-medium text-ink">
                    <button onClick={() => setLigplot({ id: m.id, name: m.name })} className="text-sky-500 hover:underline"
                      title="Open the 2D LigPlot interaction diagram">{m.name}</button>
                  </td>
                  {cm.residues.map((r) => {
                    const types = m.interactions[r] || [];
                    return (
                      <td key={r} className="px-1 py-1 text-center" title={types.join(", ")}>
                        {types.length > 0 && (
                          <span className={`inline-block h-3 w-3 rounded-sm ${INTER_COLOR[types[0]] ?? "bg-slate-400"}`} />
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cm && (
        <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-inkMuted">
          {DEFAULT_INTERACTIONS.map((i) => (
            <span key={i} className="flex items-center gap-1"><span className={`inline-block h-3 w-3 rounded-sm ${INTER_COLOR[i]}`} /> {i}</span>
          ))}
          <span className="ml-auto">click a molecule name → 2D LigPlot diagram</span>
        </div>
      )}

      {ligplot && (
        <div className="fixed inset-0 z-30 flex items-start justify-center overflow-y-auto bg-black/50 p-6" onClick={() => setLigplot(null)}>
          <div className="w-full max-w-4xl rounded-lg border border-border bg-panel p-3 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between">
              <div className="text-sm font-semibold text-ink">LigPlot — {ligplot.name}</div>
              <button onClick={() => setLigplot(null)} className="text-inkMuted hover:text-ink">✕</button>
            </div>
            <iframe src={ligplotUrl(ligplot.id)} className="h-[70vh] w-full rounded border border-border bg-white" title="LigPlot" />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------- Boltz-generate widget ----------------
const num = (v: unknown): string => {
  const x = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(x) ? x.toFixed(2) : "—";
};

function GenerateWidget({ programId, members }: { programId: string; members: ModelingMember[] }) {
  const [n, setN] = useState(10);
  const [cost, setCost] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [mols, setMols] = useState<Record<string, unknown>[]>([]);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"thumbnails" | "list">("thumbnails");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [spin3d, setSpin3d] = useState<{ url: string; smiles: string; format: string } | null>(null);
  const [exporting, setExporting] = useState(false);
  const [addDlg, setAddDlg] = useState<{ id: string; smiles: string; name: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [seeds, setSeeds] = useState<Record<string, unknown>[]>([]);
  const [sortKey, setSortKey] = useState<string>("binding_confidence");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // load the seed molecules' data whenever the subject changes, so they appear in the list
  useEffect(() => {
    fetchSeedData(programId, members.filter((m) => m.has_cofold).map((m) => m.id))
      .then(setSeeds).catch(() => setSeeds([]));
  }, [programId, members]);

  useEffect(() => {
    const t = setTimeout(() => {
      estimateGenerate(programId, n).then((r) => setCost(r.usd)).catch(() => setCost(null));
    }, 400);
    return () => clearTimeout(t);
  }, [programId, n]);

  useEffect(() => {
    if (!jobId || status === "done" || status === "error") return;
    const iv = setInterval(async () => {
      try {
        const r = await pollGenerate(jobId);
        setStatus(r.status);
        if (r.status === "done") { setMols(r.molecules); clearInterval(iv); }
        if (r.status === "error") { setStatus("error: " + (r.error || "")); clearInterval(iv); }
      } catch { /* keep polling */ }
    }, 4000);
    return () => clearInterval(iv);
  }, [jobId, status]);

  async function generate() {
    setBusy(true); setMols([]); setStatus("running");
    try { const r = await startGenerate(programId, members.map((m) => m.id), n); setJobId(r.job_id); }
    catch (e) { setStatus("error: " + String(e)); }
    finally { setBusy(false); }
  }
  async function loadCached(silent = false) {
    setBusy(true); setStatus(""); setSelected(new Set());
    try {
      const r = await fetchCachedGenerate();
      setMols(r.molecules); setJobId(r.job_id);
      setStatus(r.molecules.length ? "done" : "");
      if (!r.molecules.length && !silent) alert("No cached generate results on disk yet — run Generate once.");
    } catch (e) { if (!silent) alert(String(e)); } finally { setBusy(false); }
  }
  // auto-load the last generate results on page load (silent: no alert if empty)
  useEffect(() => {
    loadCached(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const molId = (m: Record<string, unknown>): string => String(m.id ?? "");
  const bindConf = (m: Record<string, unknown>): number => Number(m.binding_confidence ?? m.affinity ?? 0) || 0;
  const sortVal = (m: Record<string, unknown>, key: string): number => {
    if (key === "binding_confidence") return bindConf(m);
    const adme = (m.adme || {}) as Record<string, unknown>;
    if (["lipophilicity", "permeability"].includes(key)) return Number(adme[key]) || 0;
    return Number(m[key]) || 0;
  };
  function sortBy(key: string) {
    if (sortKey === key) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortKey(key); setSortDir("desc"); }
  }
  function open3d(m: Record<string, unknown>) {
    const smi = String(m.smiles || m.SMILES || "");
    if (m.seed) setSpin3d({ url: `${API_BASE}/molecule/${m.molecule_id}/structure3d?program_id=${programId}`, smiles: smi, format: "pdb" });
    else setSpin3d({ url: `${API_BASE}/modeling/generate/${jobId}/structure/${molId(m)}`, smiles: smi, format: "cif" });
  }
  // seed molecules shown alongside generated candidates, sorted together (seeds highlighted)
  const shown = [...seeds, ...mols].sort((a, b) => {
    const d = sortVal(a, sortKey) - sortVal(b, sortKey);
    return sortDir === "desc" ? -d : d;
  });
  function toggle(id: string) {
    setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }
  function toggleAll() {
    setSelected((s) => s.size === mols.length ? new Set() : new Set(mols.map(molId)));
  }
  async function exportSelected() {
    if (!jobId) return;
    setExporting(true);
    try { await exportGenerate(jobId, selected.size ? [...selected] : mols.map(molId)); }
    catch (e) { alert(String(e)); } finally { setExporting(false); }
  }
  function openAdd(id: string, smiles: string) {
    setAddDlg({ id, smiles, name: "GEN-" + Math.random().toString(36).slice(2, 7).toUpperCase() });
  }
  async function confirmAdd() {
    if (!addDlg || !jobId) return;
    setAdding(true);
    try {
      const r = await adoptGenerate(jobId, addDlg.id, addDlg.name.trim(), programId);
      setAddDlg(null);
      alert(`Added “${addDlg.name.trim()}” (molecule #${r.molecule_id}) to the Molecule Database` +
        (r.has_structure ? " with its co-fold structure + ADME." : " (ADME attached; no structure)."));
    } catch (e) { alert(String(e)); } finally { setAdding(false); }
  }

  return (
    <div className="rounded-lg border border-border bg-panel p-4">
      <div className="mb-2 text-sm font-semibold text-ink">🧬 Boltz generate — novel molecules for the pocket</div>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-inkMuted">
        <label className="flex items-center gap-1"># to generate
          <input type="number" min={10} max={1000000} step={10} value={n}
            onChange={(e) => setN(Math.min(1000000, Math.max(10, Number(e.target.value) || 10)))}
            className="w-24 rounded border border-borderStrong bg-panel2 px-2 py-1" /></label>
        <span className="rounded bg-panel2 px-2 py-1">est. cost: {cost != null ? `$${num(cost)}` : "…"}</span>
        <span>seeded by {members.length} molecule(s)</span>
        <button onClick={() => loadCached()} disabled={busy}
          className="ml-auto rounded border border-borderStrong px-3 py-1.5 text-sm font-medium text-ink hover:bg-panel2 disabled:opacity-50"
          title="Load the last completed run from disk — no new Boltz job / no cost">
          Load last results
        </button>
        <button onClick={generate} disabled={busy || members.length === 0}
          className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
          {busy ? "Starting…" : "Generate (new job)"}
        </button>
      </div>
      {status && status !== "done" && <div className="mb-2 text-xs text-inkMuted">Boltz job: {status}… (this can take several minutes)</div>}

      {mols.length > 0 && (
        <>
          {/* results toolbar: view toggle + export */}
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            <div className="inline-flex overflow-hidden rounded border border-borderStrong">
              {(["thumbnails", "list"] as const).map((v) => (
                <button key={v} onClick={() => setView(v)}
                  className={`px-2.5 py-1 ${view === v ? "bg-emerald-600 text-white" : "bg-panel2 text-inkMuted hover:bg-panel"}`}>
                  {v === "thumbnails" ? "Thumbnails" : "List"}
                </button>
              ))}
            </div>
            <span className="text-inkMuted">{mols.length} candidate(s){selected.size ? ` · ${selected.size} selected` : ""}</span>
            <button onClick={exportSelected} disabled={exporting}
              className="ml-auto rounded border border-borderStrong px-3 py-1 font-medium text-ink hover:bg-panel2 disabled:opacity-50"
              title="Download a ZIP: Excel of SMILES + data, plus co-folded structures (CIF)">
              {exporting ? "Exporting…" : `⬇ Export ${selected.size ? "selected" : "all"} (.zip)`}
            </button>
          </div>

          {view === "thumbnails" ? (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {shown.map((m, i) => {
                const smi = String(m.smiles || m.SMILES || "");
                const id = molId(m);
                const seed = !!m.seed;
                return (
                  <div key={i} className={`rounded border p-2 text-xs ${seed ? "border-amber-500/60 bg-amber-500/5" : "border-border"}`}>
                    {seed && <div className="mb-1 inline-block rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-medium text-amber-700">SEED · {String(m.name ?? "")}</div>}
                    <button onClick={() => open3d(m)}
                      className="flex w-full justify-center rounded bg-white p-1 hover:ring-2 hover:ring-emerald-500"
                      title="Click to view the co-folded 3D structure (spins)">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={`${API_BASE}/structure/svg?smiles=${encodeURIComponent(smi)}`} alt="" className="h-24" />
                    </button>
                    <div className="mt-1 break-all font-mono text-[10px] text-inkMuted">{smi.slice(0, 40)}</div>
                    <div className="mt-1 flex items-center justify-between">
                      <span className="text-inkMuted">ipTM {num(m.iptm)} · binding {num(bindConf(m))}</span>
                      {seed
                        ? <span className="text-[10px] text-inkFaint">in database</span>
                        : <button onClick={() => openAdd(id, smi)} className="rounded bg-sky-600 px-1.5 py-0.5 text-[10px] text-white">＋ add</button>}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="overflow-x-auto rounded border border-border">
              <table className="w-full text-left text-xs">
                <thead className="bg-panel2 text-inkMuted">
                  <tr>
                    <th className="p-2"><input type="checkbox" checked={selected.size === mols.length && mols.length > 0} onChange={toggleAll} /></th>
                    <th className="p-2">Structure</th><th className="p-2">SMILES</th>
                    {([["iptm", "ipTM"], ["binding_confidence", "binding conf."], ["ptm", "pTM"],
                      ["complex_plddt", "plDDT"], ["lipophilicity", "logP"], ["permeability", "perm"]] as const).map(([key, lbl]) => (
                      <th key={key} className="cursor-pointer select-none p-2 hover:text-ink" onClick={() => sortBy(key)}>
                        {lbl}{sortKey === key ? (sortDir === "desc" ? " ↓" : " ↑") : ""}
                      </th>
                    ))}
                    <th className="p-2">sol</th><th className="p-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((m, i) => {
                    const smi = String(m.smiles || m.SMILES || "");
                    const id = molId(m);
                    const seed = !!m.seed;
                    const adme = (m.adme || {}) as Record<string, unknown>;
                    return (
                      <tr key={i} className={`border-t border-border ${seed ? "bg-amber-500/5" : "hover:bg-panel2/50"}`}>
                        <td className="p-2">{seed ? <span title="seed molecule (already in database)" className="text-amber-600">★</span> : <input type="checkbox" checked={selected.has(id)} onChange={() => toggle(id)} />}</td>
                        <td className="p-2">
                          <button onClick={() => open3d(m)} className="rounded bg-white p-0.5 hover:ring-2 hover:ring-emerald-500" title="View co-folded 3D structure">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src={`${API_BASE}/structure/svg?smiles=${encodeURIComponent(smi)}`} alt="" className="h-12 w-12 object-contain" />
                          </button>
                        </td>
                        <td className="max-w-[220px] break-all p-2 font-mono text-[10px] text-inkMuted">
                          {seed && <span className="mr-1 rounded bg-amber-500/20 px-1 py-0.5 text-[9px] font-medium text-amber-700">SEED {String(m.name ?? "")}</span>}
                          {smi}
                        </td>
                        <td className="p-2">{num(m.iptm)}</td>
                        <td className="p-2">{num(bindConf(m))}</td>
                        <td className="p-2">{num(m.ptm)}</td>
                        <td className="p-2">{num(m.complex_plddt)}</td>
                        <td className="p-2">{num(adme.lipophilicity)}</td>
                        <td className="p-2">{num(adme.permeability)}</td>
                        <td className="p-2">{String(adme.solubility ?? "—").replace("-confidence", "")}</td>
                        <td className="p-2">{seed ? <span className="text-[10px] text-inkFaint">in DB</span> : <button onClick={() => openAdd(id, smi)} className="rounded bg-sky-600 px-1.5 py-0.5 text-[10px] text-white">＋ add</button>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* co-folded 3D structure modal (spins) */}
      {spin3d && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setSpin3d(null)}>
          <div className="w-full max-w-2xl rounded-lg border border-border bg-panel p-4" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between">
              <div className="text-sm font-semibold text-ink">Co-folded structure</div>
              <button onClick={() => setSpin3d(null)} className="text-inkMuted hover:text-ink">✕</button>
            </div>
            <MolViewer url={spin3d.url} className="h-96" spin defaultFormat={spin3d.format} />
            <div className="mt-2 break-all font-mono text-[10px] text-inkMuted">{spin3d.smiles}</div>
          </div>
        </div>
      )}

      {/* add-to-database dialog (system-styled) */}
      {addDlg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => !adding && setAddDlg(null)}>
          <div className="w-full max-w-md rounded-lg border border-border bg-panel p-4" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 text-sm font-semibold text-ink">Add generated molecule to the database</div>
            <div className="mb-2 flex justify-center rounded bg-white p-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`${API_BASE}/structure/svg?smiles=${encodeURIComponent(addDlg.smiles)}`} alt="" className="h-28" />
            </div>
            <label className="mb-1 block text-xs text-inkMuted">Name</label>
            <input autoFocus value={addDlg.name} onChange={(e) => setAddDlg({ ...addDlg, name: e.target.value })}
              onKeyDown={(e) => { if (e.key === "Enter" && addDlg.name.trim()) confirmAdd(); }}
              className="mb-3 w-full rounded border border-borderStrong bg-panel2 px-2 py-1.5 text-sm text-ink" />
            <div className="mb-3 rounded bg-panel2 p-2 text-[11px] text-inkMuted">
              Its Boltz co-fold structure, ipTM/binding metrics, and ADME will be attached — no new folding job.
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setAddDlg(null)} disabled={adding} className="rounded border border-borderStrong px-3 py-1.5 text-sm text-ink hover:bg-panel2 disabled:opacity-50">Cancel</button>
              <button onClick={confirmAdd} disabled={adding || !addDlg.name.trim()} className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
                {adding ? "Adding…" : "Add to database"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------- Page ----------------
export default function ModelingPage() {
  const { programId } = useProgram();
  const [groups, setGroups] = useState<MoleculeGroup[]>([]);
  const [mode, setMode] = useState<"group" | "molecule">("group");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [molHit, setMolHit] = useState<{ id: number; name: string } | null>(null);
  const [members, setMembers] = useState<ModelingMember[]>([]);
  const [hits, setHits] = useState<{ id: number; name: string }[]>([]);

  useEffect(() => { fetchGroups(programId).then((g) => { setGroups(g); if (g[0]) setGroupId(g[0].id); }).catch(() => setGroups([])); }, [programId]);

  const loadSubject = useCallback(() => {
    const sel = mode === "group" ? (groupId != null ? { group_id: groupId } : null)
      : (molHit ? { molecule_id: molHit.id } : null);
    if (!sel) { setMembers([]); return; }
    fetchModelingSubject(programId, sel).then((r) => setMembers(r.members)).catch(() => setMembers([]));
  }, [programId, mode, groupId, molHit]);
  useEffect(() => { loadSubject(); }, [loadSubject]);

  useEffect(() => {
    if (mode !== "molecule" || !q.trim()) { setHits([]); return; }
    const t = setTimeout(() => {
      fetch(`${API_BASE}/molecules/search?program_id=${programId}&q=${encodeURIComponent(q.trim())}`)
        .then((r) => r.json()).then(setHits).catch(() => setHits([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q, programId, mode]);

  return (
    <div className="max-w-5xl space-y-4">
      <h1 className="text-xl font-semibold">Modeling</h1>

      <FoldBacklogBanner programId={programId} />

      {/* unit selector */}
      <div className="rounded-lg border border-border bg-panel p-3">
        <div className="mb-2 flex items-center gap-3 text-sm">
          <span className="text-inkMuted">Basic unit:</span>
          {(["group", "molecule"] as const).map((m) => (
            <label key={m} className="flex items-center gap-1">
              <input type="radio" checked={mode === m} onChange={() => setMode(m)} /> {m === "group" ? "Group" : "Single molecule"}
            </label>
          ))}
          {mode === "group" ? (
            <select value={groupId ?? ""} onChange={(e) => setGroupId(e.target.value ? Number(e.target.value) : null)}
              className="rounded border border-borderStrong bg-panel2 px-2 py-1 text-sm">
              <option value="">Select a group…</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name} ({g.molecule_ids.length})</option>)}
            </select>
          ) : (
            <div className="relative">
              <input value={molHit ? molHit.name : q} onChange={(e) => { setMolHit(null); setQ(e.target.value); }}
                placeholder="search a molecule…" className="w-56 rounded border border-borderStrong bg-panel2 px-2 py-1 text-sm" />
              {hits.length > 0 && !molHit && (
                <div className="absolute z-10 mt-1 max-h-48 w-56 overflow-y-auto rounded border border-border bg-panel shadow-lg">
                  {hits.map((h) => (
                    <button key={h.id} onClick={() => { setMolHit(h); setHits([]); }}
                      className="block w-full px-2 py-1 text-left text-sm text-ink hover:bg-panel2">{h.name}</button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        {members.length > 0 && (
          <div className="flex flex-wrap gap-1.5 text-xs">
            {members.map((m) => (
              <span key={m.id} className={`rounded border px-1.5 py-0.5 ${m.has_cofold ? "border-emerald-500/40 text-ink" : "border-border text-inkFaint"}`}>
                {m.name}{!m.has_cofold && " · needs co-fold"}
              </span>
            ))}
          </div>
        )}
      </div>

      {members.length > 0 ? (
        <>
          <ContactMapWidget programId={programId} members={members} />
          <GenerateWidget programId={programId} members={members} />
        </>
      ) : (
        <div className="rounded-lg border border-border bg-panel p-6 text-sm text-inkMuted">
          Pick a group or a single molecule above to run modeling widgets.
        </div>
      )}
    </div>
  );
}
