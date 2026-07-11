"use client";

// Related-quote FYI. Fetches /quotes/groups directly (not via lib/api.ts) to stay
// isolated from concurrent edits to that file.
import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { API_BASE } from "@/lib/apiBase";

type Line = {
  line_id: number; document_id: number; vendor: string; service: string;
  compound: string | null; quantity: number | null; unit: string | null;
  amount: number; currency: string; turnaround_days: number | null;
  flagged: boolean; status: string; date: string | null; subject: string | null;
};
type Group = {
  bucket: string; label: string; line_count: number; vendor_count: number;
  min_amount: number; max_amount: number; vendors: string[]; lines: Line[];
};

const money = (n: number, ccy = "USD") =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: ccy, maximumFractionDigits: 0 }).format(n);

export default function QuotesPage() {
  const { programId } = useProgram();
  const [groups, setGroups] = useState<Group[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/quotes/groups?program_id=${programId}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => { setGroups(d.groups || []); setOpen((d.groups?.[0]?.bucket) ?? null); })
      .catch(() => setGroups([]))
      .finally(() => setLoading(false));
  }, [programId]);

  return (
    <div className="p-6">
      <div className="mb-1 flex items-baseline gap-3">
        <h1 className="text-lg font-semibold text-ink">Related quotes</h1>
        <span className="text-sm text-inkMuted">{groups.length} task areas with competing quotes</span>
      </div>
      <p className="mb-4 max-w-2xl text-sm text-inkMuted">
        Quotes grouped by the task they cover, so you can see at a glance where you already
        have multiple or related offers. Amounts are per the quote line&apos;s own quantity/unit —
        compare with that context, not the raw number.
      </p>

      {loading && <div className="text-sm text-inkMuted">Loading…</div>}
      {!loading && groups.length === 0 && (
        <div className="text-sm text-inkMuted">
          No task areas with 2+ vendor quotes yet. Run the quote backfill, then reload.
        </div>
      )}

      <div className="flex flex-col gap-3">
        {groups.map((g) => {
          const isOpen = open === g.bucket;
          return (
            <div key={g.bucket} className="rounded border border-border bg-panel">
              <button
                onClick={() => setOpen(isOpen ? null : g.bucket)}
                className="flex w-full items-center justify-between px-4 py-3 text-left"
              >
                <div className="flex items-center gap-3">
                  <span className="font-semibold text-ink">{g.label}</span>
                  <span className="text-xs text-inkMuted">
                    {g.vendor_count} vendors · {g.line_count} quote lines
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-ink">
                    {money(g.min_amount)} – {money(g.max_amount)}
                  </span>
                  <span className="text-inkMuted">{isOpen ? "−" : "+"}</span>
                </div>
              </button>

              {isOpen && (
                <div className="overflow-x-auto border-t border-border px-4 py-2">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-inkMuted">
                        <th className="py-1 pr-4">Vendor</th>
                        <th className="pr-4 text-right">Amount</th>
                        <th className="pr-4">Qty / unit</th>
                        <th className="pr-4">TAT</th>
                        <th className="pr-4">Quote line</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.lines.map((l) => (
                        <tr key={l.line_id} className="border-t border-border/60 align-top">
                          <td className="py-1 pr-4 font-medium text-ink">{l.vendor}</td>
                          <td className="pr-4 text-right whitespace-nowrap">
                            {money(l.amount, l.currency)}
                            {l.flagged && <span className="ml-1 text-amber-600" title="grounding check flagged">⚠</span>}
                          </td>
                          <td className="pr-4 whitespace-nowrap text-inkMuted">
                            {l.quantity != null ? `${l.quantity} ${l.unit ?? ""}` : (l.unit ?? "—")}
                          </td>
                          <td className="pr-4 whitespace-nowrap text-inkMuted">
                            {l.turnaround_days != null ? `${l.turnaround_days}d` : "—"}
                          </td>
                          <td className="pr-4 text-inkMuted">{l.service || "—"}</td>
                          <td className="whitespace-nowrap text-xs text-inkMuted" title={l.subject ?? ""}>
                            {l.date ? l.date.slice(0, 10) : ""} · doc {l.document_id}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
