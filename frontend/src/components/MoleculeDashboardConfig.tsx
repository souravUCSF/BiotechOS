"use client";

import { useEffect, useMemo, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import {
  fetchFoldConfig, setFoldConfig, fetchMetrics,
  type FoldTargetKind, type MetricDef,
} from "@/lib/api";

const TARGET_KINDS: { kind: FoldTargetKind; label: string; placeholder: string; hint: string }[] = [
  { kind: "pdb", label: "PDB ID", placeholder: "e.g. REF1",
    hint: "Fetches the reference structure from RCSB now." },
  { kind: "uniprot", label: "UniProt ID", placeholder: "e.g. P04626",
    hint: "Boltz folds from the UniProt sequence (co-fold pending)." },
  { kind: "sequence", label: "Protein sequence", placeholder: "MELAALCRW…",
    hint: "Boltz folds the pasted sequence directly (co-fold pending)." },
];

// group the metric catalog the same way the TPP builder does
function metricGroups(metrics: MetricDef[]): [string, MetricDef[]][] {
  return [
    ["Assays", metrics.filter((m) => m.kind === "assay" && !m.key.startsWith("cell:"))],
    ["Anti-proliferation by cell line", metrics.filter((m) => m.key.startsWith("cell:"))],
    ["Computed (ADME / physchem)", metrics.filter((m) => m.kind === "adme")],
    ["Derived (formulas)", metrics.filter((m) => m.kind === "formula")],
    ["Custom", metrics.filter((m) => m.kind === "custom")],
  ];
}

export function MoleculeDashboardConfig({
  cardFields,
  onCardFields,
  onClose,
}: {
  cardFields: string[];
  onCardFields: (fields: string[]) => void;
  onClose: () => void;
}) {
  const { programId } = useProgram();
  const [kind, setKind] = useState<FoldTargetKind>("pdb");
  const [targetValue, setTargetValue] = useState("");
  const [constraints, setConstraints] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [metrics, setMetrics] = useState<MetricDef[]>([]);

  useEffect(() => {
    fetchFoldConfig(programId).then((c) => {
      setKind(c.target_kind ?? "pdb");
      setTargetValue(c.target_value ?? c.pdb_id ?? "");
      setConstraints(c.constraints ?? "");
    });
    fetchMetrics(programId).then(setMetrics).catch(() => setMetrics([]));
  }, [programId]);

  const groups = useMemo(() => metricGroups(metrics), [metrics]);
  const active = TARGET_KINDS.find((t) => t.kind === kind)!;

  function toggleField(key: string) {
    onCardFields(
      cardFields.includes(key) ? cardFields.filter((f) => f !== key) : [...cardFields, key],
    );
  }

  async function save() {
    setSaving(true);
    try {
      await setFoldConfig(kind, targetValue, constraints, programId);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-lg border border-borderStrong bg-panel p-6"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Dashboard configuration</h2>
          <button onClick={onClose} className="text-inkMuted hover:text-ink">✕</button>
        </div>

        <div className="mb-5">
          <div className="mb-2 text-sm font-medium">Folding target</div>

          {/* kind selector */}
          <div className="mb-2 inline-flex rounded border border-borderStrong text-sm">
            {TARGET_KINDS.map((t) => (
              <button
                key={t.kind}
                onClick={() => setKind(t.kind)}
                className={`px-3 py-1 ${kind === t.kind ? "bg-emerald-600 text-white" : "text-ink"}`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <label className="mb-1 block text-xs text-inkMuted">
            {active.label} for Boltz co-folding
          </label>
          {kind === "sequence" ? (
            <textarea
              value={targetValue}
              onChange={(e) => setTargetValue(e.target.value)}
              rows={4}
              placeholder={active.placeholder}
              className="mb-1 w-full rounded border border-borderStrong bg-panel p-2 font-mono text-xs"
            />
          ) : (
            <input
              value={targetValue}
              onChange={(e) => setTargetValue(e.target.value)}
              placeholder={active.placeholder}
              className="mb-1 w-48 rounded border border-borderStrong bg-panel px-2 py-1.5 font-mono text-sm uppercase"
            />
          )}
          <div className="mb-3 text-xs text-inkFaint">{active.hint}</div>

          <label className="mb-1 block text-xs text-inkMuted">
            Folding constraints (optional — e.g. pocket residues, covalent warhead)
          </label>
          <textarea
            value={constraints}
            onChange={(e) => setConstraints(e.target.value)}
            rows={3}
            placeholder="e.g. constrain ligand to the ATP pocket near Cys805; hold the DFG-out conformation"
            className="w-full rounded border border-borderStrong bg-panel p-2 text-sm"
          />
          <div className="mt-2 flex items-center gap-3">
            <button onClick={save} disabled={saving || !targetValue.trim()}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
              {saving ? "Saving…" : saved ? "✓ Saved" : "Save folding target"}
            </button>
          </div>
        </div>

        <div className="border-t border-border pt-4">
          <div className="mb-2 text-sm font-medium">Data shown on molecule cards</div>
          <div className="space-y-3">
            {groups.map(([label, ms]) => ms.length > 0 && (
              <div key={label}>
                <div className="mb-1 text-xs font-medium text-inkMuted">{label}</div>
                <div className="grid grid-cols-2 gap-1.5 text-sm">
                  {ms.map((m) => (
                    <label key={m.key} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={cardFields.includes(m.key)}
                        onChange={() => toggleField(m.key)}
                      />
                      <span className="truncate" title={m.label}>{m.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
