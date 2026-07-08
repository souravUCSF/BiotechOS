"use client";

import { useCallback, useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import {
  approveInboxV2,
  declineInbox,
  fetchInbox,
  resetDemo,
  type InboxApproveResult,
  type InboxV2Item,
} from "@/lib/api";

const STATUS_STYLE: Record<string, string> = {
  pass: "text-emerald-700",
  near: "text-amber-600",
  fail: "text-red-600",
  no_data: "text-inkMuted",
};

function ContextPanel({ item }: { item: InboxV2Item }) {
  const c = item.context;
  const has = c.molecules?.length || c.budget || c.prior_quotes || c.ledger?.length;
  if (!has) return null;
  return (
    <div className="mt-3 rounded border border-border bg-bg p-3 text-xs">
      <div className="mb-1 font-medium text-inkMuted">Context</div>
      {c.molecules && c.molecules.length > 0 && (
        <div className="mb-1">
          <span className="text-inkMuted">Molecules: </span>
          {c.molecules.map((m, i) => (
            <span key={m.molecule_id}>
              {i > 0 && ", "}
              {m.name}{" "}
              <span className={STATUS_STYLE[m.tpp_status] ?? ""}>({m.tpp_status})</span>
            </span>
          ))}
        </div>
      )}
      {c.budget && (
        <div className="mb-1 text-inkMuted">
          Budget available ${c.budget.available.toLocaleString()} · committed $
          {c.budget.committed.toLocaleString()}
          {c.budget.runway_months != null && ` · ${c.budget.runway_months} mo runway`}
        </div>
      )}
      {c.prior_quotes && c.prior_quotes.amounts.length > 0 && (
        <div className="mb-1 text-inkMuted">
          Prior quotes from this vendor: {c.prior_quotes.amounts.join(", ")}
        </div>
      )}
      {c.ledger && c.ledger.length > 0 && (
        <div className="text-inkMuted">
          Related decisions: {c.ledger.map((l) => l.title).join("; ")}
        </div>
      )}
    </div>
  );
}

function InboxCard({
  item,
  onDone,
}: {
  item: InboxV2Item;
  onDone: () => void;
}) {
  const { programId } = useProgram();
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<InboxApproveResult | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const env = item.envelope;

  async function approve() {
    setBusy(true);
    try {
      const r = await approveInboxV2(item.id, programId);
      setResult(r);
    } finally {
      setBusy(false);
    }
  }

  async function decline() {
    setBusy(true);
    try {
      await declineInbox(item.id, programId);
      setDismissed(true);
      onDone();
    } finally {
      setBusy(false);
    }
  }

  if (dismissed) return null;

  const locked = env.attachments.some((a) => a.protected);

  return (
    <div className="rounded border border-border bg-panel p-4">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start justify-between text-left"
      >
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-inkMuted">
              {(item.doc_type ?? item.kind).replace(/_/g, " ")}
            </span>
            {locked && <span title="password-protected attachment">🔒</span>}
          </div>
          <h3 className="truncate text-sm font-medium">{env.subject}</h3>
          <p className="truncate text-xs text-inkMuted">
            {env.email_from}
            {env.date ? ` · ${env.date}` : ""}
          </p>
        </div>
        {result ? (
          <span className="ml-2 rounded bg-emerald-700 px-2 py-0.5 text-xs text-white">done</span>
        ) : (
          <span className="ml-2 text-xs text-inkMuted">{expanded ? "▲" : "▼"}</span>
        )}
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {env.body_preview && (
            <p className="whitespace-pre-wrap text-sm text-ink">{env.body_preview}</p>
          )}
          {env.attachments.length > 0 && (
            <div className="text-xs text-inkMuted">
              Attachments:{" "}
              {env.attachments.map((a) => `${a.protected ? "🔒 " : ""}${a.filename}`).join(", ")}
            </div>
          )}

          <div className="rounded border border-border bg-bg p-3 text-xs">
            <div className="mb-1 font-medium text-inkMuted">Extracted</div>
            <pre className="whitespace-pre-wrap font-sans text-ink">
              {JSON.stringify(item.extraction, null, 2)}
            </pre>
          </div>

          {item.analysis?.note && (
            <div className="text-sm">
              <span className="text-inkMuted">Recommendation: </span>
              <b>{item.analysis.recommendation ?? item.proposed_action.action}</b> —{" "}
              {item.analysis.note}
            </div>
          )}

          <ContextPanel item={item} />

          {!result && (
            <div className="flex items-center gap-3">
              <button
                onClick={approve}
                disabled={busy}
                className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
              >
                {busy ? "Processing…" : (item.proposed_action.label ?? "Approve")}
              </button>
              <button
                onClick={decline}
                disabled={busy}
                className="rounded border border-borderStrong px-3 py-1.5 text-sm text-inkMuted hover:bg-panel2 disabled:opacity-50"
              >
                Decline
              </button>
            </div>
          )}

          {result && (
            <div className="rounded border border-border bg-bg p-3 text-sm">
              {result.financial?.po_number && (
                <div className="text-emerald-700">
                  ✓ Issued {result.financial.po_number} · committed $
                  {result.financial.amount?.toLocaleString()} · available $
                  {result.financial.budget.available.toLocaleString()}
                </div>
              )}
              {result.molecules && result.molecules.length > 0 && (
                <div className="text-emerald-700">
                  ✓ {result.loaded} measurements loaded ·{" "}
                  {result.molecules.map((m) => `${m.name}${m.created ? " (new)" : ""}`).join(", ")}
                </div>
              )}
              {result.crossed && result.crossed.length > 0 && (
                <div className="text-emerald-700">
                  <b>{result.crossed.join(", ")}</b> crossed to MEETS TPP
                </div>
              )}
              {result.reply_draft && (
                <div className="mt-1">
                  <div className="mb-1 text-xs text-inkMuted">
                    Drafted reply (grounded · {result.grounding?.source})
                  </div>
                  <pre className="whitespace-pre-wrap font-sans text-xs text-ink">
                    {result.reply_draft}
                  </pre>
                </div>
              )}
              {result.memo && (
                <div className="mt-2 border-t border-border pt-2">
                  <div className="mb-1 text-xs text-inkMuted">Drafted go/no-go memo</div>
                  <pre className="whitespace-pre-wrap font-sans text-xs text-ink">
                    {result.memo.text}
                  </pre>
                </div>
              )}
              {result.promoted_facts != null && (
                <div className="mt-1 text-xs text-inkMuted">
                  {result.promoted_facts} observation(s) promoted to facts · logged to Decision Log
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
  const [items, setItems] = useState<InboxV2Item[] | null>(null);
  const [resetting, setResetting] = useState(false);

  const load = useCallback(() => {
    fetchInbox(programId)
      .then(setItems)
      .catch(() => setItems([]));
  }, [programId]);

  useEffect(() => {
    load();
  }, [load]);

  async function doReset() {
    setResetting(true);
    try {
      await resetDemo(programId);
      load();
    } finally {
      setResetting(false);
    }
  }

  if (items === null) return <p className="text-inkMuted">Loading…</p>;

  return (
    <div className="max-w-3xl">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Current Inbox</h1>
          <p className="text-sm text-inkMuted">
            Triaged inbound mail — the OS extracted each item and proposed an action.
          </p>
        </div>
        <button
          onClick={doReset}
          disabled={resetting}
          className="rounded border border-borderStrong px-3 py-1.5 text-xs text-inkMuted hover:bg-panel2"
        >
          {resetting ? "Resetting…" : "Reset demo"}
        </button>
      </div>

      {items.length === 0 ? (
        <div className="rounded border border-dashed border-borderStrong p-8 text-center text-inkMuted">
          Inbox empty. Ingest the corpus or click “Reset demo”.
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item) => (
            <InboxCard key={item.id} item={item} onDone={load} />
          ))}
        </div>
      )}
    </div>
  );
}
