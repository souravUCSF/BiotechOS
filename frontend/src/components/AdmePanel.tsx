"use client";

const FIELDS: [string, string][] = [
  ["MW", ""],
  ["cLogP", ""],
  ["TPSA", ""],
  ["QED", ""],
  ["HBD", ""],
  ["HBA", ""],
  ["RotB", ""],
  ["LipinskiViolations", ""],
];

export function AdmePanel({ adme }: { adme: Record<string, number> | null | undefined }) {
  if (!adme) return <div className="text-xs text-inkFaint">No ADME</div>;
  return (
    <div className="grid grid-cols-4 gap-2 text-xs">
      {FIELDS.map(([k]) => (
        <div key={k} className="rounded bg-panel2 px-2 py-1">
          <div className="text-[10px] text-inkMuted">{k}</div>
          <div className="font-mono text-ink">{adme[k] ?? "—"}</div>
        </div>
      ))}
    </div>
  );
}
