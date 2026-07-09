"use client";

import { useEffect, useState, useCallback } from "react";
import { useProgram } from "@/lib/ProgramContext";
import {
  fetchMailbox, fetchMailEmail,
  type Mailbox, type MailItem, type MailEmail, type TriageCategory,
} from "@/lib/api";

const CAT: Record<TriageCategory, { label: string; dot: string; chip: string; icon: string }> = {
  action:     { label: "Needs action",     dot: "bg-red-500",     chip: "bg-red-50 text-red-700",        icon: "❗" },
  processing: { label: "To process",       dot: "bg-blue-500",    chip: "bg-blue-50 text-blue-700",      icon: "⚙" },
  knowledge:  { label: "Updates knowledge", dot: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-700", icon: "📚" },
  ignore:     { label: "Ignored",          dot: "bg-slate-300",   chip: "bg-slate-100 text-slate-500",   icon: "🗑" },
};
const ORDER: TriageCategory[] = ["action", "processing", "knowledge", "ignore"];

function senderName(from: string) {
  const m = from?.match(/"?([^"<]+?)"?\s*</);
  return (m ? m[1] : from || "").trim() || from;
}
function fmtDate(s: string) {
  return s ? String(s).slice(0, 10) : "";
}

export default function MailboxPage() {
  const { programId } = useProgram();
  const [box, setBox] = useState<Mailbox | null>(null);
  const [filter, setFilter] = useState<TriageCategory | "actionable" | "ignore">("actionable");
  const [sel, setSel] = useState<MailItem | null>(null);
  const [email, setEmail] = useState<MailEmail | null>(null);

  const load = useCallback(() => {
    const cat = filter === "actionable" ? undefined : filter;
    fetchMailbox(programId, cat, filter === "ignore").then(setBox).catch(() => setBox(null));
  }, [programId, filter]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setSel(null); setEmail(null); }, [programId]);

  function open(m: MailItem) {
    setSel(m);
    fetchMailEmail(m.id).then(setEmail).catch(() => setEmail(null));
  }

  const counts = box?.counts;
  const tabs: { key: TriageCategory | "actionable"; label: string; n?: number }[] = [
    { key: "actionable", label: "Inbox", n: (counts?.action ?? 0) + (counts?.processing ?? 0) + (counts?.knowledge ?? 0) },
    { key: "action", label: "Needs action", n: counts?.action },
    { key: "processing", label: "To process", n: counts?.processing },
    { key: "knowledge", label: "Knowledge", n: counts?.knowledge },
    { key: "ignore", label: "Ignored", n: counts?.ignore },
  ];

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <h1 className="text-xl font-semibold">Inbox</h1>
        <span className="text-sm text-inkMuted">— triaged automatically; you review &amp; approve</span>
      </div>

      {/* filter tabs */}
      <div className="mb-3 flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setFilter(t.key)}
            className={`rounded-full border px-3 py-1 text-sm ${
              filter === t.key ? "border-ink bg-ink text-white" : "border-border text-inkMuted hover:text-ink"}`}
          >
            {t.label}{t.n != null && <span className="ml-1 opacity-60">{t.n}</span>}
          </button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,420px)_1fr]">
        {/* list */}
        <div className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-panel">
          {!box ? (
            <div className="p-6 text-sm text-inkMuted">Loading…</div>
          ) : box.emails.length === 0 ? (
            <div className="p-6 text-sm text-inkMuted">Nothing here.</div>
          ) : (
            box.emails.map((m) => (
              <button
                key={m.id}
                onClick={() => open(m)}
                className={`flex w-full flex-col gap-0.5 px-3 py-2.5 text-left hover:bg-panel2 ${
                  sel?.id === m.id ? "bg-panel2" : ""}`}
              >
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${CAT[m.category].dot}`} />
                  <span className={`truncate text-sm ${m.seen ? "text-ink" : "font-semibold text-ink"}`}>
                    {senderName(m.from)}
                  </span>
                  <span className="ml-auto shrink-0 text-xs text-inkFaint">{fmtDate(m.sent_at)}</span>
                </div>
                <div className={`truncate text-sm ${m.seen ? "text-inkMuted" : "text-ink"}`}>{m.subject || "(no subject)"}</div>
                <div className="truncate text-xs text-inkFaint">{m.preview}</div>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] ${CAT[m.category].chip}`}>
                    {CAT[m.category].icon} {CAT[m.category].label}
                  </span>
                  <span className="truncate text-[11px] text-inkMuted">→ {m.next_step}</span>
                </div>
              </button>
            ))
          )}
        </div>

        {/* reading pane */}
        <div className="rounded-lg border border-border bg-panel p-5">
          {!sel ? (
            <div className="text-sm text-inkMuted">Select an email to read it and see the OS&apos;s proposed next step.</div>
          ) : (
            <div>
              <div className="mb-1 text-base font-semibold">{sel.subject || "(no subject)"}</div>
              <div className="mb-3 text-xs text-inkMuted">
                <div>From: {sel.from}</div>
                {email?.to && <div>To: {email.to}</div>}
                <div>{fmtDate(sel.sent_at)} · {sel.doc_type}</div>
              </div>

              {/* triage recommendation */}
              <div className="mb-4 rounded-lg border border-borderStrong bg-panel2 p-3">
                <div className="mb-1 flex items-center gap-2">
                  <span className={`rounded px-2 py-0.5 text-xs ${CAT[sel.category].chip}`}>
                    {CAT[sel.category].icon} {CAT[sel.category].label}
                  </span>
                  {sel.needs_reply && <span className="text-xs text-inkMuted">· needs reply</span>}
                  <span className="ml-auto text-[11px] text-inkFaint">
                    confidence {Math.round((sel.confidence ?? 0) * 100)}%
                  </span>
                </div>
                <div className="text-sm text-ink"><span className="text-inkMuted">Proposed next step:</span> {sel.next_step}</div>
                <div className="mt-1 text-xs text-inkMuted">{sel.reason}</div>
                <div className="mt-3 flex gap-2">
                  <button className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white opacity-60" disabled>
                    Approve &amp; process
                  </button>
                  <button className="rounded border border-borderStrong px-3 py-1.5 text-sm opacity-60" disabled>
                    Modify
                  </button>
                  <span className="self-center text-[11px] text-inkFaint">(approve → ingest: coming next)</span>
                </div>
              </div>

              {/* body */}
              <div className="whitespace-pre-wrap text-sm text-ink">
                {email ? email.body : "Loading…"}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
