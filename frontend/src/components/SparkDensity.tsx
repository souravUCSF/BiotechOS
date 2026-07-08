"use client";

import { useEffect, useState } from "react";
import { fetchHistogram, type Histogram } from "@/lib/api";
import { useProgram } from "@/lib/ProgramContext";

const fmt = (v: number) =>
  v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v >= 10 ? v.toFixed(0) : v.toFixed(1);

// smooth path through points using a Catmull-Rom -> cubic Bezier conversion
function smoothPath(pts: [number, number][]): string {
  if (pts.length < 2) return "";
  let d = `M ${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${c1x},${c1y} ${c2x},${c2y} ${p2[0]},${p2[1]}`;
  }
  return d;
}

export function SparkDensity({
  metric,
  label,
  width = 260,
  height = 56,
}: {
  metric: string;
  label?: string;
  width?: number;
  height?: number;
}) {
  const { programId } = useProgram();
  const [hist, setHist] = useState<Histogram | null>(null);

  useEffect(() => {
    fetchHistogram(metric, programId).then(setHist).catch(() => setHist(null));
  }, [metric, programId]);

  if (!hist || hist.counts.length === 0) return null;

  const n = hist.counts.length;
  const max = Math.max(...hist.counts, 1);
  const pad = 2;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const pts: [number, number][] = hist.counts.map((c, i) => [
    pad + (i / (n - 1)) * innerW,
    pad + innerH - (c / max) * innerH,
  ]);
  const line = smoothPath(pts);
  const area = `${line} L ${pad + innerW},${pad + innerH} L ${pad},${pad + innerH} Z`;

  // threshold x position
  let tx: number | null = null;
  if (hist.threshold != null) {
    for (let i = 0; i < n; i++) {
      if (hist.threshold >= hist.edges[i] && hist.threshold < hist.edges[i + 1]) {
        const frac = (hist.threshold - hist.edges[i]) / (hist.edges[i + 1] - hist.edges[i]);
        tx = pad + ((i + frac) / (n - 1)) * innerW;
        break;
      }
    }
  }

  return (
    <div className="inline-block select-none">
      {label && <div className="mb-0.5 text-[10px] uppercase tracking-wide text-inkFaint">{label}</div>}
      <svg width={width} height={height} className="block">
        <path d={area} fill="var(--color-accent)" fillOpacity={0.12} />
        <path d={line} fill="none" stroke="var(--color-accent)" strokeWidth={1.5} />
        {tx != null && (
          <line x1={tx} y1={pad} x2={tx} y2={height - pad} stroke="#d97706" strokeWidth={1} strokeDasharray="2 2" />
        )}
      </svg>
      <div className="flex justify-between text-[9px] text-inkFaint" style={{ width }}>
        <span>{fmt(hist.edges[0])}{hist.units}</span>
        {hist.threshold != null && <span className="text-amber-600">TPP {hist.operator} {fmt(hist.threshold)}</span>}
        <span>{fmt(hist.edges[hist.edges.length - 1])}{hist.units}{hist.log_scale ? " (log)" : ""}</span>
      </div>
    </div>
  );
}
