"use client";

import { useEffect, useState } from "react";
import { fetchHistogram, type Histogram } from "@/lib/api";
import { useProgram } from "@/lib/ProgramContext";

const fmt = (v: number) =>
  v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v >= 10 ? v.toFixed(0) : v.toFixed(2);

export function InteractiveHistogram({
  metric,
  selectedBin,
  onSelectBin,
  onData,
  height = 120,
}: {
  metric: string;
  selectedBin: number | null;
  onSelectBin: (bin: number | null, memberIds: number[]) => void;
  onData?: (hist: Histogram) => void;
  height?: number;
}) {
  const { programId } = useProgram();
  const [hist, setHist] = useState<Histogram | null>(null);

  useEffect(() => {
    fetchHistogram(metric, programId)
      .then((h) => {
        setHist(h);
        onData?.(h);
      })
      .catch(() => setHist(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metric, programId]);

  if (!hist || hist.counts.length === 0)
    return <div className="text-xs text-neutral-600">No distribution for this property yet.</div>;

  const max = Math.max(...hist.counts, 1);
  let thresholdBin = -1;
  if (hist.threshold != null) {
    for (let i = 0; i < hist.counts.length; i++) {
      if (hist.threshold >= hist.edges[i] && hist.threshold < hist.edges[i + 1]) {
        thresholdBin = i;
        break;
      }
    }
  }

  function clickBar(i: number) {
    if (selectedBin === i) {
      onSelectBin(null, []);
    } else {
      const ids = (hist!.members ?? []).filter((m) => m.bin === i).map((m) => m.molecule_id);
      onSelectBin(i, ids);
    }
  }

  return (
    <div>
      <div className="flex items-end gap-[2px]" style={{ height }}>
        {hist.counts.map((c, i) => {
          const onPassSide =
            hist.threshold != null &&
            (hist.operator === "<"
              ? hist.edges[i + 1] <= hist.threshold
              : hist.edges[i] >= hist.threshold);
          const isSel = selectedBin === i;
          return (
            <button
              key={i}
              onClick={() => clickBar(i)}
              className="relative flex-1 cursor-pointer"
              title={`${fmt(hist.edges[i])}–${fmt(hist.edges[i + 1])}${hist.units ?? ""}: ${c} molecule${c === 1 ? "" : "s"} — click to filter`}
            >
              <div
                className={`w-full rounded-t transition-colors ${
                  isSel
                    ? "bg-blue-400"
                    : onPassSide
                      ? "bg-emerald-600 hover:bg-emerald-500"
                      : "bg-neutral-600 hover:bg-neutral-500"
                }`}
                style={{ height: `${(c / max) * (height - 8)}px` }}
              />
              {i === thresholdBin && (
                <div className="absolute inset-y-0 left-0 w-[2px] bg-amber-400" />
              )}
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-neutral-500">
        <span>{fmt(hist.edges[0])}{hist.units}</span>
        {hist.threshold != null && (
          <span className="text-amber-400">
            TPP {hist.operator} {fmt(hist.threshold)}{hist.units}
          </span>
        )}
        <span>
          {fmt(hist.edges[hist.edges.length - 1])}{hist.units}
          {hist.log_scale ? " (log)" : ""}
        </span>
      </div>
    </div>
  );
}
