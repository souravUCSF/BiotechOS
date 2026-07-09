"use client";

import { useCallback, useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import {
  fetchDecisions, decideDecision,
  type SuspectedDecision, type KnowledgeCitation,
} from "@/lib/api";

const KIND_LABEL: Record<string, string> = {
  price_agreement: "Price agreement",
  vendor_selection: "Vendor selection",
  scope_change: "Scope change",
  timeline_commitment: "Timeline commitment",
  go_no_go: "Go / No-Go",
  contract_term: "Contract term",
  other: "Other",
};

export default function DecisionsPage() {
  const { programId } = useProgram();
  const [items, setItems] = useState<SuspectedDecision[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [openDoc, setOpenDoc] = useState<KnowledgeCitation | null>(null);

  const load = useCallback(() => {
    fetchDecisions(programId).then(setItems).catch(() => setItems([]));
  }, [programId]);
  useEffect(load, [load]);

  async function act(id: number, action: "confirm" | "dismiss") {
    setBusy(id);
    try {
      await decideDecision(id, action, programId);
      setItems((xs) => xs.filter((x) => x.id !== id));
    } finally {
      setBusy(null);
    }
  }

  // group by kind
  const groups = new Map<string, SuspectedDecision[]>();
  for (const d of items) {
    const k = d.kind || "other";
    (groups.get(k) ?? groups.set(k, []).get(k)!).push(d);
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex items-baseline gap-3">
        <h1 className="text-lg font-semibold text-ink">Decisions to confirm</h1>
        <span className="text-sm text-inkMuted">{items.length} suspected</span>
      </div>
      {items.length === 0 && (
        <div className="text-sm text-inkMuted">
          No suspected decisions. New ones appear as comms are ingested.
        </div>
      )}

      {[...groups.entries()].map(([kind, ds]) => (
        <section key={kind} className="mb-6">
          <h2 className="mb-2 text-sm font-semibold text-ink">
            {KIND_LABEL[kind] ?? kind} <span className="text-inkMuted">({ds.length})</span>
          </h2>
          <div className="flex flex-col gap-2">
            {ds.map((d) => (
              <div key={d.id} className="rounded border border-border bg-panel p-3">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="text-sm text-ink">
                      <span className="font-semibold">{d.subject_key}</span>
                      <span className="text-inkMuted"> · {d.predicate} = </span>
                      <span className="font-mono">{d.value ?? "—"}</span>
                    </div>
                    {d.rationale && (
                      <div className="mt-0.5 text-xs text-inkMuted">{d.rationale}</div>
                    )}
                    {d.source && (
                      <button
                        className="mt-1 text-xs text-emerald-700 hover:underline"
                        onClick={() => setOpenDoc(d.source)}
                      >
                        source: {d.source.subject || `doc ${d.source_document_id}`}
                      </button>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-xs text-inkMuted">{Math.round(d.confidence * 100)}%</span>
                    <button
                      disabled={busy === d.id}
                      onClick={() => act(d.id, "confirm")}
                      className="rounded bg-emerald-700 px-2 py-1 text-xs text-white disabled:opacity-50"
                    >Confirm</button>
                    <button
                      disabled={busy === d.id}
                      onClick={() => act(d.id, "dismiss")}
                      className="rounded border border-border px-2 py-1 text-xs text-inkMuted disabled:opacity-50"
                    >Dismiss</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}

      {openDoc && (
        <div
          className="fixed inset-0 z-20 flex items-center justify-center bg-black/40 p-8"
          onClick={() => setOpenDoc(null)}
        >
          <div
            className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded bg-panel p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-2 text-sm font-semibold text-ink">{openDoc.subject}</div>
            <div className="mb-2 text-xs text-inkMuted">
              {openDoc.email_from} → {openDoc.email_to} · {openDoc.sent_at}
            </div>
            <pre className="whitespace-pre-wrap text-xs text-ink">{openDoc.body}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
