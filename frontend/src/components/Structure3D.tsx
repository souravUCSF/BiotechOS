"use client";

import { useEffect, useRef, useState } from "react";

import { API_BASE } from "@/lib/apiBase";
import { useProgram } from "@/lib/ProgramContext";

// 3Dmol is loaded from CDN on demand.
declare global {
  interface Window {
    $3Dmol?: {
      createViewer: (el: HTMLElement, opts: Record<string, unknown>) => Viewer;
    };
  }
}
type Viewer = {
  addModel: (data: string, fmt: string) => void;
  setStyle: (sel: Record<string, unknown>, style: Record<string, unknown>) => void;
  zoomTo: () => void;
  render: () => void;
  clear: () => void;
  resize: () => void;
  spin: (axis: boolean | string) => void;
};

function ensure3Dmol(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.$3Dmol) return resolve();
    // add the tag once; multiple callers (StrictMode double-mount) share it
    if (!document.querySelector(`script[src="${src}"]`)) {
      const s = document.createElement("script");
      s.src = src;
      s.onerror = () => reject(new Error(`failed to load ${src}`));
      document.head.appendChild(s);
    }
    // resolve only when the global is actually available, not just when the tag exists
    const started = Date.now();
    const poll = setInterval(() => {
      if (window.$3Dmol) {
        clearInterval(poll);
        resolve();
      } else if (Date.now() - started > 10000) {
        clearInterval(poll);
        reject(new Error("3Dmol did not initialize"));
      }
    }, 50);
  });
}

/** Generic 3Dmol viewer: fetches structure text from `url`, renders protein cartoon +
 *  ligand sticks, optionally auto-spins. Header X-Structure-Format picks the parser. */
export function MolViewer({ url, className = "h-64", spin = false, defaultFormat = "pdb" }:
  { url: string; className?: string; spin?: boolean; defaultFormat?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [label, setLabel] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setState("loading");
      const res = await fetch(url);
      if (!res.ok) { if (!cancelled) setState("error"); return; }
      if (!cancelled) setLabel(res.headers.get("X-Structure-Label") ?? "");
      const fmt = res.headers.get("X-Structure-Format") ?? defaultFormat;
      const text = await res.text();
      try {
        await ensure3Dmol("https://cdn.jsdelivr.net/npm/3dmol@2.4.2/build/3Dmol-min.js");
      } catch { if (!cancelled) setState("error"); return; }
      if (cancelled || !ref.current || !window.$3Dmol) return;
      try {
        const viewer = window.$3Dmol.createViewer(ref.current, { backgroundColor: "#f7f9fb" });
        viewer.addModel(text, fmt);
        viewer.setStyle({}, { cartoon: { color: "spectrum" } });
        viewer.setStyle({ hetflag: true }, { stick: { colorscheme: "greenCarbon" } });
        viewer.zoomTo();
        viewer.render();
        viewer.resize();
        if (spin) viewer.spin("y");
        if (!cancelled) setState("ready");
      } catch (e) {
        console.error("3Dmol render failed:", e);
        if (!cancelled) setState("error");
      }
    })();
    return () => { cancelled = true; };
  }, [url, spin, defaultFormat]);

  return (
    <div className={`relative ${className} w-full overflow-hidden rounded border border-border bg-bg`}>
      <div ref={ref} className="absolute inset-0" />
      {state === "ready" && label && (
        <div className="absolute bottom-1 left-2 text-[10px] text-inkMuted">{label}</div>
      )}
      {state !== "ready" && (
        <div className="absolute inset-0 flex items-center justify-center text-center text-xs text-inkMuted">
          {state === "loading" && "Loading structure…"}
          {state === "error" && "Structure unavailable"}
        </div>
      )}
    </div>
  );
}

export function Structure3D({ moleculeId, className = "h-64" }: { moleculeId: number; className?: string }) {
  const { programId } = useProgram();
  return <MolViewer url={`${API_BASE}/molecule/${moleculeId}/structure3d?program_id=${programId}`} className={className} />;
}
