import { useMemo, useState } from "react";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useQuery } from "../db/useQuery";
import { RepoBadge } from "../components/ui";
import { fmtCompact, fmtFloat, fmtInt } from "../lib/format";

interface Row {
  package_name: string;
  repo: string;
  total_distinct_ips: number;
  n_primary_pubs: number;
  total_citations: number;
  median_rcr: number | null;
  n_distinct_grants_citing: number;
}

const SQL = `
  SELECT package_name, repo, total_distinct_ips,
         n_primary_pubs, total_citations, median_rcr, n_distinct_grants_citing
  FROM 'mart_package_impact.parquet'`;

// Quick-sort presets — the metrics a reviewer actually ranks by.
const PRESETS: { id: string; label: string; col: keyof Row }[] = [
  { id: "rcr", label: "Median RCR", col: "median_rcr" },
  { id: "cites", label: "Total citations", col: "total_citations" },
  { id: "pubs", label: "Linked publications", col: "n_primary_pubs" },
  { id: "grants", label: "Grants", col: "n_distinct_grants_citing" },
];

export function ImpactLeaderboard() {
  const { data, loading, error } = useQuery<Row>(SQL);
  const [repos, setRepos] = useState<Set<string>>(new Set());
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "median_rcr", desc: true }]);

  const all = useMemo(() => data ?? [], [data]);
  const repoCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of all) m.set(p.repo, (m.get(p.repo) ?? 0) + 1);
    return m;
  }, [all]);
  const filtered = useMemo(
    () => all.filter((p) => repos.size === 0 || repos.has(p.repo)),
    [all, repos],
  );

  const downloadsLive = useMemo(() => all.some((r) => r.total_distinct_ips > 0), [all]);

  const num = (key: keyof Row, fmt: (n: number | null) => string, header: string): ColumnDef<Row> => ({
    accessorKey: key as string,
    header,
    cell: ({ getValue }) => (
      <span className="tabular-nums">{fmt(getValue<number | null>())}</span>
    ),
    sortUndefined: "last",
    sortingFn: "basic",
  });

  const columns = useMemo<ColumnDef<Row>[]>(
    () => [
      {
        accessorKey: "package_name",
        header: "Package",
        cell: ({ getValue }) => (
          <span className="font-medium text-slate-800">{getValue<string>()}</span>
        ),
      },
      { accessorKey: "repo", header: "Repo", cell: ({ getValue }) => <RepoBadge repo={getValue<string>()} /> },
      num("median_rcr", (n) => fmtFloat(n, 2), "Median RCR"),
      num("total_citations", (n) => fmtCompact(n), "Citations"),
      num("n_primary_pubs", (n) => fmtInt(n), "Pubs"),
      num("n_distinct_grants_citing", (n) => fmtInt(n), "Grants"),
      num("total_distinct_ips", (n) => (downloadsLive ? fmtCompact(n) : "—"), "Distinct IPs"),
    ],
    [downloadsLive],
  );

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 25 } },
  });

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Failed to load impact data: {error.message}
      </div>
    );
  }

  const applyPreset = (col: keyof Row) => setSorting([{ id: col as string, desc: true }]);
  const activeSort = sorting[0]?.id;
  const toggleRepo = (r: string) =>
    setRepos((prev) => {
      const next = new Set(prev);
      if (next.has(r)) next.delete(r);
      else next.add(r);
      return next;
    });

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-slate-900">Impact leaderboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          {loading ? "Loading…" : `${filtered.length.toLocaleString()} packages`} · rank by impact
          signal.{" "}
          {!downloadsLive && (
            <span className="text-slate-400">Download stats pending (endpoint offline).</span>
          )}
        </p>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            onClick={() => applyPreset(p.col)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition ${
              activeSort === p.col
                ? "bg-bioc-500 text-white"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-5 lg:flex-row">
        <div className="shrink-0 lg:w-44">
          <input
            type="search"
            placeholder="Search…"
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-bioc-500 focus:outline-none"
          />
          <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Repo</div>
          <div className="mt-2 space-y-1">
            {[...repoCounts.entries()]
              .sort((a, b) => b[1] - a[1])
              .map(([r, n]) => (
                <label key={r} className="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={repos.has(r)} onChange={() => toggleRepo(r)} />
                  <RepoBadge repo={r} />
                  <span className="ml-auto text-xs text-slate-400">{n}</span>
                </label>
              ))}
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h) => (
                      <th
                        key={h.id}
                        onClick={h.column.getToggleSortingHandler()}
                        className="cursor-pointer select-none px-3 py-2 hover:text-slate-700"
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {{ asc: " ↑", desc: " ↓" }[h.column.getIsSorted() as string] ?? ""}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row, i) => (
                  <tr key={row.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    {row.getVisibleCells().map((cell, j) => (
                      <td key={cell.id} className="px-3 py-2">
                        {j === 0 && (
                          <span className="mr-2 text-xs text-slate-400">
                            {table.getState().pagination.pageIndex * 25 + i + 1}
                          </span>
                        )}
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center gap-3 text-sm text-slate-500">
            <button
              className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              ← Prev
            </button>
            <span>
              Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount().toLocaleString()}
            </span>
            <button
              className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              Next →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
