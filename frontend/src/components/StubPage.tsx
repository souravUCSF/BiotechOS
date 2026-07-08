"use client";

export function StubPage({ title, day }: { title: string; day: string }) {
  return (
    <div className="max-w-4xl">
      <h1 className="mb-1 text-xl font-semibold">{title}</h1>
      <div className="mt-6 rounded border border-dashed border-borderStrong p-8 text-center text-inkMuted">
        Coming in {day}.
      </div>
    </div>
  );
}
