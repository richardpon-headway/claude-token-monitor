import { useEffect, useRef, useState } from "react";

interface State<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

/** Generic JSON-fetch hook keyed by `path`. Re-fetches when `refreshKey`
 *  changes — the SSE hook bumps that key on every push. Aborts in-flight
 *  requests on unmount or path change. */
export function useUsage<T>(path: string, refreshKey: number = 0): State<T> {
  const [state, setState] = useState<State<T>>({
    data: null,
    error: null,
    loading: true,
  });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setState((s) => ({ ...s, loading: true }));

    fetch(path, { signal: ac.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json() as Promise<T>;
      })
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((err: unknown) => {
        if ((err as { name?: string }).name === "AbortError") return;
        setState({
          data: null,
          error: err instanceof Error ? err : new Error(String(err)),
          loading: false,
        });
      });

    return () => ac.abort();
  }, [path, refreshKey]);

  return state;
}
