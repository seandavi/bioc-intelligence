import { useMemo, useState } from "react";
import { useQuery } from "../db/useQuery";
import { VegaChart } from "../components/VegaChart";
import { horizontalBar } from "../components/charts";
import { fmtInt } from "../lib/format";

interface Term {
  term: string;
  n: number;
}

// Every biocViews term with its package count (the flat taxonomy).
const TERMS = `
  SELECT term, count(*)::INT AS n
  FROM (SELECT unnest(biocviews) AS term FROM 'mart_package_directory.parquet')
  GROUP BY term ORDER BY n DESC`;

export function BiocViews() {
  const { data, loading, error } = useQuery<Term>(TERMS);
  const [q, setQ] = useState("");

  const all = useMemo(() => data ?? [], [data]);
  const maxN = all[0]?.n ?? 1;
  const filtered = useMemo(
    () => all.filter((t) => t.term.toLowerCase().includes(q.toLowerCase())),
    [all, q],
  );
  const topSpec = useMemo(
    () =>
      all.length
        ? horizontalBar(
            all.slice(0, 25) as unknown as Record<string, unknown>[],
            "n",
            "term",
            "Top biocViews terms",
          )
        : null,
    [all],
  );

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Failed to load biocViews: {error.message}
      </div>
    );
  }

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-slate-900">biocViews</h1>
        <p className="mt-1 text-sm text-slate-500">
          {loading ? "Loading…" : `${all.length.toLocaleString()} terms`} · the controlled
          vocabulary that classifies every package.
        </p>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        <div className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white p-4">
          {topSpec && <VegaChart spec={topSpec} className="w-full" />}
        </div>

        <div className="lg:w-96">
          <input
            type="search"
            placeholder="Filter terms…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="mb-3 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-bioc-500 focus:outline-none"
          />
          <div className="max-h-[28rem] overflow-y-auto rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <tbody>
                {filtered.map((t) => (
                  <tr key={t.term} className="border-b border-slate-100 last:border-0">
                    <td className="px-3 py-1.5 text-slate-700">{t.term}</td>
                    <td className="w-28 px-3 py-1.5">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 flex-1 rounded bg-slate-100">
                          <div
                            className="h-1.5 rounded bg-bioc-500"
                            style={{ width: `${(t.n / maxN) * 100}%` }}
                          />
                        </div>
                        <span className="w-10 text-right tabular-nums text-xs text-slate-500">
                          {fmtInt(t.n)}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td className="px-3 py-4 text-center text-sm text-slate-400">no matching terms</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
