"use client";

import { useMemo, useState } from "react";
import type { Molecule } from "@/lib/types";
import { PROPERTIES, moleculeProperties, propDef } from "@/lib/properties";

const W = 640;
const H = 420;
const PAD = 56;

function scale(v: number, lo: number, hi: number, a: number, b: number) {
  if (hi === lo) return (a + b) / 2;
  return a + ((v - lo) / (hi - lo)) * (b - a);
}

export function PropertyScatter({
  molecules,
  onSelect,
  highlight,
}: {
  molecules: Molecule[];
  onSelect?: (id: number) => void;
  highlight?: Set<number>;
}) {
  const [xKey, setXKey] = useState("tgta_ic50");
  const [yKey, setYKey] = useState("selectivity");

  const xDef = propDef(xKey)!;
  const yDef = propDef(yKey)!;

  const points = useMemo(() => {
    return molecules
      .map((m) => {
        const props = moleculeProperties(m);
        const xv = props[xKey];
        const yv = props[yKey];
        if (xv == null || yv == null || xv <= 0 || yv <= 0) return null;
        return { id: m.id, name: m.name, x: xv, y: yv };
      })
      .filter((p): p is { id: number; name: string; x: number; y: number } => p !== null);
  }, [molecules, xKey, yKey]);

  const xs = points.map((p) => (xDef.log ? Math.log10(p.x) : p.x));
  const ys = points.map((p) => (yDef.log ? Math.log10(p.y) : p.y));
  const xlo = Math.min(...xs), xhi = Math.max(...xs);
  const ylo = Math.min(...ys), yhi = Math.max(...ys);

  const fmt = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v >= 10 ? v.toFixed(0) : v.toFixed(2));

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
        <label className="text-inkMuted">
          X:{" "}
          <select
            value={xKey}
            onChange={(e) => setXKey(e.target.value)}
            className="rounded border border-borderStrong bg-panel px-2 py-1 text-ink"
          >
            {PROPERTIES.map((p) => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
          </select>
        </label>
        <label className="text-inkMuted">
          Y:{" "}
          <select
            value={yKey}
            onChange={(e) => setYKey(e.target.value)}
            className="rounded border border-borderStrong bg-panel px-2 py-1 text-ink"
          >
            {PROPERTIES.map((p) => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
          </select>
        </label>
        <span className="text-xs text-inkFaint">{points.length} molecules with both properties</span>
      </div>

      <svg width={W} height={H} className="rounded border border-border bg-bg">
        {/* axes */}
        <line x1={PAD} y1={H - PAD} x2={W - 12} y2={H - PAD} stroke="#cbd3df" />
        <line x1={PAD} y1={12} x2={PAD} y2={H - PAD} stroke="#cbd3df" />
        <text x={(W + PAD) / 2} y={H - 16} fill="#5b6472" fontSize="12" textAnchor="middle">
          {xDef.label} {xDef.units} {xDef.log ? "(log)" : ""}
        </text>
        <text x={16} y={(H - PAD) / 2} fill="#5b6472" fontSize="12" textAnchor="middle"
          transform={`rotate(-90 16 ${(H - PAD) / 2})`}>
          {yDef.label} {yDef.units} {yDef.log ? "(log)" : ""}
        </text>
        {/* axis min/max ticks */}
        <text x={PAD} y={H - PAD + 16} fill="#8a94a3" fontSize="10" textAnchor="middle">{fmt(Math.min(...points.map(p=>p.x)))}</text>
        <text x={W - 12} y={H - PAD + 16} fill="#8a94a3" fontSize="10" textAnchor="end">{fmt(Math.max(...points.map(p=>p.x)))}</text>
        <text x={PAD - 6} y={H - PAD} fill="#8a94a3" fontSize="10" textAnchor="end">{fmt(Math.min(...points.map(p=>p.y)))}</text>
        <text x={PAD - 6} y={18} fill="#8a94a3" fontSize="10" textAnchor="end">{fmt(Math.max(...points.map(p=>p.y)))}</text>

        {points.map((p) => {
          const px = scale(xDef.log ? Math.log10(p.x) : p.x, xlo, xhi, PAD, W - 12);
          const py = scale(yDef.log ? Math.log10(p.y) : p.y, ylo, yhi, H - PAD, 12);
          const hot = highlight?.has(p.id);
          return (
            <g key={p.id} className="cursor-pointer" onClick={() => onSelect?.(p.id)}>
              <circle cx={px} cy={py} r={hot ? 6 : 4}
                fill={hot ? "#34d399" : "#60a5fa"}
                fillOpacity={hot ? 1 : 0.7} stroke="#f7f9fb" />
              <title>{`${p.name}: ${xDef.label} ${fmt(p.x)}${xDef.units}, ${yDef.label} ${fmt(p.y)}${yDef.units}`}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
