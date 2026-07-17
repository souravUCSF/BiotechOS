"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchMoleculeValues, type MetricDef, type MoleculeValues } from "@/lib/api";
import { API_BASE } from "@/lib/apiBase";

const W = 640;
const H = 420;
const PAD = 56;

function scale(v: number, lo: number, hi: number, a: number, b: number) {
  if (hi === lo) return (a + b) / 2;
  return a + ((v - lo) / (hi - lo)) * (b - a);
}

type Pt = { id: number; name: string; x: number; y: number; px: number; py: number };

// X/Y axis options come from the SAME program metric catalog the "All molecules"
// table uses (fetchMetrics → metrics), so the two are always in sync — including
// assays, ADME, cell lines and Boltz-predicted metrics.
export function PropertyScatter({
  programId,
  metrics,
  onSelect,
  highlight,
  externalHoverId,
  onHoverId,
  onBrush,
}: {
  programId: string;
  metrics: MetricDef[];
  onSelect?: (id: number) => void;
  highlight?: Set<number>;
  externalHoverId?: number | null;
  onHoverId?: (id: number | null) => void;
  onBrush?: (ids: number[]) => void;
}) {
  const [xKey, setXKey] = useState("");
  const [yKey, setYKey] = useState("");
  const [rows, setRows] = useState<MoleculeValues[]>([]);
  const [hovered, setHovered] = useState<Pt | null>(null);
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // pick sensible defaults from the catalog (potency vs selectivity), and repair
  // the selection whenever the program (and thus the catalog) changes.
  useEffect(() => {
    if (metrics.length === 0) return;
    const keys = new Set(metrics.map((m) => m.key));
    setXKey((prev) => {
      if (keys.has(prev)) return prev;
      const potency = metrics.find((m) => /ic50/i.test(m.key) || /ic50/i.test(m.label)) ?? metrics[0];
      return potency.key;
    });
    setYKey((prev) => {
      if (keys.has(prev)) return prev;
      const sel = metrics.find((m) => /selectiv/i.test(m.key) || /selectiv/i.test(m.label))
        ?? metrics.find((m) => !/ic50/i.test(m.key)) ?? metrics[Math.min(1, metrics.length - 1)];
      return sel.key;
    });
  }, [metrics]);

  // fetch per-molecule values for just the two selected axes
  useEffect(() => {
    if (!xKey || !yKey) { setRows([]); return; }
    const keys = Array.from(new Set([xKey, yKey]));
    fetchMoleculeValues(keys, programId).then(setRows).catch(() => setRows([]));
  }, [xKey, yKey, programId]);

  const xDef = metrics.find((m) => m.key === xKey);
  const yDef = metrics.find((m) => m.key === yKey);

  const raw = useMemo(() => {
    if (!xDef || !yDef) return [] as { id: number; name: string; x: number; y: number }[];
    return rows
      .map((r) => {
        const xv = r.values[xKey];
        const yv = r.values[yKey];
        if (xv == null || yv == null) return null;
        if (xDef.log && xv <= 0) return null;
        if (yDef.log && yv <= 0) return null;
        return { id: r.molecule_id, name: r.name, x: xv, y: yv };
      })
      .filter((p): p is { id: number; name: string; x: number; y: number } => p !== null);
  }, [rows, xKey, yKey, xDef, yDef]);

  const xs = raw.map((p) => (xDef?.log ? Math.log10(p.x) : p.x));
  const ys = raw.map((p) => (yDef?.log ? Math.log10(p.y) : p.y));
  const xlo = Math.min(...xs), xhi = Math.max(...xs);
  const ylo = Math.min(...ys), yhi = Math.max(...ys);

  const pts: Pt[] = raw.map((p) => ({
    ...p,
    px: scale(xDef?.log ? Math.log10(p.x) : p.x, xlo, xhi, PAD, W - 12),
    py: scale(yDef?.log ? Math.log10(p.y) : p.y, ylo, yhi, H - PAD, 12),
  }));

  const fmt = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v >= 10 ? v.toFixed(0) : v.toFixed(2));
  const units = (d?: MetricDef) => (d?.units ? ` ${d.units}` : "");

  function toSvg(e: React.MouseEvent) {
    const r = svgRef.current!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
  }
  function onDown(e: React.MouseEvent) { const { x, y } = toSvg(e); setDrag({ x0: x, y0: y, x1: x, y1: y }); }
  function onMove(e: React.MouseEvent) { if (!drag) return; const { x, y } = toSvg(e); setDrag({ ...drag, x1: x, y1: y }); }
  function onUp() {
    if (!drag) return;
    if (Math.abs(drag.x1 - drag.x0) > 4 || Math.abs(drag.y1 - drag.y0) > 4) {
      const xmin = Math.min(drag.x0, drag.x1), xmax = Math.max(drag.x0, drag.x1);
      const ymin = Math.min(drag.y0, drag.y1), ymax = Math.max(drag.y0, drag.y1);
      const ids = pts.filter((p) => p.px >= xmin && p.px <= xmax && p.py >= ymin && p.py <= ymax).map((p) => p.id);
      onBrush?.(ids);
    }
    setDrag(null);
  }

  const brushRect = drag
    ? { x: Math.min(drag.x0, drag.x1), y: Math.min(drag.y0, drag.y1),
        w: Math.abs(drag.x1 - drag.x0), h: Math.abs(drag.y1 - drag.y0) }
    : null;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
        <label className="text-inkMuted">
          X:{" "}
          <select value={xKey} onChange={(e) => setXKey(e.target.value)}
            className="rounded border border-borderStrong bg-panel px-2 py-1 text-ink">
            {metrics.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
        </label>
        <label className="text-inkMuted">
          Y:{" "}
          <select value={yKey} onChange={(e) => setYKey(e.target.value)}
            className="rounded border border-borderStrong bg-panel px-2 py-1 text-ink">
            {metrics.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
        </label>
        <span className="text-xs text-inkFaint">
          {pts.length} molecules · drag to select, hover for structure
        </span>
      </div>

      <div className="relative inline-block">
        <svg
          ref={svgRef}
          width={W}
          height={H}
          className="rounded border border-border bg-bg"
          onMouseDown={onDown}
          onMouseMove={onMove}
          onMouseUp={onUp}
          onMouseLeave={() => { setDrag(null); setHovered(null); onHoverId?.(null); }}
        >
          <line x1={PAD} y1={H - PAD} x2={W - 12} y2={H - PAD} stroke="#cbd3df" />
          <line x1={PAD} y1={12} x2={PAD} y2={H - PAD} stroke="#cbd3df" />
          <text x={(W + PAD) / 2} y={H - 16} fill="#5b6472" fontSize="12" textAnchor="middle">
            {xDef?.label ?? ""}{units(xDef)} {xDef?.log ? "(log)" : ""}
          </text>
          <text x={16} y={(H - PAD) / 2} fill="#5b6472" fontSize="12" textAnchor="middle"
            transform={`rotate(-90 16 ${(H - PAD) / 2})`}>
            {yDef?.label ?? ""}{units(yDef)} {yDef?.log ? "(log)" : ""}
          </text>
          {pts.length > 0 && (
            <>
              <text x={PAD} y={H - PAD + 16} fill="#8a94a3" fontSize="10" textAnchor="middle">{fmt(Math.min(...pts.map((p) => p.x)))}</text>
              <text x={W - 12} y={H - PAD + 16} fill="#8a94a3" fontSize="10" textAnchor="end">{fmt(Math.max(...pts.map((p) => p.x)))}</text>
              <text x={PAD - 6} y={H - PAD} fill="#8a94a3" fontSize="10" textAnchor="end">{fmt(Math.min(...pts.map((p) => p.y)))}</text>
              <text x={PAD - 6} y={18} fill="#8a94a3" fontSize="10" textAnchor="end">{fmt(Math.max(...pts.map((p) => p.y)))}</text>
            </>
          )}
          {pts.length === 0 && (
            <text x={(W + PAD) / 2} y={H / 2} fill="#8a94a3" fontSize="12" textAnchor="middle">
              No molecules have values for both selected properties.
            </text>
          )}

          {brushRect && (
            <rect x={brushRect.x} y={brushRect.y} width={brushRect.w} height={brushRect.h}
              fill="#3b82f6" fillOpacity={0.1} stroke="#3b82f6" strokeDasharray="3 2" />
          )}

          {pts.map((p) => {
            const isHot = highlight?.has(p.id);
            const isHover = hovered?.id === p.id || externalHoverId === p.id;
            return (
              <circle
                key={p.id}
                cx={p.px}
                cy={p.py}
                r={isHover ? 7 : isHot ? 6 : 4}
                fill={isHover ? "#f59e0b" : isHot ? "#059669" : "#3b82f6"}
                fillOpacity={isHover ? 1 : 0.75}
                stroke="#ffffff"
                className="cursor-pointer"
                onMouseEnter={() => { setHovered(p); onHoverId?.(p.id); }}
                onMouseLeave={() => { setHovered(null); onHoverId?.(null); }}
                onClick={() => onSelect?.(p.id)}
              />
            );
          })}
        </svg>

        {/* hover tooltip: molecule id + 2D structure */}
        {hovered && (
          <div
            className="pointer-events-none absolute z-20 rounded border border-borderStrong bg-panel p-2 shadow-lg"
            style={{ left: Math.min(hovered.px + 12, W - 150), top: Math.max(hovered.py - 130, 4) }}
          >
            <div className="mb-1 text-xs font-medium text-ink">{hovered.name}</div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`${API_BASE}/molecule/${hovered.id}/structure2d`} alt="" className="h-24 w-32 object-contain" />
            <div className="mt-1 text-[10px] text-inkMuted">
              {xDef?.label} {fmt(hovered.x)}{units(xDef)} · {yDef?.label} {fmt(hovered.y)}{units(yDef)}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
