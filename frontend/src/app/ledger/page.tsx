"use client";

import { useAppState } from "@/lib/useAppState";

const KIND_STYLE: Record<string, string> = {
  go_no_go: "bg-emerald-700 text-white",
  data_interpretation: "bg-blue-800 text-white",
  chem_update: "bg-panel2 text-ink",
  po_approval: "bg-amber-700 text-white",
  invoice_reconcile: "bg-amber-800 text-white",
};

export default function LedgerPage() {
  const { state, loading } = useAppState();
  if (loading) return <p className="text-inkMuted">Loading…</p>;
  if (!state) return null;

  return (
    <div className="max-w-3xl">
      <h1 className="mb-1 text-xl font-semibold">Decision Log</h1>
      <p className="mb-6 text-sm text-inkMuted">
        Every human-approved decision, timestamped — the signed paper trail. “The OS
        synthesizes, drafts, computes, tracks; the human decides and signs.”
      </p>

      {state.ledger_entries.length === 0 ? (
        <div className="rounded border border-dashed border-borderStrong p-8 text-center text-inkMuted">
          No decisions yet — approve items in the Inbox to build the record.
        </div>
      ) : (
        <ol className="space-y-3">
          {state.ledger_entries.map((e) => (
            <li key={e.id} className="rounded border border-border bg-panel p-4">
              <div className="flex items-center justify-between">
                <span className={`rounded px-2 py-0.5 text-xs ${KIND_STYLE[e.kind] ?? "bg-panel2"}`}>
                  {e.kind.replace(/_/g, " ")}
                </span>
                <span className="text-xs text-inkMuted">
                  {e.created_at} · signed by {e.approved_by}
                </span>
              </div>
              <div className="mt-2 text-sm font-medium">{e.title}</div>
              {e.content && (
                <pre className="mt-1 whitespace-pre-wrap font-sans text-xs text-inkMuted">
                  {e.content}
                </pre>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
