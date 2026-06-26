import { useEffect, useState } from "react";
import { query } from "./duckdb";

export interface QueryState<T> {
  data: T[] | null;
  loading: boolean;
  error: Error | null;
}

// Run a SQL query against the bundled marts. `sql` should be stable (or memoized
// by the caller); changing it re-runs. Deps lets callers force a re-run.
export function useQuery<T = Record<string, unknown>>(
  sql: string | null,
  deps: unknown[] = [],
): QueryState<T> {
  const [state, setState] = useState<QueryState<T>>({
    data: null,
    loading: sql !== null,
    error: null,
  });

  useEffect(() => {
    if (sql === null) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    query<T>(sql)
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((error: Error) => {
        if (!cancelled) setState({ data: null, loading: false, error });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sql, ...deps]);

  return state;
}
