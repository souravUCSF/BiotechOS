import type { Molecule } from "./types";

// A comparable scalar property extracted from a molecule's assays + ADME.
export type PropertyDef = {
  key: string;
  label: string;
  log: boolean; // display on log axis (concentration / ratio properties)
  units?: string;
};

export const PROPERTIES: PropertyDef[] = [
  { key: "tgta_ic50", label: "TGTA IC50", log: true, units: "nM" },
  { key: "tgtb_ic50", label: "TGTB IC50", log: true, units: "nM" },
  { key: "selectivity", label: "TGTA/TGTB selectivity", log: true, units: "x" },
  { key: "cell_ic50", label: "Cellular anti-prolif", log: true, units: "nM" },
  { key: "MW", label: "MW", log: false, units: "" },
  { key: "cLogP", label: "cLogP", log: false, units: "" },
  { key: "TPSA", label: "TPSA", log: false, units: "" },
  { key: "QED", label: "QED", log: false, units: "" },
  { key: "HBD", label: "HBD", log: false, units: "" },
  { key: "HBA", label: "HBA", log: false, units: "" },
  { key: "RotB", label: "Rotatable bonds", log: false, units: "" },
];

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function assayMedian(mol: Molecule, modality: string, target?: string): number | null {
  const vals = mol.assays
    .filter((a) => a.modality === modality && (!target || a.target === target) && a.value != null)
    .map((a) => a.value as number);
  return median(vals);
}

export function moleculeProperties(mol: Molecule): Record<string, number | null> {
  const adme = mol.adme ?? {};
  return {
    tgta_ic50: assayMedian(mol, "biochemical_ic50", "TGTA"),
    tgtb_ic50: assayMedian(mol, "biochemical_ic50", "TGTB"),
    selectivity: assayMedian(mol, "selectivity"),
    cell_ic50: assayMedian(mol, "cellular_antiprolif", "TGTA"),
    MW: adme.MW ?? null,
    cLogP: adme.cLogP ?? null,
    TPSA: adme.TPSA ?? null,
    QED: adme.QED ?? null,
    HBD: adme.HBD ?? null,
    HBA: adme.HBA ?? null,
    RotB: adme.RotB ?? null,
  };
}

export const propLabel = (key: string) =>
  PROPERTIES.find((p) => p.key === key)?.label ?? key;
export const propDef = (key: string) => PROPERTIES.find((p) => p.key === key);
