"use client";

import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import {
  fetchEntities, fetchEntity,
  type EntityListItem, type EntityProfile, type EntityEdge,
} from "@/lib/api";

const TYPES = ["", "vendor", "person", "cell_line", "assay", "program", "molecule"];

function edgeRow(e: EntityEdge, dir: "→" | "←", onOpen: (id: number) => void) {
  const superseded = e.status !== "current";
  return (
    <div className={`flex items-center gap-2 text-sm ${superseded ? "opacity-40 line-through" : ""}`}>
      <span className="text-inkMuted w-36 shrink-0">{e.predicate}</span>
      <span className="text-inkMuted">{dir}</span>
      <button className="text-emerald-700 hover:underline" onClick={() => onOpen(e.other_id)}>
        {e.other_name}
      </button>
      <span className="text-xs text-inkMuted">({e.other_type})</span>
    </div>
  );
}

export default function EntitiesPage() {
  const { programId } = useProgram();
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [list, setList] = useState<EntityListItem[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [prof, setProf] = useState<EntityProfile | null>(null);

  useEffect(() => {
    fetchEntities(programId, type || undefined, q || undefined)
      .then(setList).catch(() => setList([]));
  }, [programId, type, q]);

  useEffect(() => {
    if (sel == null) { setProf(null); return; }
    fetchEntity(sel, programId).then(setProf).catch(() => setProf(null));
  }, [sel, programId]);

  return (
    <div className="grid grid-cols-[320px_1fr] gap-6 p-6">
      {/* left: entity list */}
      <div className="flex flex-col gap-3">
        <h1 className="text-lg font-semibold text-ink">Knowledge Graph</h1>
        <input
          className="rounded border border-border bg-panel px-3 py-1.5 text-sm"
          placeholder="Search entities…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="flex flex-wrap gap-1">
          {TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setType(t)}
              className={`rounded px-2 py-0.5 text-xs ${
                type === t ? "bg-ink text-panel" : "bg-panel text-inkMuted border border-border"
              }`}
            >{t || "all"}</button>
          ))}
        </div>
        <div className="flex flex-col divide-y divide-border overflow-y-auto rounded border border-border">
          {list.map((e) => (
            <button
              key={e.id}
              onClick={() => setSel(e.id)}
              className={`flex items-center justify-between px-3 py-2 text-left text-sm hover:bg-panel ${
                sel === e.id ? "bg-panel font-semibold" : ""
              }`}
            >
              <span className="truncate">{e.display_name}</span>
              <span className="ml-2 shrink-0 text-xs text-inkMuted">{e.entity_type} · {e.edge_count}</span>
            </button>
          ))}
          {list.length === 0 && <div className="px-3 py-6 text-sm text-inkMuted">No entities.</div>}
        </div>
      </div>

      {/* right: profile */}
      <div className="min-w-0">
        {!prof && <div className="text-sm text-inkMuted">Select an entity to see everything known about it.</div>}
        {prof && (
          <div className="flex flex-col gap-5">
            <div>
              <div className="text-xl font-semibold text-ink">{prof.entity.display_name}</div>
              <div className="text-sm text-inkMuted">{prof.entity.entity_type}</div>
              {prof.aliases.length > 1 && (
                <div className="mt-1 text-xs text-inkMuted">
                  aka {prof.aliases.map((a) => a.alias).join(", ")}
                </div>
              )}
            </div>

            {prof.molecule && (
              <section>
                <h2 className="mb-2 text-sm font-semibold text-ink">Molecule</h2>
                {prof.molecule.smiles && (
                  <div className="mb-1 break-all font-mono text-xs text-inkMuted">
                    SMILES: {prof.molecule.smiles}
                  </div>
                )}
                {prof.molecule.inchi_key && (
                  <div className="font-mono text-xs text-inkMuted">InChIKey: {prof.molecule.inchi_key}</div>
                )}
              </section>
            )}

            {prof.assays && prof.assays.length > 0 && (
              <section>
                <h2 className="mb-2 text-sm font-semibold text-ink">
                  Assay results <span className="text-inkMuted">({prof.assays.length} groups)</span>
                </h2>
                <div className="overflow-x-auto">
                  <table className="text-sm">
                    <thead>
                      <tr className="text-left text-xs text-inkMuted">
                        <th className="pr-4 py-1">Modality</th>
                        <th className="pr-4">Target</th>
                        <th className="pr-4">Type</th>
                        <th className="pr-4">Cell line</th>
                        <th className="pr-4 text-right">n</th>
                        <th className="pr-4 text-right">Avg</th>
                        <th className="pr-4 text-right">Range</th>
                        <th>Units</th>
                      </tr>
                    </thead>
                    <tbody>
                      {prof.assays.map((a, i) => (
                        <tr key={i} className="border-t border-border">
                          <td className="pr-4 py-1">{a.modality}</td>
                          <td className="pr-4">{a.target ?? "—"}</td>
                          <td className="pr-4">{a.standard_type ?? "—"}</td>
                          <td className="pr-4">{a.cell_line ?? "—"}</td>
                          <td className="pr-4 text-right">{a.n}</td>
                          <td className="pr-4 text-right">{a.avg_value != null ? a.avg_value.toPrecision(3) : "—"}</td>
                          <td className="pr-4 text-right text-xs text-inkMuted">
                            {a.min_value != null && a.max_value != null
                              ? `${a.min_value.toPrecision(2)}–${a.max_value.toPrecision(2)}` : "—"}
                          </td>
                          <td>{a.units ?? ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {(prof.edges_out.length > 0 || prof.edges_in.length > 0) && (
              <section>
                <h2 className="mb-2 text-sm font-semibold text-ink">Relationships</h2>
                <div className="flex flex-col gap-1">
                  {prof.edges_out.map((e, i) => <div key={`o${i}`}>{edgeRow(e, "→", setSel)}</div>)}
                  {prof.edges_in.map((e, i) => <div key={`i${i}`}>{edgeRow(e, "←", setSel)}</div>)}
                </div>
              </section>
            )}

            {prof.facts.length > 0 && (
              <section>
                <h2 className="mb-2 text-sm font-semibold text-ink">Facts (current + superseded)</h2>
                <table className="text-sm">
                  <tbody>
                    {prof.facts.map((f, i) => (
                      <tr key={i} className={f.status !== "current" ? "opacity-40" : ""}>
                        <td className="py-0.5 pr-4 text-inkMuted">{f.predicate}</td>
                        <td className="py-0.5 pr-4">{f.value}</td>
                        <td className="py-0.5 text-xs text-inkMuted">
                          {f.status === "current" ? "current" : `superseded ${f.valid_to ?? ""}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
