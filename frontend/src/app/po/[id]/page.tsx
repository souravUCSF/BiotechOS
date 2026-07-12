"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  fetchPO, updatePO, approvePO,
  type PurchaseOrder, type POLineItem,
} from "@/lib/api";
import { API_BASE } from "@/lib/apiBase";

const BLUE = "#4472c4";
const num = (v: number) => (v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// small badge shown on fields auto-filled from the knowledge base (hidden in print)
const KbChip = () => (
  <span className="kb-hint no-print ml-1 align-middle rounded bg-amber-200 px-1 text-[9px] font-semibold text-amber-800">from KB</span>
);

// Buyer (our company) block, from the PO's program — matches the Program A PO template.
const BUYER: Record<string, { name: string; addr: string[]; phone: string; contact: string; email: string }> = {
  demo: {
    name: "Example A Bio", addr: ["100 Example Ave", "San Francisco, CA 94100"],
    phone: "(555) 010-0100", contact: "Jordan Lee", email: "founder@example-a.com",
  },
  program-b: {
    name: "Example B Bio", addr: ["100 Example Ave", "San Francisco, CA 94100"],
    phone: "(555) 010-0100", contact: "Jordan Lee", email: "founder@example-b.com",
  },
};

export default function POPage() {
  const { id } = useParams<{ id: string }>();
  const poId = Number(id);
  const [po, setPo] = useState<PurchaseOrder | null>(null);
  const [items, setItems] = useState<POLineItem[]>([]);
  const [vendor, setVendor] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState<string | null>(null);

  // template fields not (yet) persisted by the API — local to the document
  const [vendorAddr, setVendorAddr] = useState("");
  const [shipVia, setShipVia] = useState("TBD");
  const [requisitioner, setRequisitioner] = useState("");
  const [fob, setFob] = useState("");
  const [shipTerms, setShipTerms] = useState("");
  const [discount, setDiscount] = useState(0);
  const [shipping, setShipping] = useState(0);
  const [other, setOther] = useState(0);
  const [comments, setComments] = useState("Invoice to: ap@example-a.com");
  // buyer (our company) details — sourced from the KB, editable, saved back
  const [buyerAddr, setBuyerAddr] = useState("");
  const [buyerPhone, setBuyerPhone] = useState("");
  // which fields were auto-filled from the KB (for the highlight)
  const [kb, setKb] = useState<Record<string, boolean>>({});

  const load = useCallback(() => {
    fetchPO(poId).then((p) => {
      setPo(p); setItems(p.line_items); setVendor(p.vendor_name ?? ""); setDirty(false);
    }).catch(() => setPo(null));
  }, [poId]);
  useEffect(load, [load]);

  // pull company (buyer) profile from the KB, falling back to the template defaults
  useEffect(() => {
    if (!po) return;
    const b = BUYER[po.program_id] ?? BUYER.demo;
    fetch(`${API_BASE}/kb/details?program_id=${po.program_id}&entity_type=company&name=${encodeURIComponent(b.name)}`)
      .then((r) => r.json())
      .then((d) => {
        const f = d.fields || {};
        setBuyerAddr((prev) => prev || (f.address?.value ?? b.addr.join("\n")));
        setBuyerPhone((prev) => prev || (f.phone?.value ?? b.phone));
        setKb((k) => ({ ...k, "buyer.address": !!f.address, "buyer.phone": !!f.phone }));
      })
      .catch(() => { setBuyerAddr((p) => p || b.addr.join("\n")); setBuyerPhone((p) => p || b.phone); });
  }, [po]);

  // when the vendor is set and its address is missing, fill it from the KB (highlighted)
  useEffect(() => {
    if (!po || !vendor.trim() || vendorAddr.trim()) return;
    const ctrl = new AbortController();
    fetch(`${API_BASE}/kb/details?program_id=${po.program_id}&entity_type=vendor&name=${encodeURIComponent(vendor)}`,
      { signal: ctrl.signal })
      .then((r) => r.json())
      .then((d) => {
        const addr = d.fields?.address?.value;
        if (addr) { setVendorAddr(addr); setKb((k) => ({ ...k, "vendor.address": true })); }
      })
      .catch(() => {});
    return () => ctrl.abort();
  }, [po, vendor, vendorAddr]);

  // persist reusable profile info back to the KB so it auto-fills next time
  async function saveKb() {
    if (!po) return;
    const b = BUYER[po.program_id] ?? BUYER.demo;
    const posts: Promise<Response>[] = [];
    const post = (entity_type: string, name: string, fields: Record<string, string>) =>
      posts.push(fetch(`${API_BASE}/kb/details`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ program_id: po.program_id, entity_type, name, fields }),
      }));
    if (vendor.trim() && vendorAddr.trim()) post("vendor", vendor.trim(), { address: vendorAddr.trim() });
    const cf: Record<string, string> = {};
    if (buyerAddr.trim()) cf.address = buyerAddr.trim();
    if (buyerPhone.trim()) cf.phone = buyerPhone.trim();
    if (Object.keys(cf).length) post("company", b.name, cf);
    await Promise.all(posts).catch(() => {});
  }

  const editable = po?.status === "draft";
  const subtotal = items.reduce((s, li) => s + (Number(li.amount) || 0), 0);
  const total = subtotal - (discount || 0) + (shipping || 0) + (other || 0);

  function setItem(i: number, patch: Partial<POLineItem>) {
    setItems((xs) => xs.map((li, j) => (j === i ? { ...li, ...patch } : li))); setDirty(true);
  }
  function setUnitPrice(i: number, unitPrice: number) {
    const qty = Number(items[i].quantity) || 1;
    setItem(i, { amount: +(unitPrice * qty).toFixed(2) });
  }
  function setQty(i: number, qty: number | null) {
    const up = unitPriceOf(items[i]);
    setItems((xs) => xs.map((li, j) => (j === i ? { ...li, quantity: qty, amount: +(up * (qty || 1)).toFixed(2) } : li)));
    setDirty(true);
  }
  const unitPriceOf = (li: POLineItem) => {
    const q = Number(li.quantity) || 1;
    return q ? (Number(li.amount) || 0) / q : (Number(li.amount) || 0);
  };
  function removeItem(i: number) { setItems((xs) => xs.filter((_, j) => j !== i)); setDirty(true); }
  function addItem() { setItems((xs) => [...xs, { description: "", amount: 0, quantity: 1 }]); setDirty(true); }

  async function save() {
    setBusy(true);
    try { const p = await updatePO(poId, items, vendor); setPo(p); setItems(p.line_items); setDirty(false); await saveKb(); }
    finally { setBusy(false); }
  }
  async function approve() {
    setBusy(true);
    try {
      if (dirty) await updatePO(poId, items, vendor);
      await saveKb();
      const r = await approvePO(poId); setEmail(r.email); load();
    } finally { setBusy(false); }
  }
  // amber highlight + reset on edit for KB-sourced fields
  const kbCls = (key: string) => (kb[key] ? " kb-src bg-amber-50 ring-1 ring-amber-300 rounded" : "");
  const clearKb = (key: string) => setKb((k) => ({ ...k, [key]: false }));

  if (!po) return <div className="p-6 text-sm text-inkMuted">Loading PO…</div>;

  const buyer = BUYER[po.program_id] ?? BUYER.demo;
  const poNumber = po.po_number ?? "(draft)";   // number is assigned only on issue
  const dateStr = new Date(po.approved_at ?? Date.now()).toLocaleDateString("en-US",
    { month: "numeric", day: "numeric", year: "2-digit" });
  const inp = "w-full bg-transparent text-black outline-none";
  const ed = editable ? "focus:bg-blue-50" : "";
  // pad to a minimum number of visible rows like the spreadsheet template
  const emptyRows = Math.max(0, 12 - items.length);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <style>{`
        @media print {
          body * { visibility: hidden; }
          #po-doc, #po-doc * { visibility: visible; }
          #po-doc { position: absolute; left: 0; top: 0; width: 100%; box-shadow: none !important; }
          .no-print, .kb-hint { display: none !important; }
          /* KB highlight is a UI hint only — print the value cleanly */
          #po-doc .kb-src { background: transparent !important; box-shadow: none !important; }
        }
      `}</style>

      {/* actions — not printed */}
      <div className="no-print mb-4 flex items-center gap-2">
        <Link href="/cfo" className="rounded border border-border px-3 py-1.5 text-sm text-ink">← Finance</Link>
        {editable && (
          <>
            <button onClick={save} disabled={busy || !dirty}
              className="rounded border border-border px-3 py-1.5 text-sm text-ink disabled:opacity-40">Save draft</button>
            <button onClick={approve} disabled={busy}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40">Approve &amp; issue PO</button>
          </>
        )}
        <button onClick={() => window.print()}
          className="ml-auto rounded border border-border px-3 py-1.5 text-sm text-ink">⬇ Download PDF</button>
      </div>

      {/* ===== PURCHASE ORDER DOCUMENT (matches template; prints to PDF) ===== */}
      <div id="po-doc" className="bg-white p-8 text-[13px] text-black shadow-sm">
        {/* header */}
        <div className="flex items-start justify-between">
          <div className="w-72">
            <div className="text-2xl font-semibold">{buyer.name}</div>
            <textarea value={buyerAddr} disabled={!editable} rows={2} placeholder="Address"
              onChange={(e) => { setBuyerAddr(e.target.value); clearKb("buyer.address"); }}
              className={`${inp} ${ed} resize-none text-zinc-700${kbCls("buyer.address")}`} />
            {kb["buyer.address"] && <KbChip />}
            <div className="text-zinc-700">
              Phone:{" "}
              <input value={buyerPhone} disabled={!editable}
                onChange={(e) => { setBuyerPhone(e.target.value); clearKb("buyer.phone"); }}
                className={`inline w-40 bg-transparent text-zinc-700 outline-none${kbCls("buyer.phone")}`} />
              {kb["buyer.phone"] && <KbChip />}
            </div>
            <div className="mt-2 text-zinc-700">Website:</div>
          </div>
          <div className="text-right">
            <div className="text-3xl font-extrabold tracking-wide" style={{ color: BLUE }}>PURCHASE ORDER</div>
            <table className="ml-auto mt-3">
              <tbody>
                <tr><td className="pr-3 text-right text-zinc-600">DATE</td>
                  <td className="border border-zinc-400 px-3 text-center min-w-24">{dateStr}</td></tr>
                <tr><td className="pr-3 text-right text-zinc-600">PO #</td>
                  <td className="border border-zinc-400 px-3 text-center">{poNumber}</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* VENDOR + SHIP TO */}
        <div className="mt-6 grid grid-cols-2 gap-6">
          <div>
            <div className="px-2 py-1 text-xs font-bold text-white" style={{ background: BLUE }}>VENDOR</div>
            <div className="bg-zinc-50 p-2">
              <input value={vendor} disabled={!editable} placeholder="Vendor name"
                onChange={(e) => { setVendor(e.target.value); setDirty(true); }} className={`${inp} ${ed} font-medium`} />
              <textarea value={vendorAddr} disabled={!editable} placeholder="Street&#10;City, State ZIP&#10;Country" rows={3}
                onChange={(e) => { setVendorAddr(e.target.value); clearKb("vendor.address"); }}
                className={`${inp} ${ed} resize-none text-zinc-700${kbCls("vendor.address")}`} />
              {kb["vendor.address"] && <KbChip />}
            </div>
          </div>
          <div>
            <div className="px-2 py-1 text-xs font-bold text-white" style={{ background: BLUE }}>SHIP TO</div>
            <div className="bg-zinc-50 p-2 text-zinc-800">
              <div className="font-medium">{buyer.name}</div>
              <div>Contact: {buyer.contact}</div>
              {(buyerAddr || buyer.addr.join("\n")).split("\n").map((l, i) => <div key={i}>{l}</div>)}
              <div>Phone: {buyerPhone || buyer.phone}</div>
            </div>
          </div>
        </div>

        {/* requisitioner / ship via / fob / shipping terms */}
        <div className="mt-4 grid grid-cols-4 text-center text-white text-xs font-bold" style={{ background: BLUE }}>
          <div className="py-1">REQUISITIONER</div><div className="py-1">SHIP VIA</div>
          <div className="py-1">F.O.B.</div><div className="py-1">SHIPPING TERMS</div>
        </div>
        <div className="grid grid-cols-4 border-x border-b border-zinc-300 text-center">
          <input value={requisitioner} disabled={!editable} onChange={(e) => setRequisitioner(e.target.value)} className={`${inp} ${ed} border-r border-zinc-300 px-2 py-1 text-center`} />
          <input value={shipVia} disabled={!editable} onChange={(e) => setShipVia(e.target.value)} className={`${inp} ${ed} border-r border-zinc-300 px-2 py-1 text-center`} />
          <input value={fob} disabled={!editable} onChange={(e) => setFob(e.target.value)} className={`${inp} ${ed} border-r border-zinc-300 px-2 py-1 text-center`} />
          <input value={shipTerms} disabled={!editable} onChange={(e) => setShipTerms(e.target.value)} className={`${inp} ${ed} px-2 py-1 text-center`} />
        </div>

        {/* line items */}
        <table className="mt-4 w-full border-collapse">
          <thead>
            <tr className="text-white text-xs font-bold" style={{ background: BLUE }}>
              <th className="w-14 border border-zinc-300 py-1">ITEM #</th>
              <th className="border border-zinc-300 py-1 text-left px-2">DESCRIPTION</th>
              <th className="w-14 border border-zinc-300 py-1">QTY</th>
              <th className="w-28 border border-zinc-300 py-1">UNIT PRICE</th>
              <th className="w-28 border border-zinc-300 py-1">TOTAL</th>
              {editable && <th className="w-6 no-print" />}
            </tr>
          </thead>
          <tbody>
            {items.map((li, i) => (
              <tr key={i}>
                <td className="border border-zinc-300 px-2 text-center">{i + 1}</td>
                <td className="border border-zinc-300 px-2">
                  <input value={li.description} disabled={!editable} placeholder="Description"
                    onChange={(e) => setItem(i, { description: e.target.value })} className={`${inp} ${ed}`} />
                </td>
                <td className="border border-zinc-300 px-1 text-center">
                  <input value={li.quantity ?? ""} disabled={!editable}
                    onChange={(e) => setQty(i, e.target.value ? Number(e.target.value) : null)} className={`${inp} ${ed} text-center`} />
                </td>
                <td className="border border-zinc-300 px-2 text-right">
                  {editable
                    ? <input type="number" defaultValue={unitPriceOf(li).toFixed(2)}
                        onChange={(e) => setUnitPrice(i, Number(e.target.value))} className={`${inp} ${ed} text-right`} />
                    : num(unitPriceOf(li))}
                </td>
                <td className="border border-zinc-300 px-2 text-right">{num(Number(li.amount) || 0)}</td>
                {editable && (
                  <td className="no-print pl-1 text-center">
                    <button onClick={() => removeItem(i)} className="text-zinc-400 hover:text-red-500">✕</button>
                  </td>
                )}
              </tr>
            ))}
            {Array.from({ length: emptyRows }).map((_, i) => (
              <tr key={`e${i}`} className="text-zinc-300">
                <td className="border border-zinc-300 px-2 text-center">{items.length + i + 1}</td>
                <td className="border border-zinc-300">&nbsp;</td>
                <td className="border border-zinc-300" /><td className="border border-zinc-300" />
                <td className="border border-zinc-300 px-2 text-right">-</td>
                {editable && <td className="no-print" />}
              </tr>
            ))}
          </tbody>
        </table>
        {editable && <button onClick={addItem} className="no-print mt-1 text-xs text-sky-600 hover:underline">+ add line</button>}

        {/* comments + totals */}
        <div className="mt-5 grid grid-cols-2 gap-6">
          <div>
            <div className="bg-zinc-200 px-2 py-1 text-xs font-bold text-zinc-700">Comments or Special Instructions</div>
            <textarea value={comments} disabled={!editable} rows={4} onChange={(e) => setComments(e.target.value)}
              className={`${inp} ${ed} border border-zinc-300 p-2 text-zinc-700`} />
          </div>
          <table className="self-start">
            <tbody>
              <tr><td className="py-1 pr-6 text-right text-zinc-600">SUBTOTAL</td><td className="border border-zinc-300 px-3 text-right min-w-28">{num(subtotal)}</td></tr>
              <tr><td className="py-1 pr-6 text-right text-zinc-600">Discount</td>
                <td className="border border-zinc-300 px-3 text-right">
                  {editable ? <input type="number" value={discount || ""} onChange={(e) => setDiscount(Number(e.target.value))} className={`${inp} text-right`} /> : (discount ? `(${num(discount)})` : "-")}
                </td></tr>
              <tr><td className="py-1 pr-6 text-right text-zinc-600">SHIPPING</td>
                <td className="border border-zinc-300 px-3 text-right">
                  {editable ? <input type="number" value={shipping || ""} onChange={(e) => setShipping(Number(e.target.value))} className={`${inp} text-right`} /> : (shipping ? num(shipping) : "-")}
                </td></tr>
              <tr><td className="py-1 pr-6 text-right text-zinc-600">OTHER</td>
                <td className="border border-zinc-300 px-3 text-right">
                  {editable ? <input type="number" value={other || ""} onChange={(e) => setOther(Number(e.target.value))} className={`${inp} text-right`} /> : (other ? num(other) : "-")}
                </td></tr>
              <tr className="font-bold"><td className="py-1 pr-6 text-right">TOTAL</td>
                <td className="border border-zinc-300 px-3 text-right text-white" style={{ background: BLUE }}>$ {num(total)}</td></tr>
            </tbody>
          </table>
        </div>

        <div className="mt-8 text-center text-xs text-zinc-600">
          If you have any questions about this purchase order, please contact
          <div>[{buyer.contact}, {buyer.phone.replace(/[()\s]/g, "").replace(/^/, "")}, {buyer.email}]</div>
        </div>
      </div>

      {email && (
        <div className="no-print mt-4 rounded border border-emerald-500/30 bg-panel p-3">
          <div className="mb-1 text-xs font-semibold text-emerald-800">Drafted vendor email (simulated — not sent)</div>
          <div className="whitespace-pre-wrap text-sm text-ink">{email}</div>
        </div>
      )}
    </div>
  );
}
