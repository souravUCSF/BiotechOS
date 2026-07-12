"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { fetchPrograms } from "./api";
import type { Program } from "./types";

type Ctx = {
  programId: string;
  setProgramId: (id: string) => void;
  programs: Program[];
};

const ProgramCtx = createContext<Ctx | null>(null);

export function ProgramProvider({ children }: { children: ReactNode }) {
  const [programId, setProgramId] = useState<string>("kras");
  const [programs, setPrograms] = useState<Program[]>([]);

  useEffect(() => {
    fetchPrograms()
      .then(setPrograms)
      .catch(() => setPrograms([]));
  }, []);

  return (
    <ProgramCtx.Provider value={{ programId, setProgramId, programs }}>
      {children}
    </ProgramCtx.Provider>
  );
}

export function useProgram() {
  const ctx = useContext(ProgramCtx);
  if (!ctx) throw new Error("useProgram must be used within ProgramProvider");
  return ctx;
}
