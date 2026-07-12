"use client";

import Link from "next/link";

const SECTIONS: { href: string; label: string; blurb: string }[] = [
  { href: "/mailbox", label: "Inbox", blurb: "One company email, auto-sorted into quotes, invoices, legal, data & other — smart processing and ingest." },
  { href: "/registry", label: "Registry", blurb: "Approve new compounds before their data enters the database." },
  { href: "/tpp-builder", label: "TPP", blurb: "Define the Target Product Profile your molecules are measured against." },
  { href: "/moleculedb", label: "Molecule Database", blurb: "Every registered compound with its data and TPP pass/fail." },
  { href: "/molecules", label: "Molecule Dashboard", blurb: "Deep-dive your molecules: AI structure+ADME, view program data, compare molecules." },
  { href: "/modeling", label: "Modeling", blurb: "Contact maps and Boltz-generated novel molecules for a pocket." },
  { href: "/cfo", label: "Budget", blurb: "POs, invoices, commitments and reconciliation in one view." },
  { href: "/query", label: "QueryOS", blurb: "Ask in plain English; get cited answers from your program's data." },
  { href: "/ledger", label: "Logs", blurb: "An immutable record of every decision and action." },
];

const WORKFLOWS: { title: string; steps: string }[] = [
  { title: "Data intake", steps: "Email from CRO (text, attachements) → QC extraction → Approval → Database" },
  { title: "Procurement", steps: "Email with Quote → PO → Invoice → Reconcile → Budget updates" },
  { title: "Legal review", steps: "Email with Contract → Claude legal review → Execute + store" },
  { title: "Compound registration", steps: "New compound → Registry gate → Folded and active in Molecule Database" },
  { title: "Define & score", steps: "Build a TPP by yourself or with Claude → Molecules auto-scored pass / fail" },
  { title: "Structure modeling Loop", steps: "Co-fold → Contact map → Generate novel analogs → Test the best" },
  { title: "Ask anything", steps: "QueryOS answers with citations across the whole corpus" },
];

export default function Home() {
  return (
    <div className="max-w-5xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-ink">BiotechOS</h1>
        <p className="mt-1 text-sm text-inkMuted">The operating system for a drug-discovery program — inbox to modeling, one loop.</p>
      </div>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-inkMuted">Sections</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {SECTIONS.map((s) => (
            <Link key={s.href} href={s.href}
              className="group rounded-lg border border-border bg-panel p-3 transition hover:border-emerald-500/50 hover:bg-panel2">
              <div className="text-sm font-semibold text-ink group-hover:text-emerald-700">{s.label}</div>
              <div className="mt-1 text-xs text-inkMuted">{s.blurb}</div>
            </Link>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-inkMuted">Workflows</h2>
        <div className="divide-y divide-border rounded-lg border border-border bg-panel">
          {WORKFLOWS.map((w) => (
            <div key={w.title} className="flex flex-col gap-0.5 p-3 sm:flex-row sm:items-baseline sm:gap-4">
              <div className="w-44 shrink-0 text-sm font-medium text-ink">{w.title}</div>
              <div className="font-mono text-xs text-inkMuted">{w.steps}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
