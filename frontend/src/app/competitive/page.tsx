"use client";

import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { fetchCompetitive, type Radar, type RadarItem } from "@/lib/api";

function threatColor(t: number | null) {
  if (t == null) return "bg-neutral-700";
  if (t >= 0.75) return "bg-red-600";
  if (t >= 0.55) return "bg-amber-500";
  return "bg-neutral-600";
}

function ItemRow({ i }: { i: RadarItem }) {
  const inner = (
    <div className="flex items-start justify-between gap-3 rounded border border-neutral-800 bg-neutral-900 p-3 hover:bg-neutral-800/50">
      <div className="min-w-0">
        <div className="truncate text-sm text-neutral-200">{i.title}</div>
        <div className="mt-0.5 text-xs text-neutral-500">
          {[i.org, i.stage, i.status, i.event_date].filter(Boolean).join(" · ")}
          {i.source ? ` · ${i.source}` : ""}
        </div>
      </div>
      {i.threat_score != null && (
        <span className={`shrink-0 rounded px-2 py-0.5 text-xs text-white ${threatColor(i.threat_score)}`}>
          {(i.threat_score * 100).toFixed(0)}
        </span>
      )}
    </div>
  );
  return i.url ? (
    <a href={i.url} target="_blank" rel="noreferrer" className="block">{inner}</a>
  ) : (
    inner
  );
}

function Column({ title, items, hint }: { title: string; items: RadarItem[]; hint: string }) {
  const sorted = [...items].sort((a, b) => (b.threat_score ?? 0) - (a.threat_score ?? 0));
  return (
    <div>
      <div className="mb-1 text-sm font-semibold text-neutral-200">{title}</div>
      <div className="mb-2 text-xs text-neutral-500">{hint}</div>
      <div className="max-h-[520px] space-y-2 overflow-y-auto pr-1">
        {sorted.length === 0 ? (
          <div className="text-xs text-neutral-600">none</div>
        ) : (
          sorted.map((i, n) => <ItemRow key={n} i={i} />)
        )}
      </div>
    </div>
  );
}

function CatalystTimeline({ items }: { items: RadarItem[] }) {
  const dated = items
    .filter((i) => i.event_date)
    .sort((a, b) => (a.event_date! < b.event_date! ? -1 : 1))
    .slice(0, 10);
  if (!dated.length) return null;
  return (
    <div className="mb-8">
      <div className="mb-3 text-sm font-semibold text-neutral-200">
        Catalyst timeline — upcoming inflection points
      </div>
      <div className="relative border-l border-neutral-700 pl-5">
        {dated.map((i, n) => (
          <div key={n} className="relative mb-4">
            <div className={`absolute -left-[23px] top-1 h-2.5 w-2.5 rounded-full ${threatColor(i.threat_score)}`} />
            <div className="text-xs font-mono text-neutral-400">{i.event_date}</div>
            <div className="text-sm text-neutral-200">{i.title}</div>
            <div className="text-xs text-neutral-500">{[i.org, i.stage].filter(Boolean).join(" · ")}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function CompetitivePage() {
  const { programId } = useProgram();
  const [radar, setRadar] = useState<Radar | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCompetitive(programId).then(setRadar).catch((e) => setError(String(e)));
  }, [programId]);

  if (error) return <p className="text-red-400">Error: {error}</p>;
  if (!radar) return <p className="text-neutral-400">Loading radar…</p>;

  return (
    <div>
      <div className="mb-4 flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Competitive Radar</h1>
        <span className="text-xs text-neutral-500">
          {radar.live ? "live" : "cached"} · ClinicalTrials.gov + PubMed + curated ·{" "}
          {new Date(radar.generated_at).toLocaleString()}
        </span>
      </div>

      <CatalystTimeline items={radar.axes.catalyst} />

      <div className="grid gap-6 md:grid-cols-4">
        <Column title="Competing programs" items={radar.axes.program}
          hint="Same target / mechanism, by stage" />
        <Column title="Clinical catalysts" items={radar.axes.catalyst}
          hint="Readouts & completion dates" />
        <Column title="Financings" items={radar.axes.financing}
          hint="Funding = momentum" />
        <Column title="News & deals" items={radar.axes.news}
          hint="Partnerships, approvals, disclosures" />
      </div>
    </div>
  );
}
