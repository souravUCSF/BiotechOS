"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { fetchQuote, type Quotation } from "@/lib/api";
import { useProgram } from "@/lib/ProgramContext";

const BLUE = "#4472c4";
const num = (v: number) => (v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const dateStr = (iso: string) => (iso ? new Date(iso).toLocaleDateString() : "");

// A vendor quotation rendered as a document from its parsed fields (prints to PDF).
export default function QuotePage() {
  const { id } = useParams<{ id: string }>();
  const docId = Number(id);
  const { programId } = useProgram();
  const router = useRouter();
  const [q, setQ] = useState<Quotation | null>(null);
  const [err, setErr] = useState(false);

  const load = useCallback(() => {
    fetchQuote(docId, programId).then(setQ).catch(() => setErr(true));
  }, [docId, programId]);
  useEffect(load, [load]);

  if (err) return <div className="p-8 text-sm text-inkMuted">Quotation not found.</div>;
  if (!q) return <div className="p-8 text-sm text-inkMuted">Loading…</div>;

  const subtotal = q.line_items.reduce((s, li) => s + (Number(li.amount) || 0), 0);
  const total = q.amount ?? subtotal;

  return (
    <div className="mx-auto max-w-4xl p-6">
      {/* toolbar (hidden in print) */}
      <div className="no-print mb-4 flex items-center gap-2">
        <button onClick={() => router.back()} className="rounded border border-border px-3 py-1.5 text-sm text-ink">← Back</button>
        <div className="text-sm text-inkMuted">Vendor quotation — {q.quote_ref || q.subject}</div>
        <button onClick={() => window.print()} className="ml-auto rounded border border-border px-3 py-1.5 text-sm text-ink">⬇ Download PDF</button>
      </div>

      {/* ===== QUOTATION DOCUMENT (prints to PDF) ===== */}
      <div id="quote-doc" className="bg-white p-8 text-[13px] text-black shadow-sm">
        {/* header */}
        <div className="flex items-start justify-between">
          <div className="w-72">
            <div className="text-2xl font-semibold">{q.vendor}</div>
            <div className="text-zinc-700">{q.vendor_email}</div>
          </div>
          <div className="text-right">
            <div className="text-3xl font-extrabold tracking-wide" style={{ color: BLUE }}>QUOTATION</div>
            <table className="ml-auto mt-3">
              <tbody>
                <tr><td className="pr-3 text-right text-zinc-600">QUOTE #</td>
                  <td className="border border-zinc-400 px-3 text-center min-w-24">{q.quote_ref || "—"}</td></tr>
                <tr><td className="pr-3 text-right text-zinc-600">DATE</td>
                  <td className="border border-zinc-400 px-3 text-center">{dateStr(q.dated)}</td></tr>
                {q.valid && <tr><td className="pr-3 text-right text-zinc-600">VALID</td>
                  <td className="border border-zinc-400 px-3 text-center">{q.valid}</td></tr>}
              </tbody>
            </table>
          </div>
        </div>

        {/* prepared for */}
        <div className="mt-6 grid grid-cols-2 gap-6">
          <div>
            <div className="px-2 py-1 text-xs font-bold text-white" style={{ background: BLUE }}>PREPARED FOR</div>
            <div className="bg-zinc-50 p-2 text-zinc-800">
              <div className="font-medium">{q.buyer.name}</div>
              <div>Attn: {q.buyer.contact}</div>
              {q.buyer.addr.map((l, i) => <div key={i}>{l}</div>)}
              <div>{q.buyer.email}</div>
            </div>
          </div>
          <div>
            <div className="px-2 py-1 text-xs font-bold text-white" style={{ background: BLUE }}>SCOPE</div>
            <div className="bg-zinc-50 p-2 text-zinc-700">
              <div>{q.subject}</div>
              {q.turnaround && <div className="mt-1">Turnaround: {q.turnaround}</div>}
            </div>
          </div>
        </div>

        {/* line items */}
        <table className="mt-4 w-full border-collapse">
          <thead>
            <tr className="text-white text-xs font-bold" style={{ background: BLUE }}>
              <th className="w-14 border border-zinc-300 py-1">ITEM #</th>
              <th className="border border-zinc-300 py-1 text-left px-2">DESCRIPTION</th>
              <th className="w-14 border border-zinc-300 py-1">QTY</th>
              <th className="w-32 border border-zinc-300 py-1">AMOUNT</th>
            </tr>
          </thead>
          <tbody>
            {q.line_items.map((li, i) => (
              <tr key={i}>
                <td className="border border-zinc-300 px-2 text-center">{i + 1}</td>
                <td className="border border-zinc-300 px-2">{li.description}</td>
                <td className="border border-zinc-300 px-1 text-center">{li.quantity ?? "—"}</td>
                <td className="border border-zinc-300 px-2 text-right">{num(Number(li.amount) || 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* total */}
        <div className="mt-5 flex justify-end">
          <table className="self-start">
            <tbody>
              <tr><td className="py-1 pr-6 text-right text-zinc-600">SUBTOTAL</td>
                <td className="border border-zinc-300 px-3 text-right min-w-32">{num(subtotal)}</td></tr>
              <tr className="font-bold"><td className="py-1 pr-6 text-right">TOTAL</td>
                <td className="border border-zinc-300 px-3 text-right text-white" style={{ background: BLUE }}>$ {num(total)}</td></tr>
            </tbody>
          </table>
        </div>

        <div className="mt-8 text-center text-xs text-zinc-600">
          This quotation was parsed from the vendor email into a structured document.
          Prices are fixed for the validity period shown. Create a PO from the inbox to proceed.
        </div>
      </div>
    </div>
  );
}
