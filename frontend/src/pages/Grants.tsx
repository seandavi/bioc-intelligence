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
import { fmtInt } from "../lib/format";
import { downloadCsv } from "../lib/csv";

interface Grant {
  grant_id: string;
  agency: string | null;
  title: string | null;
  n_packages_supported: number;
  packages: string; // ', '-joined
}

const SQL = `
  SELECT grant_id, agency, title, n_packages_supported,
         array_to_string(package_names, ', ') AS packages
  FROM 'mart_grant_attribution.parquet'
  ORDER BY n_packages_supported DESC, grant_id`;

export function Grants() {
  const { data, loading, error } = useQuery<Grant>(SQL);
  const [agencies, setAgencies] = useState<Set<string>>(new Set());
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "n_packages_supported", desc: true }]);

  const all = useMemo(() => data ?? [], [data]);
  const agencyCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const g of all) m.set(g.agency ?? "—", (m.get(g.agency ?? "—") ?? 0) + 1);
    return m;
  }, [all]);
  const filtered = useMemo(
    () => all.filter((g) => agencies.size === 0 || agencies.has(g.agency ?? "—")),
    [all, agencies],
  );

  const columns = useMemo<ColumnDef<Grant>[]>(
    () => [
      {
        accessorKey: "grant_id",
        header: "Grant",
        cell: ({ getValue }) => <span className="font-medium text-slate-800">{getValue<string>()}</span>,
      },
      {
        accessorKey: "agency",
        header: "Agency",
        cell: ({ getValue }) => (
          <span className="inline-block rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
            {getValue<string | null>() ?? "—"}
          </span>
        ),
      },
      {
        accessorKey: "n_packages_supported",
        header: "Packages",
        cell: ({ getValue }) => <span className="tabular-nums">{fmtInt(getValue<number>())}</span>,
      },
      {
        accessorKey: "packages",
        header: "Supported packages",
        enableSorting: false,
        cell: ({ getValue }) => (
          <span className="text-xs text-slate-500">{getValue<string>()}</span>
        ),
      },
    ],
    [],
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
        Failed to load grants: {error.message}
      </div>
    );
  }

  const exportRows = table.getFilteredRowModel().rows.map((r) => r.original as unknown as Record<string, unknown>);
  const toggleAgency = (a: string) =>
    setAgencies((prev) => {
      const next = new Set(prev);
      if (next.has(a)) next.delete(a);
      else next.add(a);
      return next;
    });

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Grant attribution</h1>
          <p className="mt-1 text-sm text-slate-500">
            {loading ? "Loading…" : `${filtered.length.toLocaleString()} grants`} · NIH awards whose
            publications are described by Bioconductor packages.
          </p>
        </div>
        <button
          onClick={() => downloadCsv("bioc-grant-attribution.csv", exportRows)}
          className="rounded-md bg-bioc-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-bioc-600"
        >
          Export CSV
        </button>
      </div>

      <div className="flex flex-col gap-5 lg:flex-row">
        <div className="shrink-0 lg:w-40">
          <input
            type="search"
            placeholder="Search…"
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-bioc-500 focus:outline-none"
          />
          <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Agency</div>
          <div className="mt-2 max-h-72 space-y-1 overflow-y-auto">
            {[...agencyCounts.entries()]
              .sort((a, b) => b[1] - a[1])
              .map(([a, n]) => (
                <label key={a} className="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={agencies.has(a)} onChange={() => toggleAgency(a)} />
                  {a}
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
                        className={`px-3 py-2 ${h.column.getCanSort() ? "cursor-pointer select-none hover:text-slate-700" : ""}`}
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {{ asc: " ↑", desc: " ↓" }[h.column.getIsSorted() as string] ?? ""}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100 align-top last:border-0 hover:bg-slate-50">
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-3 py-2">
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
