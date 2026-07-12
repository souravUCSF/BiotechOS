"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchLegalReview, runLegalReview, legalDocDownloadUrl, saveLegalDoc, fetchLegalExecutionStatus,
  type LegalReview as LR, type LegalIssue,
} from "@/lib/api";

const EXEC: Record<string, { label: string; chip: string }> = {
  draft: { label: "Draft — for execution", chip: "bg-sky-500/15 text-sky-300" },
  in_revision: { label: "In revision", chip: "bg-amber-500/15 text-amber-300" },
  executed: { label: "Executed / countersigned", chip: "bg-emerald-500/15 text-emerald-800" },
};

const SEV: Record<string, { label: string; chip: string; dot: string; ring: string }> = {
  high: { label: "High", chip: "bg-rose-500/15 text-rose-300", dot: "bg-rose-500", ring: "border-rose-500/40" },
  medium: { label: "Medium", chip: "bg-amber-500/15 text-amber-300", dot: "bg-amber-500", ring: "border-amber-500/40" },
  low: { label: "Low", chip: "bg-sky-500/15 text-sky-300", dot: "bg-sky-500", ring: "border-sky-500/40" },
};

function IssueCard({ it }: { it: LegalIssue }) {
  const s = SEV[it.severity] ?? SEV.low;
  return (
    <div className={`rounded border ${s.ring} bg-panel2 p-2.5`}>
      <div className="mb-0.5 flex items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${s.chip}`}>{s.label}</span>
        <span className="text-sm font-medium text-ink">{it.title}</span>
      </div>
      {it.clause && <div className="text-[11px] text-inkFaint">Clause: {it.clause}</div>}
      <div className="mt-1 text-xs text-inkMuted">{it.issue}</div>
      {it.recommendation && (
        <div className="mt-1.5 rounded border border-emerald-600/40 bg-emerald-100 px-2 py-1 text-xs text-emerald-900">
          <span className="font-semibold text-emerald-700">Recommend →</span> {it.recommendation}
        </div>
      )}
    </div>
  );
}

export function LegalReview({ docId, programId }: { docId: number; programId: string }) {
  const [lr, setLr] = useState<LR | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"text" | "native">("text");
  const [execTBD, setExecTBD] = useState(false);
  const [saved, setSaved] = useState(false);
  const [execStatus, setExecStatus] = useState<string | null>(null);
  const [reviewAnyway, setReviewAnyway] = useState(false);

  const load = useCallback(() => {
    fetchLegalReview(docId, programId).then(setLr).catch(() => setLr(null));
  }, [docId, programId]);
  useEffect(load, [load]);
  useEffect(() => { setOpen(false); setMode("text"); setSaved(false); setReviewAnyway(false); }, [docId]);
  // up-front: is this an already-executed doc (file it) or a draft to review?
  useEffect(() => {
    setExecStatus(null);
    fetchLegalExecutionStatus(docId, programId)
      .then((r) => setExecStatus(r.execution_status)).catch(() => setExecStatus(null));
  }, [docId, programId]);

  async function saveToFiles() {
    setBusy(true);
    try { await saveLegalDoc(docId, programId); setSaved(true); }
    finally { setBusy(false); }
  }

  async function run() {
    setBusy(true);
    try {
      const files = mode === "native"
        ? lr?.attachments.filter((a) => a.native_available).map((a) => a.filename)
        : undefined;
      setLr(await runLegalReview(docId, programId, mode, files));
      setOpen(true);
    } finally { setBusy(false); }
  }

  if (!lr) return null;
  const rv = lr.review;
  const anyNative = lr.attachments.some((a) => a.native_available);

  return (
    <div className="mb-4 rounded-lg border border-borderStrong bg-panel2 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-semibold text-ink">⚖️ Legal review</span>
        {rv && (
          <>
            <span className="text-xs text-inkMuted">{rv.agreement_type}</span>
            <span className={`rounded px-1.5 py-0.5 text-xs ${(EXEC[rv.execution_status] ?? EXEC.draft).chip}`}>
              {(EXEC[rv.execution_status] ?? EXEC.draft).label}
            </span>
            {(["high", "medium", "low"] as const).map((k) => rv.counts[k] > 0 && (
              <span key={k} className={`rounded px-1.5 py-0.5 text-xs ${SEV[k].chip}`}>{rv.counts[k]} {SEV[k].label}</span>
            ))}
          </>
        )}
        <span className="ml-auto text-[11px] text-inkFaint">draft-legal</span>
      </div>

      {busy && (
        <div className="mb-2 flex items-center gap-2 rounded border border-violet-500/30 bg-violet-500/10 px-2 py-1.5 text-xs text-violet-300">
          <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-violet-400 border-t-transparent" />
          Reviewing the agreement… this can take up to a minute.
        </div>
      )}

      {execStatus === "executed" && !reviewAnyway ? (
        // Already fully executed → file it, don't run a redline review.
        <div className="rounded border border-emerald-500/30 bg-emerald-500/5 p-2">
          <div className="mb-2 text-xs font-medium text-emerald-800">
            📁 This looks like a <b>fully-executed</b> document returned for records — no review needed, just file it for later.
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={saveToFiles} disabled={busy || saved}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60">
              {saved ? "✓ Saved to files" : "🗄 Save to files"}
            </button>
            <a href={legalDocDownloadUrl(docId, programId)} download
              className="rounded border border-borderStrong px-3 py-1.5 text-sm text-ink">📥 Download</a>
            <button onClick={() => setReviewAnyway(true)}
              className="text-xs text-inkFaint hover:text-ink">Review anyway</button>
          </div>
        </div>
      ) : rv ? (
        <>
          <div className="mb-2 text-xs text-inkMuted">{rv.summary}</div>
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => setOpen(true)}
              className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white">
              View document &amp; {rv.issues.length} issue{rv.issues.length !== 1 ? "s" : ""}
            </button>
            {/* workflow action depends on execution status */}
            {rv.execution_status === "executed" ? (
              <>
                <button onClick={async () => { await saveLegalDoc(docId, programId).catch(() => {}); setSaved(true); }}
                  disabled={saved}
                  className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60">
                  {saved ? "✓ Saved to records" : "🗄 Save to records"}
                </button>
                <a href={legalDocDownloadUrl(docId, programId)} download
                  className="rounded border border-borderStrong px-3 py-1.5 text-sm text-ink">
                  📥 Download
                </a>
              </>
            ) : (
              <button onClick={() => setExecTBD(true)}
                className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white">
                ✍️ Route for execution
              </button>
            )}
            <span className="mx-1 h-4 w-px bg-border" />
            <label className="inline-flex items-center gap-1 text-xs text-inkMuted">
              <input type="radio" checked={mode === "text"} onChange={() => setMode("text")} /> text
            </label>
            <label className={`inline-flex items-center gap-1 text-xs ${anyNative ? "text-inkMuted" : "text-inkFaint"}`}>
              <input type="radio" checked={mode === "native"} disabled={!anyNative} onChange={() => setMode("native")} /> native
            </label>
            <button onClick={run} disabled={busy}
              className="rounded border border-borderStrong px-3 py-1.5 text-sm text-inkMuted disabled:opacity-50">Re-review</button>
          </div>
          {execTBD && (
            <div className="mt-2 rounded border border-indigo-500/30 bg-indigo-500/5 px-2 py-1 text-xs text-inkMuted">
              DocuSign routing is not wired yet (TBD) — this will send {rv.agreement_type} out for e-signature.
              <button onClick={() => setExecTBD(false)} className="ml-2 text-inkFaint hover:text-ink">dismiss</button>
            </div>
          )}
        </>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-inkMuted">
            {execStatus === null ? "Checking execution status…" : "Run the document through draft-legal."}
          </span>
          <label className="inline-flex items-center gap-1 text-xs text-inkMuted">
            <input type="radio" checked={mode === "text"} onChange={() => setMode("text")} /> text
          </label>
          <label className={`inline-flex items-center gap-1 text-xs ${anyNative ? "text-inkMuted" : "text-inkFaint"}`}>
            <input type="radio" checked={mode === "native"} disabled={!anyNative} onChange={() => setMode("native")} /> native
          </label>
          <button onClick={run} disabled={busy}
            className="rounded bg-violet-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">Review contract</button>
        </div>
      )}

      {/* large document + issues popup */}
      {open && rv && (
        <div className="fixed inset-0 z-30 flex items-start justify-center overflow-y-auto bg-black/60 p-6"
          onClick={() => setOpen(false)}>
          <div className="mt-4 w-full max-w-6xl rounded-lg border border-border bg-panel shadow-xl"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 border-b border-border px-4 py-2">
              <span className="text-sm font-semibold text-ink">⚖️ {rv.agreement_type}</span>
              {rv.parties?.length > 0 && <span className="text-xs text-inkMuted">{rv.parties.join(" · ")}</span>}
              {rv.term && <span className="text-xs text-inkFaint">Term: {rv.term}</span>}
              <button onClick={() => setOpen(false)} className="ml-auto text-inkMuted hover:text-ink">✕</button>
            </div>
            <div className="grid h-[80vh] grid-cols-2 gap-0">
              {/* document */}
              <div className="min-h-0 overflow-y-auto border-r border-border bg-panel2 p-4">
                <div className="mb-2 text-[11px] uppercase tracking-wide text-inkFaint">Document</div>
                <pre className="whitespace-pre-wrap break-words rounded bg-white p-4 font-mono text-[11px] leading-relaxed text-slate-900 shadow-inner">
                  {lr.document_text || "(no document text)"}
                </pre>
              </div>
              {/* issues by severity */}
              <div className="overflow-y-auto p-4">
                <div className="mb-1 text-[11px] uppercase tracking-wide text-inkFaint">
                  Issues — {rv.counts.high} High · {rv.counts.medium} Medium · {rv.counts.low} Low
                </div>
                <div className="mb-2 text-xs text-inkMuted">{rv.summary}</div>
                <div className="space-y-2">
                  {rv.issues.map((it, i) => <IssueCard key={i} it={it} />)}
                  {rv.issues.length === 0 && <div className="text-xs text-inkMuted">No issues flagged.</div>}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
