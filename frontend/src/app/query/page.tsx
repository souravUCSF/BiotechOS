"use client";

import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import {
  askKnowledge, fetchCorpusSummary,
  type KnowledgeAnswer, type CorpusSummary,
} from "@/lib/api";

const EXAMPLES = [
  "Which cell lines can Vendor 22 test?",
  "What services does Vendor 23 offer?",
  "What has Vendor 23 quoted?",
  "Which vendors can run intact MS?",
];

export default function QueryOSPage() {
  const { programId } = useProgram();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [ans, setAns] = useState<KnowledgeAnswer | null>(null);
  const [summary, setSummary] = useState<CorpusSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);

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
          <div className="whitespace-pre-wrap text-sm text-ink">{ans.answer}</div>

          {ans.citations.length > 0 && (
            <div className="mt-4 border-t border-border pt-3">
              <div className="mb-1 text-xs font-medium text-inkMuted">Sources</div>
              <ul className="space-y-1 text-xs">
                {ans.citations.map((c, i) => (
                  <li key={`${c.id}-${i}`} className="text-inkMuted">
                    <span className="text-ink">📧 {c.subject || "(no subject)"}</span>
                    {c.email_from && <span className="ml-1">— {c.email_from}</span>}
                    {c.sent_at && <span className="ml-1 text-inkFaint">{String(c.sent_at).slice(0, 10)}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
