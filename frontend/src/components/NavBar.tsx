"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ProgramSwitcher } from "./ProgramSwitcher";

const LINKS = [
  { href: "/", label: "Inbox" },
  { href: "/tpp-builder", label: "TPP" },
  { href: "/tpp", label: "Molecule Database" },
  { href: "/molecules", label: "Molecule Dashboard" },
  { href: "/competitive", label: "Competitive Radar" },
  { href: "/cfo", label: "CFO / Budget" },
  { href: "/ledger", label: "Decision Log" },
];

export function NavBar() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-10 flex items-center justify-between border-b border-neutral-800 bg-neutral-950 px-6 py-3">
      <div className="flex items-center gap-6">
        <span className="text-sm font-semibold tracking-wide text-neutral-100">BiotechOS</span>
        <nav className="flex gap-4">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`text-sm ${
                pathname === l.href
                  ? "text-white font-medium"
                  : "text-neutral-400 hover:text-neutral-200"
              }`}
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
      <ProgramSwitcher />
    </header>
  );
}
