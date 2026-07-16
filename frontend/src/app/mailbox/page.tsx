"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useProgram } from "@/lib/ProgramContext";
import {
  fetchMailbox, fetchMailEmail, createPoFromEmail, fetchRelatedQuotes, reclassifyEmail,
  addEmailNote, fetchEmailNotes, setEmailCategory, setEmailIgnored,
  type Mailbox, type MailItem, type MailEmail, type TriageCategory, type RelatedQuotes, type EmailNote,
} from "@/lib/api";
import { DataQC } from "@/components/DataQC";
import { LegalReview } from "@/components/LegalReview";

// 5-way business classification (quote/invoice/legal/data drive actions; other is read-only)
const CAT: Record<TriageCategory, { label: string; dot: string; chip: string; icon: string }> = {
  quote:   { label: "Quote",   dot: "bg-violet-500",  chip: "bg-violet-50 text-violet-700",   icon: "💱" },
  invoice: { label: "Invoice", dot: "bg-amber-500",   chip: "bg-amber-50 text-amber-700",     icon: "🧾" },
  legal:   { label: "Legal",   dot: "bg-rose-500",    chip: "bg-rose-50 text-rose-700",       icon: "⚖️" },
  data:    { label: "Data",    dot: "bg-blue-500",    chip: "bg-blue-50 text-blue-700",       icon: "🧪" },
  other:   { label: "Other",   dot: "bg-slate-300",   chip: "bg-slate-100 text-slate-500",    icon: "🗂" },
};

// doc_type → 5-way category (client mirror of engine/categories.py) for deep-linked emails
const DT2CAT: Record<string, TriageCategory> = {
  quote: "quote", invoice: "invoice", contract: "legal", legal: "legal",
  cro_data: "data", data: "data",
};
function catFor(docType?: string, triageCat?: string): TriageCategory {
  if (triageCat && ["quote", "invoice", "legal", "data", "other"].includes(triageCat)) return triageCat as TriageCategory;
  return DT2CAT[docType || ""] ?? "other";
}

function senderName(from: string) {
  const m = from?.match(/"?([^"<]+?)"?\s*</);
  return (m ? m[1] : from || "").trim() || from;
}
function fmtDate(s: string) {
  return s ? String(s).slice(0, 10) : "";
}

// Quote actions: create a PO from the parsed lines, or compare competing quotes.
function QuotePanel({ item, programId }: { item: MailItem; programId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [rel, setRel] = useState<RelatedQuotes | null>(null);
  const [showRel, setShowRel] = useState(false);

  async function createPo() {
    setBusy(true);
    try { const r = await createPoFromEmail(item.id, programId); router.push(`/po/${r.po_id}`); }
    finally { setBusy(false); }
  }
  async function toggleRelated() {
    if (showRel) { setShowRel(false); return; }
    setShowRel(true);
    if (!rel) fetchRelatedQuotes(item.id, programId).then(setRel).catch(() => setRel(null));
  }
  return (
    <div className="mt-3 rounded-lg border border-borderStrong bg-panel2 p-3">
      <div className="mb-2 text-xs text-inkMuted">This vendor quote was parsed into structured line items.</div>
      <div className="flex flex-wrap gap-2">
        <button onClick={() => router.push(`/quote/${item.id}`)}
          className="rounded border border-borderStrong px-3 py-1.5 text-sm text-ink">
          📄 View quotation (PDF)
        </button>
        <button onClick={createPo} disabled={busy}
          className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
          {busy ? "Creating…" : "Create PO from this quote"}
        </button>
        <button onClick={toggleRelated}
          className="rounded border border-borderStrong px-3 py-1.5 text-sm text-ink">
          {showRel ? "Hide" : "Compare related quotes"}
        </button>
      </div>
      {showRel && (
        <div className="mt-3 text-xs">
          {!rel ? <div className="text-inkMuted">Loading…</div> : rel.related.length === 0 ? (
            <div className="text-inkMuted">No competing quotes found for {rel.buckets.join(", ") || "this service"}.</div>
          ) : (
            <div>
              <div className="mb-1 text-inkMuted">Competing quotes for {rel.buckets.join(", ")} (cheapest first):</div>
              <table className="w-full text-left">
                <thead className="text-inkMuted"><tr>
                  <th className="py-0.5">Vendor</th><th>Scope</th><th className="text-right">Amount</th>
                </tr></thead>
                <tbody>
                  {rel.related.map((r) => (
                    <tr key={r.line_id} className="border-t border-border/60">
                      <td className="py-0.5 pr-2 text-ink">{r.vendor ?? "—"}</td>
                      <td className="pr-2 text-inkMuted">{(r.scope ?? "").slice(0, 60)}</td>
                      <td className="text-right font-mono text-ink">${(r.amount ?? 0).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Routes an email to its action based on the 5-way business category. Only quote/
// invoice/legal/data are actionable; 'other' is read-only.
function ApprovePanel({ item, programId, onIgnored }: { item: MailItem; programId: string; onIgnored?: () => void }) {
  const cat = item.category;
  if (cat === "data") return <div className="mt-1" key={item.id}><DataQC docId={item.id} programId={programId} onIgnored={onIgnored} /></div>;
  if (cat === "legal") return <div className="mt-1" key={item.id}><LegalReview docId={item.id} programId={programId} /></div>;
  if (cat === "quote") return <QuotePanel item={item} programId={programId} />;
  if (cat === "invoice") {
    return (
      <div className="mt-3 rounded-lg border border-borderStrong bg-panel2 p-3">
        <div className="mb-2 text-xs text-inkMuted">Match this invoice against its purchase order to release funds.</div>
        <Link href="/cfo" className="inline-block rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white">
          Open in CFO / Budget → reconcile
        </Link>
      </div>
    );
  }
  // other — read-only, not acted upon by the system
  return (
    <div className="mt-3 rounded-lg border border-border bg-panel2 p-3 text-xs text-inkMuted">
      Filed as “Other” — no system action. Re-classify above if this looks miscategorized.
    </div>
  );
}

export default function MailboxPage() {
  const { programId } = useProgram();
  const [box, setBox] = useState<Mailbox | null>(null);
  const [filter, setFilter] = useState<TriageCategory | "actionable" | "ignored">("actionable");
  const [catEdit, setCatEdit] = useState(false);   // double-click classification to change it
  const [sel, setSel] = useState<MailItem | null>(null);
  const [email, setEmail] = useState<MailEmail | null>(null);
  const [reBusy, setReBusy] = useState(false);
  const [q, setQ] = useState("");
  // "leave a note for Claude" — flags the email in email_notes for later action
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [noteBusy, setNoteBusy] = useState(false);
  const [notes, setNotes] = useState<EmailNote[]>([]);

  const load = useCallback(() => {
    const cat = filter === "actionable" ? undefined : filter;
    fetchMailbox(programId, cat, filter === "other").then(setBox).catch(() => setBox(null));
  }, [programId, filter]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setSel(null); setEmail(null); }, [programId]);

  function open(m: MailItem) {
    setSel(m);
    setNoteOpen(false); setNoteText("");
    fetchMailEmail(m.id).then(setEmail).catch(() => setEmail(null));
    fetchEmailNotes(m.id, programId).then(setNotes).catch(() => setNotes([]));
  }

  // open an email by id even if it's outside the loaded list window (used by deep-link + ID search)
  function openById(id: number) {
    const inList = box?.emails.find((e) => e.id === id);
    if (inList) { open(inList); return; }
    setNoteOpen(false); setNoteText("");
    fetchEmailNotes(id, programId).then(setNotes).catch(() => setNotes([]));
    fetchMailEmail(id).then((e) => {
      setEmail(e);
      setSel({
        id: e.id, from: e.from, subject: e.subject, sent_at: e.sent_at, doc_type: e.doc_type,
        seen: true, category: catFor(e.doc_type, e.triage?.category as string | undefined),
        ignored: !!e.triage?.ignored,
        next_step: e.triage?.next_step ?? "", reason: e.triage?.reason ?? "",
        needs_reply: e.triage?.needs_reply ?? false, confidence: e.triage?.confidence ?? 0, preview: "",
      });
    }).catch(() => {});
  }

  async function saveNote() {
    if (!sel || !noteText.trim()) return;
    setNoteBusy(true);
    try {
      await addEmailNote(sel.id, noteText.trim(), programId);
      setNoteText("");
      setNotes(await fetchEmailNotes(sel.id, programId).catch(() => notes));
      setNoteOpen(false);
    } finally { setNoteBusy(false); }
  }

  // deep link: /mailbox?doc=<id> opens that email even if it's outside the list window
  const openedDoc = useRef<string | null>(null);
  useEffect(() => {
    const docId = new URLSearchParams(window.location.search).get("doc");
    if (!docId || openedDoc.current === docId) return;
    openedDoc.current = docId;
    openById(Number(docId));
  }, [box]);

  async function reclassify() {
    if (!sel) return;
    setReBusy(true);
    try {
      const r = await reclassifyEmail(sel.id, programId);
      setSel({ ...sel, category: r.category });
      load();
    } finally { setReBusy(false); }
  }
  async function changeCategory(c: TriageCategory) {
    if (!sel) return;
    setCatEdit(false);
    if (c === sel.category) return;
    setSel({ ...sel, category: c });
    await setEmailCategory(sel.id, c, programId).catch(() => {});
    load();
  }
  async function toggleIgnore() {
    if (!sel) return;
    const next = !sel.ignored;
    setSel({ ...sel, ignored: next });
    await setEmailIgnored(sel.id, next, programId).catch(() => {});
    load();
  }

  const counts = box?.counts;
  const actionable = (counts?.quote ?? 0) + (counts?.invoice ?? 0) + (counts?.legal ?? 0) + (counts?.data ?? 0);
  const tabs: { key: TriageCategory | "actionable" | "ignored"; label: string; n?: number }[] = [
    { key: "actionable", label: "Inbox", n: actionable },
    { key: "quote", label: "Quote", n: counts?.quote },
    { key: "invoice", label: "Invoice", n: counts?.invoice },
    { key: "legal", label: "Legal", n: counts?.legal },
    { key: "data", label: "Data", n: counts?.data },
    { key: "other", label: "Other", n: counts?.other },
    { key: "ignored", label: "Ignored", n: counts?.ignored },
  ];

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <h1 className="text-xl font-semibold">Inbox</h1>
        <span className="text-sm text-inkMuted">— triaged automatically; you review &amp; approve</span>
      </div>

      {/* filter tabs + search */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setFilter(t.key)}
            className={`rounded-full border px-3 py-1 text-sm ${
              filter === t.key ? "border-ink bg-ink text-white" : "border-border text-inkMuted hover:text-ink"}`}
          >
            {t.key !== "actionable" && CAT[t.key as TriageCategory] && <span className="mr-1">{CAT[t.key as TriageCategory].icon}</span>}
            {t.key === "ignored" && <span className="mr-1">🚫</span>}
            {t.label}{t.n != null && <span className="ml-1 opacity-60">{t.n}</span>}
          </button>
        ))}
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="🔍 Search emails (subject, sender, or #ID)…"
          className="ml-auto w-56 rounded border border-border bg-panel px-3 py-1 text-sm"
        />
      </div>

      <div className="grid gap-4 md:grid-cols-[340px_minmax(0,1fr)] md:items-start">
        {/* list — sticky sidebar so it stays in view while the reading pane scrolls */}
        <div className="divide-y divide-border overflow-y-auto rounded-lg border border-border bg-panel md:sticky md:top-4 md:max-h-[calc(100vh-7rem)]">
          {(() => {
            const ql = q.trim().toLowerCase();
            const emails = ql
              ? (box?.emails ?? []).filter((m) =>
                  String(m.id) === ql || String(m.id).includes(ql) ||
                  [m.subject, m.from, m.preview].some((s) => (s || "").toLowerCase().includes(ql)))
              : box?.emails ?? [];
            if (!box) return <div className="p-6 text-sm text-inkMuted">Loading…</div>;
            if (emails.length === 0) {
              // numeric query with no window match → offer to open that email id directly
              if (/^\d+$/.test(ql)) {
                return (
                  <div className="p-4 text-sm text-inkMuted">
                    No email in this view matches “{ql}”.
                    <button onClick={() => openById(Number(ql))}
                      className="mt-2 block rounded bg-sky-600 px-3 py-1.5 text-white">Open email #{ql}</button>
                  </div>
                );
              }
              return <div className="p-6 text-sm text-inkMuted">Nothing here.</div>;
            }
            return emails.map((m) => (
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
            ));
          })()}
        </div>

        {/* reading pane */}
        <div className="min-w-0 rounded-lg border border-border bg-panel p-5">
          {!sel ? (
            <div className="text-sm text-inkMuted">Select an email to read it and see the OS&apos;s proposed next step.</div>
          ) : (
            <div>
              <div className="mb-1 flex items-center gap-2">
                <span className="rounded bg-panel2 px-1.5 py-0.5 font-mono text-xs text-inkMuted"
                  title="Email ID — reference this when flagging or asking about the email">#{sel.id}</span>
                <span className="text-base font-semibold">{sel.subject || "(no subject)"}</span>
                <button onClick={() => { setNoteOpen((v) => !v); }}
                  title="Leave a note for Claude — flags this email so you can have Claude action it on your command"
                  className={`ml-auto flex shrink-0 items-center gap-1 rounded border px-2 py-1 text-xs ${
                    notes.length ? "border-amber-400 bg-amber-50 text-amber-700" : "border-border text-inkMuted hover:text-ink"}`}>
                  📝 leave a note for Claude{notes.length ? ` (${notes.length})` : ""}
                </button>
              </div>

              {/* note composer + existing notes */}
              {noteOpen && (
                <div className="mb-3 rounded-lg border border-amber-400/50 bg-amber-50/40 p-3">
                  <div className="mb-1 text-xs font-medium text-amber-800">Note for Claude</div>
                  <textarea value={noteText} onChange={(e) => setNoteText(e.target.value)} autoFocus
                    placeholder="e.g. this was mis-classified as a quote — it's actually data; fix the classifier"
                    className="w-full rounded border border-border bg-panel px-2 py-1.5 text-sm" rows={2} />
                  <div className="mt-2 flex items-center gap-2">
                    <button onClick={saveNote} disabled={noteBusy || !noteText.trim()}
                      className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
                      {noteBusy ? "Saving…" : "🚩 Flag with note"}
                    </button>
                    <button onClick={() => setNoteOpen(false)} className="text-xs text-inkMuted hover:text-ink">cancel</button>
                    <span className="text-[11px] text-inkFaint">Say “take my notes” and Claude will action these.</span>
                  </div>
                </div>
              )}
              {notes.length > 0 && !noteOpen && (
                <div className="mb-3 space-y-1">
                  {notes.map((n) => (
                    <div key={n.id} className="rounded border border-amber-400/40 bg-amber-50/30 px-2 py-1 text-xs text-amber-900">
                      🚩 {n.note}
                    </div>
                  ))}
                </div>
              )}
              <div className="mb-3 text-xs text-inkMuted">
                <div>From: {sel.from}</div>
                {email?.to && <div>To: {email.to}</div>}
                <div>{fmtDate(sel.sent_at)} · {sel.doc_type}</div>
              </div>

              {/* triage recommendation */}
              <div className="mb-4 rounded-lg border border-borderStrong bg-panel2 p-3">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  {catEdit ? (
                    <select autoFocus value={sel.category}
                      onChange={(e) => changeCategory(e.target.value as TriageCategory)}
                      onBlur={() => setCatEdit(false)}
                      className="rounded border border-sky-400 bg-white px-2 py-0.5 text-xs">
                      {(["quote", "invoice", "legal", "data", "other"] as TriageCategory[]).map((c) => (
                        <option key={c} value={c}>{CAT[c].label}</option>
                      ))}
                    </select>
                  ) : (
                    <span className={`cursor-pointer rounded px-2 py-0.5 text-xs ${CAT[sel.category].chip}`}
                      title="double-click to change the classification" onDoubleClick={() => setCatEdit(true)}>
                      {CAT[sel.category].icon} {CAT[sel.category].label}
                    </span>
                  )}
                  <button onClick={reclassify} disabled={reBusy}
                    title="Re-run the classifier model on this email"
                    className="rounded border border-border px-1.5 py-0.5 text-[11px] text-inkMuted hover:text-ink disabled:opacity-50">
                    {reBusy ? "…" : "↻ re-classify"}
                  </button>
                  <button onClick={toggleIgnore}
                    title="Ignore for now — drops this email out of the category counters"
                    className={`rounded border px-1.5 py-0.5 text-[11px] ${sel.ignored ? "border-amber-400 bg-amber-50 text-amber-700" : "border-border text-inkMuted hover:text-ink"}`}>
                    {sel.ignored ? "↩ un-ignore" : "🚫 Ignore for now"}
                  </button>
                  {sel.needs_reply && <span className="text-xs text-inkMuted">· needs reply</span>}
                  <span className="ml-auto text-[11px] text-inkFaint">
                    confidence {Math.round((sel.confidence ?? 0) * 100)}%
                  </span>
                </div>
                <div className="text-sm text-ink"><span className="text-inkMuted">Proposed next step:</span> {sel.next_step}</div>
                <div className="mt-1 text-xs text-inkMuted">{sel.reason}</div>
              </div>

              {/* approve → route to the right processor for this email's classification */}
              <ApprovePanel item={sel} programId={programId} onIgnored={() => { setSel(null); setEmail(null); load(); }} />

              {/* body */}
              <div className="whitespace-pre-wrap break-words text-sm text-ink">
                {email ? email.body : "Loading…"}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
