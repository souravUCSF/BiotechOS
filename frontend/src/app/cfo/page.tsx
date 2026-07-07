"use client";

import { useEffect, useState } from "react";
import { useProgram } from "@/lib/ProgramContext";
import { fetchBudget, type BudgetResponse } from "@/lib/api";

const usd = (v: number) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

const STATUS_STYLE: Record<string, string> = {
  issued: "bg-blue-800 text-white",
  closed: "bg-emerald-700 text-white",
  draft: "bg-neutral-700 text-neutral-200",
  paid: "bg-emerald-700 text-white",
  matched: "bg-emerald-700 text-white",
  mismatch: "bg-red-700 text-white",
  received: "bg-neutral-700 text-neutral-200",
  ordered: "bg-blue-800 text-white",
};

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded border border-neutral-800 bg-neutral-900 p-4">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
      {sub && <div className="text-xs text-neutral-500">{sub}</div>}
    </div>
  );
}

export default function CfoPage() {
  const { programId } = useProgram();
  const [data, setData] = useState<BudgetResponse | null>(null);

  useEffect(() => {
    fetchBudget(programId).then(setData).catch(() => setData(null));
    const t = setInterval(() => fetchBudget(programId).then(setData).catch(() => {}), 3000);
    return () => clearInterval(t);
  }, [programId]);

  if (!data) return <p className="text-neutral-400">Loading…</p>;
  const b = data.budget;

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">CFO / Budget</h1>
      <p className="mb-6 text-sm text-neutral-400">
        Committed-vs-actual budget, PO pipeline, and runway — updated live as the
        procurement loop runs. Approve quotes and reconcile invoices in the Inbox.
      </p>

      <div className="mb-8 grid gap-4 md:grid-cols-5">
        <Stat label="Total budget" value={usd(b.total)} />
        <Stat label="Committed" value={usd(b.committed)} sub="encumbered by open POs" />
        <Stat label="Actual spend" value={usd(b.actual)} sub="paid / reconciled" />
        <Stat label="Available" value={usd(b.available)} sub="total − committed − actual" />
        <Stat label="Runway" value={b.runway_months != null ? `${b.runway_months} mo` : "—"}
          sub={`burn ${usd(b.monthly_burn)}/mo`} />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h2 className="mb-2 text-sm font-semibold text-neutral-300">Purchase orders</h2>
          <div className="overflow-hidden rounded border border-neutral-800">
            <table className="w-full text-left text-sm">
              <thead className="bg-neutral-900 text-neutral-400">
                <tr><th className="px-3 py-2">PO</th><th className="px-3 py-2">Vendor</th>
                  <th className="px-3 py-2">Amount</th><th className="px-3 py-2">Status</th></tr>
              </thead>
              <tbody>
                {data.purchase_orders.length === 0 ? (
                  <tr><td colSpan={4} className="px-3 py-3 text-neutral-600">No POs yet — approve a quote.</td></tr>
                ) : data.purchase_orders.map((po) => (
                  <tr key={po.id} className="border-t border-neutral-800">
                    <td className="px-3 py-2 font-mono text-xs">{po.po_number}</td>
                    <td className="px-3 py-2">{po.vendor_name}</td>
                    <td className="px-3 py-2 font-mono">{usd(po.amount)}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[po.status] ?? "bg-neutral-700"}`}>{po.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <h2 className="mb-2 text-sm font-semibold text-neutral-300">Invoices</h2>
          <div className="overflow-hidden rounded border border-neutral-800">
            <table className="w-full text-left text-sm">
              <thead className="bg-neutral-900 text-neutral-400">
                <tr><th className="px-3 py-2">Amount</th><th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Match</th></tr>
              </thead>
              <tbody>
                {data.invoices.length === 0 ? (
                  <tr><td colSpan={3} className="px-3 py-3 text-neutral-600">No invoices yet.</td></tr>
                ) : data.invoices.map((inv) => (
                  <tr key={inv.id} className="border-t border-neutral-800">
                    <td className="px-3 py-2 font-mono">{usd(inv.amount)}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[inv.status] ?? "bg-neutral-700"}`}>{inv.status}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-neutral-400">{inv.match_notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
