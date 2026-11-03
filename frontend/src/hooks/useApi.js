import { useCallback, useEffect, useRef, useState } from "react";

/** Runs an async loader, tracks loading/error, optional polling. `deps` re-trigger the load. */
export function useApi(loader, deps = [], { interval = 0, initial = null } = {}) {
  const [data, setData] = useState(initial);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const result = await loaderRef.current();
      setData(result);
      setError(null);
      return result;
    } catch (e) {
      setError(e);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
    if (!interval) return undefined;
    const id = setInterval(() => reload(true), interval);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload, setData };
}

/** Wraps an async action with a busy flag and toast feedback. */
export function useAction(toast) {
  const [busy, setBusy] = useState(null);
  const run = useCallback(async (key, fn, success) => {
    setBusy(key);
    try {
      const r = await fn();
      if (success) toast?.(typeof success === "function" ? success(r) : success, "ok");
      return r;
    } catch (e) {
      toast?.(e.message, "error");
      return undefined;
    } finally {
      setBusy(null);
    }
  }, [toast]);
  return { busy, run };
}
