"use client";

import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import {
  askKnowledge, fetchCorpusSummary,
  type KnowledgeAnswer, type CorpusSummary, type KnowledgeCitation,
} from "@/lib/api";

const EXAMPLES = [
  "Which cell lines can Vendor 2 test?",
  "What services does Vendor 1 offer?",
  "How much are ADP-Glo kinase assays at Vendor 6?",
  "Who can run Caco-2 assays?",
];

// render an answer string, turning [n] / [n,m] markers into clickable citation links
function renderAnswer(
  text: string,
  citations: KnowledgeCitation[],
  onOpen: (c: KnowledgeCitation) => void,
) {
  const byN = new Map<number, KnowledgeCitation>();
  citations.forEach((c) => { if (c.n != null) byN.set(c.n, c); });
  return text.split(/(\[\d+(?:\s*,\s*\d+)*\])/g).map((part, i) => {
    const m = part.match(/^\[(\d+(?:\s*,\s*\d+)*)\]$/);
    if (!m) return <span key={i}>{part}</span>;
    const nums = m[1].split(",").map((s) => s.trim());
    return (
      <sup key={i} className="mx-0.5 whitespace-nowrap text-emerald-700">
        [{nums.map((n, j) => {
          const c = byN.get(Number(n));
          return (
            <span key={j}>
              {j > 0 ? "," : ""}
              <button
                className="hover:underline"
                title={c?.subject || `source ${n}`}
                onClick={() => c && onOpen(c)}
              >{n}</button>
            </span>
          );
        })}]
      </sup>
    );
  });
}

export default function QueryOSPage() {
  const { programId } = useProgram();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [ans, setAns] = useState<KnowledgeAnswer | null>(null);
  const [summary, setSummary] = useState<CorpusSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [openDoc, setOpenDoc] = useState<KnowledgeCitation | null>(null);

  useEffect(() => {
    fetchCorpusSummary(programId).then(setSummary).catch(() => setSummary(null));
  }, [programId]);

  async function run(question: string) {
    const text = question.trim();
    if (!text) return;
    setQ(text);
    setBusy(true);
    setErr(null);
    setAns(null);
    try {
      setAns(await askKnowledge(text, programId));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-1 text-xl font-semibold">QueryOS</h1>
      <p className="mb-5 text-sm text-inkMuted">
        Ask the knowledge base built from your email + document corpus. Answers are
        grounded in extracted facts and cite the source emails — it will say
        “not found in the corpus” rather than guess.
        {summary && (
          <span className="ml-1 text-inkFaint">
            ({summary.documents} documents · {summary.facts} facts)
          </span>
        )}
      </p>

      <div className="flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run(q)}
          placeholder="e.g. which cell lines can Vendor 22 test?"
          className="flex-1 rounded border border-borderStrong bg-panel px-3 py-2 text-sm"
        />
        <button
          onClick={() => run(q)}
          disabled={busy || !q.trim()}
          className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Asking…" : "Ask"}
        </button>
      </div>

      <div className="mt-2 flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => run(ex)}
            className="rounded-full border border-border px-3 py-1 text-xs text-inkMuted hover:text-ink"
          >
            {ex}
          </button>
        ))}
      </div>

      {err && <div className="mt-4 text-sm text-red-600">{err}</div>}

      {ans && (
        <div className="mt-6 rounded-lg border border-border bg-panel p-4">
          <div className="mb-2 flex items-center gap-2 text-xs text-inkFaint">
            <span className={`rounded px-2 py-0.5 ${
              ans.source === "facts" ? "bg-emerald-600 text-white"
                : ans.source === "documents" ? "bg-amber-500 text-black"
                : "bg-panel2 text-inkMuted"}`}>
              {ans.source === "facts" ? `knowledge facts (${ans.fact_count})`
                : ans.source === "documents" ? "document search" : "no match"}
            </span>
            {!ans.used_llm && <span>· deterministic (no API key)</span>}
          </div>
          <div className="whitespace-pre-wrap text-sm text-ink">
            {renderAnswer(ans.answer, ans.citations, setOpenDoc)}
          </div>

          {ans.citations.length > 0 && (
            <div className="mt-4 border-t border-border pt-3">
              <div className="mb-1 text-xs font-medium text-inkMuted">
                Sources — click to open the email
              </div>
              <ul className="space-y-1 text-xs">
                {ans.citations.map((c, i) => (
                  <li key={`${c.id}-${i}`} className="flex gap-1.5">
                    <span className="font-mono text-emerald-700">[{c.n ?? i + 1}]</span>
                    <button
                      onClick={() => setOpenDoc(c)}
                      className="text-left text-inkMuted hover:text-ink"
                    >
                      <span className="text-ink">{c.subject || "(no subject)"}</span>
                      {c.email_from && <span className="ml-1">— {c.email_from}</span>}
                      {c.sent_at && <span className="ml-1 text-inkFaint">{String(c.sent_at).slice(0, 10)}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* source email side panel */}
      {openDoc && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={() => setOpenDoc(null)}>
          <div
            className="h-full w-full max-w-xl overflow-y-auto border-l border-borderStrong bg-panel p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold text-ink">{openDoc.subject || "(no subject)"}</div>
                <div className="mt-1 text-xs text-inkMuted">
                  {openDoc.email_from && <div>From: {openDoc.email_from}</div>}
                  {openDoc.email_to && <div>To: {openDoc.email_to}</div>}
                  {openDoc.sent_at && <div>Date: {String(openDoc.sent_at).slice(0, 10)}</div>}
                  {openDoc.doc_type && (
                    <span className="mt-1 inline-block rounded bg-panel2 px-2 py-0.5 text-inkMuted">
                      {openDoc.doc_type}
                    </span>
                  )}
                </div>
              </div>
              <button onClick={() => setOpenDoc(null)} className="text-inkMuted hover:text-ink">✕</button>
            </div>
            {openDoc.snippet && (
              <div className="mb-3 rounded border border-emerald-300 bg-emerald-50 p-2 text-xs text-emerald-800">
                matched: …{openDoc.snippet.replace(/\[/g, "").replace(/\]/g, "")}…
              </div>
            )}
            <pre className="whitespace-pre-wrap break-words text-xs text-ink">{openDoc.body || "(no content)"}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
