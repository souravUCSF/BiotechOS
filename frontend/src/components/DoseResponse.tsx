"use client";

import type { Rederivation } from "@/lib/api";

const W = 380;
const H = 240;
const PAD = 40;

export function DoseResponse({ rederiv }: { rederiv: Rederivation }) {
  if (!rederiv.has_curve || !rederiv.raw_points || !rederiv.fit) return null;
  const { concentration_nM: conc, pct_inhibition: resp } = rederiv.raw_points;
  const logs = conc.map((c) => Math.log10(c));
  const xlo = Math.min(...logs), xhi = Math.max(...logs);
  const ylo = Math.min(0, ...resp), yhi = Math.max(100, ...resp);

  const sx = (lx: number) => PAD + ((lx - xlo) / (xhi - xlo)) * (W - PAD - 12);
  const sy = (y: number) => H - PAD - ((y - ylo) / (yhi - ylo)) * (H - PAD - 12);

  const { bottom, top, ic50, hill } = rederiv.fit;
  const fourPL = (x: number) => bottom + (top - bottom) / (1 + (x / ic50) ** hill);
  const curve: string = Array.from({ length: 60 }, (_, i) => {
    const lx = xlo + (i / 59) * (xhi - xlo);
    const x = 10 ** lx;
    return `${i === 0 ? "M" : "L"} ${sx(lx).toFixed(1)} ${sy(fourPL(x)).toFixed(1)}`;
  }).join(" ");

  return (
    <div>
      <svg width={W} height={H} className="rounded border border-neutral-800 bg-neutral-950">
        <line x1={PAD} y1={H - PAD} x2={W - 12} y2={H - PAD} stroke="#404040" />
        <line x1={PAD} y1={12} x2={PAD} y2={H - PAD} stroke="#404040" />
        <text x={(W + PAD) / 2} y={H - 8} fill="#a3a3a3" fontSize="10" textAnchor="middle">
          [compound] nM (log)
        </text>
        <text x={12} y={(H - PAD) / 2} fill="#a3a3a3" fontSize="10" textAnchor="middle"
          transform={`rotate(-90 12 ${(H - PAD) / 2})`}>% inhibition</text>

        {/* re-fitted curve */}
        <path d={curve} fill="none" stroke="#34d399" strokeWidth="2" />
        {/* raw points */}
        {conc.map((c, i) => (
          <circle key={i} cx={sx(Math.log10(c))} cy={sy(resp[i])} r={3} fill="#60a5fa" />
        ))}

        {/* fitted IC50 (green) vs reported IC50 (amber) verticals */}
        {rederiv.fitted_ic50 && (
          <line x1={sx(Math.log10(rederiv.fitted_ic50))} y1={12} x2={sx(Math.log10(rederiv.fitted_ic50))}
            y2={H - PAD} stroke="#34d399" strokeDasharray="3 2" />
        )}
        {rederiv.reported_ic50 && (
          <line x1={sx(Math.log10(rederiv.reported_ic50))} y1={12} x2={sx(Math.log10(rederiv.reported_ic50))}
            y2={H - PAD} stroke="#f59e0b" strokeDasharray="3 2" />
        )}
      </svg>
      <div className="mt-2 flex gap-4 text-xs">
        <span className="text-emerald-400">● re-derived IC50 {rederiv.fitted_ic50} nM (R²={rederiv.fit.r2})</span>
        <span className="text-amber-400">● reported IC50 {rederiv.reported_ic50} nM</span>
      </div>
    </div>
  );
}
