"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { fetchMolecule, setFavorite, setCanonicalName, fetchMailEmail,
  updateMoleculeSmiles, addMoleculeAlias,
  type MoleculeAlias, type MailEmail } from "@/lib/api";
import { Structure3D } from "@/components/Structure3D";
import { AdmePanel } from "@/components/AdmePanel";
import type { Molecule } from "@/lib/types";

import { API_BASE } from "@/lib/apiBase";

type MolDetail = Molecule & { has_structure: boolean; program_id: string; aliases: MoleculeAlias[] };

export default function MoleculeDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const molId = Number(id);
  const [mol, setMol] = useState<MolDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [canonBusy, setCanonBusy] = useState<string | null>(null);
  // source email/doc modal for a data row
  const [srcDoc, setSrcDoc] = useState<MailEmail | null>(null);
  const [srcLoading, setSrcLoading] = useState(false);
  // edit SMILES (double-click) + add alias (+ button)
  const [editSmiles, setEditSmiles] = useState(false);
  const [smilesVal, setSmilesVal] = useState("");
  const [addAlias, setAddAlias] = useState(false);
  const [aliasVal, setAliasVal] = useState("");
  const [busy, setBusy] = useState(false);

  async function saveSmiles() {
    if (!mol) return;
    setBusy(true);
    try { await updateMoleculeSmiles(molId, smilesVal.trim(), mol.program_id); setEditSmiles(false); reload(); }
    catch (e) { alert(String(e)); }
    finally { setBusy(false); }
  }
  async function saveAlias() {
    if (!mol || !aliasVal.trim()) { setAddAlias(false); return; }
    setBusy(true);
    try { await addMoleculeAlias(molId, aliasVal.trim(), mol.program_id); setAliasVal(""); setAddAlias(false); reload(); }
    catch (e) { alert(String(e)); }
    finally { setBusy(false); }
  }

  function openSource(docId: number) {
    setSrcLoading(true); setSrcDoc(null);
    fetchMailEmail(docId).then(setSrcDoc).catch(() => setSrcDoc(null)).finally(() => setSrcLoading(false));
  }

  function reload() {
    fetchMolecule(molId).then(setMol).catch((e) => setError(String(e)));
  }
  useEffect(() => { reload(); }, [molId]);

  async function makeCanonical(alias: string) {
    if (!mol) return;
    const ok = window.confirm(
      `Rename this molecule from "${mol.name}" to "${alias}"?\n\n` +
      `"${alias}" becomes the canonical name everywhere in the system (dashboard, database, ` +
      `facts, quotes, registry); "${mol.name}" is kept as an alias. This cannot be auto-undone.`,
    );
    if (!ok) return;
    setCanonBusy(alias);
    try { await setCanonicalName(molId, alias, mol.program_id); reload(); }
    catch (e) { alert(String(e)); }
    finally { setCanonBusy(null); }
  }

  async function toggleFavorite() {
    if (!mol) return;
    const next = !mol.favorite;
    setMol({ ...mol, favorite: next ? 1 : 0 });
    try {
      await setFavorite(molId, next);
    } catch {
      setMol({ ...mol, favorite: mol.favorite }); // revert on failure
    }
  }

  if (error) return <p className="text-red-600">Error: {error}</p>;
  if (!mol) return <p className="text-inkMuted">Loading…</p>;

  // group assays by modality for the "all available data" view
  const byModality: Record<string, typeof mol.assays> = {};
  for (const a of mol.assays) (byModality[a.modality] ??= []).push(a);

  return (
    <div className="max-w-5xl">
      <Link href="/molecules" className="text-sm text-inkMuted hover:text-ink">
        ← Dashboard
      </Link>
      <div className="mb-4 mt-2 flex items-center gap-2">
        <h1 className="text-xl font-semibold">{mol.name}</h1>
        <button
          onClick={toggleFavorite}
          title={mol.favorite ? "Remove from favorites" : "Add to favorites"}
          aria-label="Toggle favorite"
          className={mol.favorite ? "text-amber-500" : "text-inkFaint hover:text-amber-500"}
        >
          <svg width="22" height="22" viewBox="0 0 24 24"
            fill={mol.favorite ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8">
            <path d="M6 3h12a1 1 0 0 1 1 1v16l-7-4-7 4V4a1 1 0 0 1 1-1z" />
          </svg>
        </button>
      </div>

      {/* names & aliases the system knows for this molecule; promote one to canonical */}
      <div className="mb-5 rounded border border-border bg-panel p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-inkMuted">
          Names &amp; aliases ({mol.aliases.length})
          <button onClick={() => { setAddAlias((v) => !v); setAliasVal(""); }}
            title="Add a name / alias"
            className="flex h-4 w-4 items-center justify-center rounded-full border border-borderStrong text-inkMuted hover:bg-panel2 hover:text-ink">+</button>
        </div>
        {addAlias && (
          <div className="mb-2 flex items-center gap-2">
            <input value={aliasVal} onChange={(e) => setAliasVal(e.target.value)} autoFocus
              placeholder="new name / alias (e.g. a CRO code)"
              onKeyDown={(e) => { if (e.key === "Enter") saveAlias(); if (e.key === "Escape") setAddAlias(false); }}
              className="w-72 rounded border border-border bg-panel2 px-2 py-1 text-xs text-ink normal-case" />
            <button onClick={saveAlias} disabled={busy || !aliasVal.trim()}
              className="rounded bg-sky-600 px-2 py-1 text-xs text-white disabled:opacity-50">Add</button>
          </div>
        )}
        {mol.aliases.length === 0 ? (
          <div className="text-xs text-inkMuted">No aliases recorded for this molecule.</div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {mol.aliases.map((a, i) => {
              const isCanon = a.alias === mol.name;
              return (
                <span key={i}
                  className="inline-flex items-center gap-1 rounded border border-border bg-panel2 px-2 py-1 text-xs">
                  <span className="text-ink">{a.alias}</span>
                  {a.vendor && <span className="text-inkFaint">({a.vendor})</span>}
                  {isCanon ? (
                    <span className="rounded bg-emerald-500/15 px-1 text-[10px] text-emerald-600">canonical</span>
                  ) : (
                    <button onClick={() => makeCanonical(a.alias)} disabled={canonBusy === a.alias}
                      className="rounded bg-sky-500/15 px-1 text-[10px] text-sky-600 hover:bg-sky-500/25 disabled:opacity-50"
                      title="Make this the canonical name (re-keys the whole system)">
                      {canonBusy === a.alias ? "…" : "make canonical"}
                    </button>
                  )}
                </span>
              );
            })}
          </div>
        )}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <Structure3D moleculeId={mol.id} />
          <a
            href={`${API_BASE}/molecule/${mol.id}/structure3d?download=1`}
            className="mt-2 inline-block rounded border border-borderStrong px-3 py-1.5 text-sm text-ink hover:bg-panel2"
          >
            ↓ Download structure (PDB)
          </a>
          <div className="mt-2 flex justify-center rounded border border-border bg-panel p-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`${API_BASE}/molecule/${mol.id}/structure2d`} alt="2D" className="h-40" />
          </div>
        </div>
        <div>
          <h2 className="mb-2 text-sm font-semibold text-ink">Predicted ADME</h2>
          <AdmePanel adme={mol.adme} />
          <div className="mt-4 rounded border border-border bg-panel p-3 text-xs text-inkMuted">
            <div className="mb-1 font-mono text-[11px] text-inkMuted">SMILES</div>
            {editSmiles ? (
              <div>
                <textarea value={smilesVal} onChange={(e) => setSmilesVal(e.target.value)} autoFocus rows={2}
                  onKeyDown={(e) => { if (e.key === "Escape") setEditSmiles(false); }}
                  className="w-full break-all rounded border border-sky-400 bg-white px-2 py-1 font-mono text-ink" />
                <div className="mt-1 flex gap-2">
                  <button onClick={saveSmiles} disabled={busy || !smilesVal.trim()}
                    className="rounded bg-sky-600 px-2 py-1 text-xs text-white disabled:opacity-50">Save SMILES</button>
                  <button onClick={() => setEditSmiles(false)} className="text-xs text-inkMuted hover:text-ink">cancel</button>
                </div>
              </div>
            ) : (
              <div className="cursor-text break-all font-mono text-ink hover:bg-sky-50"
                title="double-click to edit"
                onDoubleClick={() => { setSmilesVal(mol.smiles ?? ""); setEditSmiles(true); }}>
                {mol.smiles || "— (double-click to add SMILES)"}
              </div>
            )}
          </div>
          <a
            href={`${API_BASE}/molecule/${mol.id}/data.csv`}
            className="mt-4 inline-block rounded border border-borderStrong px-3 py-1.5 text-sm text-ink hover:bg-panel2"
          >
            ↓ Download raw data (CSV)
          </a>
        </div>
      </div>

      <h2 className="mb-3 mt-8 text-sm font-semibold text-ink">
        All available data ({mol.assays.length} measurements across {Object.keys(byModality).length} modalities)
      </h2>
      <div className="space-y-4">
        {Object.entries(byModality).map(([modality, assays]) => (
          <div key={modality} className="rounded border border-border">
            <div className="border-b border-border bg-panel px-3 py-2 text-xs font-medium uppercase text-inkMuted">
              {modality} ({assays.length})
            </div>
            <div className="max-h-64 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-inkMuted">
                  <tr>
                    <th className="px-3 py-1">Target</th>
                    <th className="px-3 py-1">Type</th>
                    <th className="px-3 py-1">Value</th>
                    <th className="px-3 py-1">Units</th>
                    <th className="px-3 py-1">Assay</th>
                    <th className="px-3 py-1">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {assays.slice(0, 40).map((a) => (
                    <tr key={a.id} className="border-t border-neutral-900">
                      <td className="px-3 py-1">{a.target ?? "—"}</td>
                      <td className="px-3 py-1">{a.standard_type ?? "—"}</td>
                      <td className="px-3 py-1 font-mono">{a.value ?? "—"}</td>
                      <td className="px-3 py-1">{a.units ?? "—"}</td>
                      <td className="px-3 py-1 text-inkMuted">
                        {a.assay_desc ? a.assay_desc.slice(0, 70) : "—"}
                      </td>
                      <td className="px-3 py-1">
                        {a.source_document_id ? (
                          <button onClick={() => openSource(a.source_document_id!)}
                            className="text-sky-500 hover:underline" title="Bring up the source email/doc">
                            ✉ email #{a.source_document_id}
                          </button>
                        ) : (
                          <span className="text-inkFaint">{a.source ?? "—"}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>

      {/* source email/doc modal — the correspondence a datapoint was derived from */}
      {(srcDoc || srcLoading) && (
        <div className="fixed inset-0 z-30 flex items-start justify-center overflow-y-auto bg-black/60 p-8"
          onClick={() => { setSrcDoc(null); setSrcLoading(false); }}>
          <div className="w-full max-w-3xl rounded-lg border border-border bg-panel p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}>
            {srcLoading && <div className="text-sm text-inkMuted">Loading…</div>}
            {srcDoc && (
              <>
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-panel2 px-1.5 py-0.5 font-mono text-xs text-inkMuted">#{srcDoc.id}</span>
                      <span className="truncate text-sm font-semibold text-ink">{srcDoc.subject || "(no subject)"}</span>
                    </div>
                    <div className="mt-0.5 text-xs text-inkMuted">
                      From {srcDoc.from || "?"} · {String(srcDoc.sent_at).slice(0, 10)} · {srcDoc.doc_type}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Link href={`/mailbox?doc=${srcDoc.id}`} className="text-xs text-sky-500 hover:underline">open in Inbox ↗</Link>
                    <button onClick={() => setSrcDoc(null)} className="text-inkMuted hover:text-ink">✕</button>
                  </div>
                </div>
                <div className="max-h-[60vh] overflow-y-auto whitespace-pre-wrap break-words rounded border border-border bg-panel2 p-3 text-xs text-ink">
                  {srcDoc.body || "(no body)"}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
