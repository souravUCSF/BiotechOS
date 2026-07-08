"use client";

import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { fetchFoldConfig, setFoldConfig } from "@/lib/api";

export const CARD_FIELD_OPTIONS: { key: string; label: string; units: string }[] = [
  { key: "tgta_ic50", label: "TGTA IC50", units: "nM" },
  { key: "selectivity", label: "Selectivity", units: "x" },
  { key: "cell_ic50", label: "Cellular", units: "nM" },
  { key: "tgtb_ic50", label: "TGTB IC50", units: "nM" },
  { key: "QED", label: "QED", units: "" },
  { key: "MW", label: "MW", units: "" },
  { key: "cLogP", label: "cLogP", units: "" },
  { key: "TPSA", label: "TPSA", units: "" },
];

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
  const [pdbId, setPdbId] = useState("");
  const [constraints, setConstraints] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchFoldConfig(programId).then((c) => {
      setPdbId(c.pdb_id ?? "");
      setConstraints(c.constraints ?? "");
    });
  }, [programId]);

  function toggleField(key: string) {
    onCardFields(
      cardFields.includes(key) ? cardFields.filter((f) => f !== key) : [...cardFields, key],
    );
  }

  async function save() {
    setSaving(true);
    try {
      await setFoldConfig(pdbId, constraints, programId);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="w-full max-w-lg rounded-lg border border-borderStrong bg-panel p-6"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Dashboard configuration</h2>
          <button onClick={onClose} className="text-inkMuted hover:text-ink">✕</button>
        </div>

        <div className="mb-5">
          <div className="mb-2 text-sm font-medium">Folding target</div>
          <label className="mb-1 block text-xs text-inkMuted">
            Protein / PDB ID for Boltz co-folding
          </label>
          <input
            value={pdbId}
            onChange={(e) => setPdbId(e.target.value)}
            placeholder="e.g. REF1"
            className="mb-3 w-40 rounded border border-borderStrong bg-panel px-2 py-1.5 font-mono text-sm uppercase"
          />
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
            <button onClick={save} disabled={saving || !pdbId.trim()}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
              {saving ? "Saving…" : saved ? "✓ Saved" : "Save folding target"}
            </button>
            <span className="text-xs text-inkFaint">
              Sets the reference structure now; used for co-folds when Boltz is enabled.
            </span>
          </div>
        </div>

        <div className="border-t border-border pt-4">
          <div className="mb-2 text-sm font-medium">Data shown on molecule cards</div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            {CARD_FIELD_OPTIONS.map((f) => (
              <label key={f.key} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={cardFields.includes(f.key)}
                  onChange={() => toggleField(f.key)}
                />
                {f.label}
              </label>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
