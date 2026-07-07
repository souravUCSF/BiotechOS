"use client";

import { useAppState } from "@/lib/useAppState";

export default function InboxPage() {
  const { state, error, loading } = useAppState();

  if (loading) return <p className="text-neutral-400">Loading…</p>;
  if (error) return <p className="text-red-400">Error: {error}</p>;
  if (!state) return null;

  return (
    <div className="max-w-4xl">
      <h1 className="mb-1 text-xl font-semibold">Monday-morning Inbox</h1>
      <p className="mb-6 text-sm text-neutral-400">
        {state.program.name} · {state.molecules.length} active molecules loaded
      </p>

      {state.inbox_items.length === 0 ? (
        <div className="rounded border border-dashed border-neutral-700 p-8 text-center text-neutral-500">
          No inbox items yet — the Day 4 inbox loop will populate this from
          held-out CRO datasets.
        </div>
      ) : (
        <ul className="space-y-3">
          {state.inbox_items.map((item) => (
            <li
              key={item.id}
              className="rounded border border-neutral-800 bg-neutral-900 p-4"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{item.title}</span>
                <span className="text-xs uppercase text-neutral-500">
                  {item.kind}
                </span>
              </div>
              {item.summary && (
                <p className="mt-1 text-sm text-neutral-400">{item.summary}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
