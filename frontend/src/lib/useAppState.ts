"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchState } from "./api";
import { useProgram } from "./ProgramContext";
import type { StateResponse } from "./types";

export function useAppState() {
  const { programId } = useProgram();
  const [state, setState] = useState<StateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // `silent` refresh keeps the current UI mounted (no loading flip) so local
  // component state — e.g. an approved inbox card's result — survives a reload.
  const load = useCallback(
    (silent = false) => {
      if (!silent) setLoading(true);
      fetchState(programId)
        .then((s) => {
          setState(s);
          setError(null);
        })
        .catch((e) => setError(String(e)))
        .finally(() => setLoading(false));
    },
    [programId],
  );

  useEffect(() => {
    load(false);
  }, [load]);

  const reload = useCallback(() => load(true), [load]);

  return { state, error, loading, reload };
}
