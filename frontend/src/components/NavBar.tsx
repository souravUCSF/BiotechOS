"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ProgramSwitcher } from "./ProgramSwitcher";
import { useProgram } from "@/lib/ProgramContext";
import { API_BASE } from "@/lib/apiBase";

const LINKS = [
  { href: "/mailbox", label: "Inbox" },
  { href: "/simulation", label: "Simulation" },
  { href: "/query", label: "QueryOS" },
  { href: "/quotes", label: "Quotes" },
  { href: "/tpp-builder", label: "TPP" },
  { href: "/tpp", label: "Molecule Database" },
  { href: "/registry", label: "Registry" },
  { href: "/molecules", label: "Molecule Dashboard" },
  { href: "/cfo", label: "CFO / Budget" },
  { href: "/ledger", label: "Logs" },
];

export function NavBar() {
  const pathname = usePathname();
  const { programId } = useProgram();
  const [regCount, setRegCount] = useState(0);

  useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/registry/candidates?program_id=${programId}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!alive || !d) return;
        const n = Array.isArray(d) ? d.length : (d.candidates?.length ?? d.count ?? 0);
        setRegCount(n);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [programId, pathname]);

  return (
    <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-panel px-6 py-3">
      <div className="flex items-center gap-6">
        <span className="text-sm font-semibold tracking-wide text-ink">BiotechOS</span>
        <nav className="flex gap-4">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`text-sm ${
                pathname === l.href
                  ? "text-ink font-semibold"
                  : "text-inkMuted hover:text-ink"
              }`}
            >
              {l.label}
              {l.href === "/registry" && regCount > 0 && (
                <span className="ml-1 rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
                  {regCount}
                </span>
              )}
            </Link>
          ))}
        </nav>
      </div>
      <ProgramSwitcher />
    </header>
  );
}
