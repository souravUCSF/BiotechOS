"use client";

import { useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { updateTppParam, type TppParam } from "@/lib/api";
import { ParamHistogram } from "@/components/ParamHistogram";

export function TppParamModal({
  param,
  onClose,
  onVersioned,
}: {
  param: TppParam;
  onClose: () => void;
  onVersioned: (v: number) => void;
}) {
  const { programId } = useProgram();
  const [operator, setOperator] = useState(param.operator);
  const [threshold, setThreshold] = useState(String(param.threshold));
  const [justification, setJustification] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const changed =
    operator !== param.operator || Number(threshold) !== param.threshold;

  async function save() {
    if (!justification.trim()) {
      setError("A written justification is required to change the TPP.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await updateTppParam(
        param.id,
        { operator, threshold: Number(threshold) },
        justification,
        programId,
      );
      onVersioned(r.new_version);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-lg border border-borderStrong bg-panel p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-1 flex items-start justify-between">
          <h2 className="text-lg font-semibold">{param.label}</h2>
          <button onClick={onClose} className="text-inkMuted hover:text-ink">✕</button>
        </div>
        <div className="mb-4 text-xs uppercase tracking-wide text-inkMuted">
          {param.axis} · metric <span className="font-mono">{param.metric}</span>
        </div>

        <p className="mb-4 text-sm text-ink">{param.rationale}</p>

        <div className="mb-4">
          <div className="mb-2 text-xs font-medium text-inkMuted">
            Where the current molecules sit vs. this criterion
          </div>
          <ParamHistogram metric={param.metric} />
        </div>

        <div className="rounded border border-border bg-panel p-4">
          <div className="mb-3 text-sm font-medium">Change this criterion</div>
          <div className="mb-3 flex items-center gap-2 text-sm">
            <select
              value={operator}
              onChange={(e) => setOperator(e.target.value)}
              className="rounded border border-borderStrong bg-bg px-2 py-1"
            >
              <option value="<">&lt; (lower is better)</option>
              <option value=">">&gt; (higher is better)</option>
            </select>
            <input
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              className="w-28 rounded border border-borderStrong bg-bg px-2 py-1 font-mono"
            />
            <span className="text-inkMuted">{param.units}</span>
          </div>

          <div className="mb-2 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-700">
            ⚠ Changing this updates the TPP <b>globally for this program</b> and creates a new
            version. All molecules are re-scored against it.
          </div>

          <label className="mb-1 block text-xs text-inkMuted">
            Justification (required — recorded on the new version)
          </label>
          <textarea
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            rows={3}
            placeholder="Why is this change warranted?"
            className="w-full rounded border border-borderStrong bg-bg p-2 text-sm"
          />

          {error && <div className="mt-2 text-xs text-red-600">{error}</div>}

          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={save}
              disabled={busy || !changed || !justification.trim()}
              className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save as new version"}
            </button>
            {!changed && <span className="text-xs text-inkFaint">No change yet</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
