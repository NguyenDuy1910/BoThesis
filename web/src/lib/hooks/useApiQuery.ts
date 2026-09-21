"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** A cancellable read boundary; feature hooks supply the data implementation. */
export function useApiQuery<T>(read: () => Promise<T>, key: string | number = "") {
  const readRef = useRef(read);
  readRef.current = read;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    let active = true;
    setError(null);
    readRef.current().then((value) => { if (active) setData(value); })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : "Could not load this view."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [key, revision]);
  return { data, error, loading, reload };
}
