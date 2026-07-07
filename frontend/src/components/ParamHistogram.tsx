"use client";

import { useEffect, useState } from "react";
import { fetchHistogram, type Histogram } from "@/lib/api";
import { useProgram } from "@/lib/ProgramContext";

const fmt = (v: number) =>
  v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v >= 10 ? v.toFixed(0) : v.toFixed(1);

export function ParamHistogram({ metric }: { metric: string }) {
  const { programId } = useProgram();
  const [hist, setHist] = useState<Histogram | null>(null);

  useEffect(() => {
    fetchHistogram(metric, programId).then(setHist).catch(() => setHist(null));
  }, [metric, programId]);

  if (!hist || hist.counts.length === 0)
    return <div className="h-16 text-xs text-neutral-600">no distribution</div>;

  const max = Math.max(...hist.counts);
  // find which bin the threshold falls into (edges has counts.length + 1 entries)
  let thresholdBin = -1;
  if (hist.threshold != null) {
    for (let i = 0; i < hist.counts.length; i++) {
      if (hist.threshold >= hist.edges[i] && hist.threshold < hist.edges[i + 1]) {
        thresholdBin = i;
        break;
      }
    }
  }

  return (
    <div>
      <div className="flex h-16 items-end gap-[2px]">
        {hist.counts.map((c, i) => {
          // color bars on the passing side of the threshold green, failing side neutral
          const onPassSide =
            hist.threshold != null &&
            (hist.operator === "<"
              ? hist.edges[i + 1] <= hist.threshold
              : hist.edges[i] >= hist.threshold);
          return (
            <div
              key={i}
              className="relative flex-1"
              title={`${fmt(hist.edges[i])}–${fmt(hist.edges[i + 1])}${
                hist.units ?? ""
              }: ${c}`}
            >
              <div
                className={`w-full rounded-t ${
                  onPassSide ? "bg-emerald-600" : "bg-neutral-600"
                }`}
                style={{ height: `${max ? (c / max) * 56 : 0}px` }}
              />
              {i === thresholdBin && (
                <div className="absolute inset-y-0 left-0 w-[2px] bg-amber-400" />
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-neutral-500">
        <span>
          {fmt(hist.edges[0])}
          {hist.units}
        </span>
        {hist.threshold != null && (
          <span className="text-amber-400">
            TPP {hist.operator} {fmt(hist.threshold)}
            {hist.units}
          </span>
        )}
        <span>
          {fmt(hist.edges[hist.edges.length - 1])}
          {hist.units}
          {hist.log_scale ? " (log)" : ""}
        </span>
      </div>
    </div>
  );
}
