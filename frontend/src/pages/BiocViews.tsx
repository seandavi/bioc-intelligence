import { useEffect, useMemo, useState } from "react";
import { useQuery } from "../db/useQuery";
import { TermTree, type TreeNode } from "../components/TermTree";
import { VegaChart } from "../components/VegaChart";
import { horizontalBar, NEUTRAL } from "../components/charts";
import { BiocViewChip, INPUT_CLASS, SrLabel } from "../components/ui";
import { fmtInt } from "../lib/format";

interface Term {
  term: string;
  n: number;
}

// The four taxonomy roots apply to whole repositories, not topics.
const ROOTS = new Set(["Software", "AnnotationData", "ExperimentData", "Workflow"]);

// Every biocViews term with its package count (the flat taxonomy).
const TERMS = `
  SELECT term, count(*)::INT AS n
  FROM (SELECT unnest(biocviews) AS term FROM 'mart_package_directory.parquet')
  GROUP BY term ORDER BY n DESC`;

export function BiocViews() {
  const { data, loading, error } = useQuery<Term>(TERMS);
  const [q, setQ] = useState("");
  const [treeQ, setTreeQ] = useState("");
  const [tree, setTree] = useState<TreeNode[] | null>(null);
  const [treeError, setTreeError] = useState<Error | null>(null);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/tree.json`)
      .then((r) => (r.ok ? (r.json() as Promise<TreeNode[]>) : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setTree, setTreeError);
  }, []);

  const all = useMemo(() => (data ?? []).filter((t) => !ROOTS.has(t.term)), [data]);
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
            NEUTRAL,
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
        <h1 className="text-2xl font-semibold text-ink">biocViews</h1>
        <p className="mt-1 text-sm text-neutral-300">
          {loading ? "Loading…" : `${all.length.toLocaleString()} terms`} · the controlled
          vocabulary that classifies every package.
        </p>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        <div className="min-w-0 flex-1">
          <SrLabel htmlFor="biocviews-tree-filter">Filter hierarchy</SrLabel>
          <input
            id="biocviews-tree-filter"
            type="search"
            placeholder="Filter hierarchy…"
            value={treeQ}
            onChange={(e) => setTreeQ(e.target.value)}
            className={`mb-3 w-full ${INPUT_CLASS}`}
          />
          <div className="max-h-[40rem] overflow-y-auto rounded-xl border border-primary-75 bg-white p-3">
            {treeError ? (
              <p className="text-sm text-red-700">Failed to load hierarchy: {treeError.message}</p>
            ) : tree ? (
              <TermTree roots={tree} filter={treeQ} />
            ) : (
              <p className="text-sm text-neutral-300">Loading…</p>
            )}
          </div>
          {topSpec && (
            <div className="mt-6 rounded-xl border border-primary-75 bg-white p-4">
              <VegaChart spec={topSpec} className="w-full" />
            </div>
          )}
        </div>

        <div className="lg:w-96">
          <SrLabel htmlFor="biocviews-term-filter">Filter terms</SrLabel>
          <input
            id="biocviews-term-filter"
            type="search"
            placeholder="Filter terms…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className={`mb-3 w-full ${INPUT_CLASS}`}
          />
          <div className="max-h-[28rem] overflow-y-auto rounded-xl border border-primary-75 bg-white">
            <table className="w-full text-sm">
              <tbody>
                {filtered.map((t) => (
                  <tr key={t.term} className="border-b border-neutral-75 last:border-0">
                    <td className="px-3 py-1.5">
                      <BiocViewChip term={t.term} />
                    </td>
                    <td className="w-28 px-3 py-1.5">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 flex-1 rounded bg-neutral-75">
                          <div
                            className="h-1.5 rounded bg-neutral-200"
                            style={{ width: `${(t.n / maxN) * 100}%` }}
                          />
                        </div>
                        <span className="w-10 text-right tabular-nums text-xs text-neutral-300">
                          {fmtInt(t.n)}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td className="px-3 py-4 text-center text-sm text-neutral-300">no matching terms</td>
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
