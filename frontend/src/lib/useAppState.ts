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

  const reload = useCallback(() => {
    setLoading(true);
    fetchState(programId)
      .then((s) => {
        setState(s);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [programId]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { state, error, loading, reload };
}
