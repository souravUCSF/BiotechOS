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
  if (!adme) return <div className="text-xs text-neutral-600">No ADME</div>;
  return (
    <div className="grid grid-cols-4 gap-2 text-xs">
      {FIELDS.map(([k]) => (
        <div key={k} className="rounded bg-neutral-800/60 px-2 py-1">
          <div className="text-[10px] text-neutral-500">{k}</div>
          <div className="font-mono text-neutral-200">{adme[k] ?? "—"}</div>
        </div>
      ))}
    </div>
  );
}
