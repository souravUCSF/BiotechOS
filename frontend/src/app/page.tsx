"use client";

import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { useAppState } from "@/lib/useAppState";
import {
  approveInbox,
  fetchRederivation,
  resetDemo,
  type ApproveResult,
  type Rederivation,
} from "@/lib/api";
import type { InboxItem } from "@/lib/types";
import { DoseResponse } from "@/components/DoseResponse";

function parseAction(item: InboxItem): { label?: string; note?: string; action?: string } {
  try {
    return item.proposed_action ? JSON.parse(item.proposed_action) : {};
  } catch {
    return {};
  }
}

function InboxCard({
  item,
  onApproved,
}: {
  item: InboxItem;
  onApproved: (r: ApproveResult) => void;
}) {
  const { programId } = useProgram();
  const action = parseAction(item);
  const [rederiv, setRederiv] = useState<Rederivation | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ApproveResult | null>(null);
  const approved = item.status === "approved" || result !== null;

  useEffect(() => {
    if (item.kind === "bio_cro_data") {
      fetchRederivation(item.id, programId)
        .then((r) => (r.has_curve ? setRederiv(r) : null))
        .catch(() => {});
    }
  }, [item.id, item.kind, programId]);

  async function approve() {
    setBusy(true);
    try {
      const r = await approveInbox(item.id, programId);
      setResult(r);
      onApproved(r);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded border border-neutral-800 bg-neutral-900 p-4">
      <div className="flex items-start justify-between">
        <div>
          <span className="text-xs uppercase tracking-wide text-neutral-500">
            {item.kind.replace(/_/g, " ")}
          </span>
          <h3 className="text-sm font-medium">{item.title}</h3>
        </div>
        {approved && (
          <span className="rounded bg-emerald-700 px-2 py-0.5 text-xs text-white">approved</span>
        )}
      </div>
      {item.summary && <p className="mt-2 text-sm text-neutral-400">{item.summary}</p>}

      {rederiv?.flagged && (
        <div className="mt-3 rounded border border-amber-700/50 bg-amber-950/30 p-3">
          <div className="mb-2 text-xs font-medium text-amber-400">
            ⚠ Data QC — reported IC50 disagrees with the raw curve
          </div>
          <DoseResponse rederiv={rederiv} />
        </div>
      )}

      {!approved && (
        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={approve}
            disabled={busy}
            className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? "Processing…" : (action.label ?? "Approve")}
          </button>
          {action.note && <span className="text-xs text-neutral-500">{action.note}</span>}
        </div>
      )}

      {result && (
        <div className="mt-3 rounded border border-neutral-800 bg-neutral-950 p-3 text-sm">
          {result.crossed.length > 0 ? (
            <div className="text-emerald-400">
              ✓ {result.loaded} measurements loaded · <b>{result.crossed.join(", ")}</b> crossed to
              MEETS TPP
            </div>
          ) : (
            <div className="text-neutral-300">
              ✓ {result.loaded > 0 ? `${result.loaded} measurements loaded` : "Acknowledged"} ·
              logged to Decision Log
            </div>
          )}
          {result.memo && (
            <div className="mt-2 border-t border-neutral-800 pt-2">
              <div className="mb-1 text-xs text-neutral-500">
                Drafted go/no-go memo {result.memo.used_llm ? "" : "(fallback)"}
              </div>
              <pre className="whitespace-pre-wrap font-sans text-xs text-neutral-300">
                {result.memo.text}
              </pre>
            </div>
          )}
          {result.financial && (
            <div className="mt-1">
              {result.financial.po_number && (
                <div className="text-emerald-400">
                  ✓ Issued {result.financial.po_number} · committed{" "}
                  ${result.financial.amount?.toLocaleString()} · available now $
                  {result.financial.budget.available.toLocaleString()}
                </div>
              )}
              {result.financial.matched != null && (
                <div className={result.financial.matched ? "text-emerald-400" : "text-red-400"}>
                  {result.financial.matched ? "✓" : "⚠"} {result.financial.note} · actual spend $
                  {result.financial.budget.actual.toLocaleString()}
                </div>
              )}
              {result.financial.email && (
                <div className="mt-2 border-t border-neutral-800 pt-2">
                  <div className="mb-1 text-xs text-neutral-500">
                    Vendor email — Gmail draft (composed, not sent)
                  </div>
                  <pre className="whitespace-pre-wrap font-sans text-xs text-neutral-300">
                    {result.financial.email}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function InboxPage() {
  const { programId } = useProgram();
  const { state, loading, reload } = useAppState();
  const [resetting, setResetting] = useState(false);

  async function doReset() {
    setResetting(true);
    try {
      await resetDemo(programId);
      reload();
    } finally {
      setResetting(false);
    }
  }

  if (loading) return <p className="text-neutral-400">Loading…</p>;
  if (!state) return null;

  return (
    <div className="max-w-3xl">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Monday-morning Inbox</h1>
          <p className="text-sm text-neutral-400">
            {state.program.name} · the OS has pre-triaged each item and proposed an action.
          </p>
        </div>
        <button
          onClick={doReset}
          disabled={resetting}
          className="rounded border border-neutral-700 px-3 py-1.5 text-xs text-neutral-400 hover:bg-neutral-800"
        >
          {resetting ? "Resetting…" : "Reset demo"}
        </button>
      </div>

      {state.inbox_items.length === 0 ? (
        <div className="rounded border border-dashed border-neutral-700 p-8 text-center text-neutral-500">
          Inbox empty. Click “Reset demo” to re-stage the incoming CRO datasets.
        </div>
      ) : (
        <div className="space-y-4">
          {state.inbox_items.map((item) => (
            <InboxCard key={item.id} item={item} onApproved={() => reload()} />
          ))}
        </div>
      )}
    </div>
  );
}
