import { Fragment, useMemo, useState } from "react";
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
import { InfoDot } from "../components/InfoDot";
import { StatCard } from "../components/StatCard";
import { VegaChart } from "../components/VegaChart";
import { horizontalBar } from "../components/charts";
import { GrantReport, type PackageImpact, type PackageWork } from "../components/GrantReport";
import { fmtInt } from "../lib/format";
import { downloadCsv } from "../lib/csv";
import { nihIcName } from "../lib/nih";
import { Link, parseList, setParams, toggleInList, useRoute } from "../lib/router";

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

const GRANT_PACKAGES = `SELECT unnest(package_names) FROM 'mart_grant_attribution.parquet'`;

const IMPACT_SQL = `
  SELECT package_name, distinct_ips_trailing_12mo, total_distinct_ips, n_primary_pubs,
         total_citations, median_rcr
  FROM 'mart_package_impact.parquet'
  WHERE package_name IN (${GRANT_PACKAGES})`;

const WORK_SQL = `
  SELECT package_name, work_id, citation_count, icite_rcr, match_method
  FROM 'mart_package_work.parquet'
  WHERE package_name IN (${GRANT_PACKAGES})`;

const NOT_FOUND = "not found in RePORTER projects";
const icLabel = (code: string) => (code === "—" ? `— · ${NOT_FOUND}` : `${code} · ${nihIcName(code)}`);
const Missing = () => <span title={NOT_FOUND}>—</span>;

export function Grants() {
  const { data, loading, error } = useQuery<Grant>(SQL);
  const impactQ = useQuery<PackageImpact>(IMPACT_SQL);
  const workQ = useQuery<PackageWork>(WORK_SQL);
  const [open, setOpen] = useState<string | null>(null);
  const [includeLowConfidence, setIncludeLowConfidence] = useState(false);
  const { params } = useRoute();
  const globalFilter = params.q ?? "";
  const agencyParam = params.agency;
  const agencies = useMemo(() => new Set(parseList(agencyParam)), [agencyParam]);
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

  const impact = useMemo(
    () => new Map((impactQ.data ?? []).map((r) => [r.package_name, r])),
    [impactQ.data],
  );
  const worksByPackage = useMemo(() => {
    const m = new Map<string, PackageWork[]>();
    for (const w of workQ.data ?? []) m.set(w.package_name, [...(m.get(w.package_name) ?? []), w]);
    return m;
  }, [workQ.data]);

  const icSpec = useMemo(
    () =>
      horizontalBar(
        [...agencyCounts.entries()]
          .filter(([a]) => a !== "—")
          .sort((a, b) => b[1] - a[1])
          .slice(0, 15)
          .map(([a, n]) => ({ ic: icLabel(a), awards: n })),
        "awards",
        "ic",
        "Awards per Institute/Center (top 15)",
      ),
    [agencyCounts],
  );
  const nPackages = useMemo(
    () => new Set(filtered.flatMap((g) => g.packages.split(", ").filter(Boolean))).size,
    [filtered],
  );

  const columns = useMemo<ColumnDef<Grant>[]>(
    () => [
      {
        id: "expand",
        header: "",
        enableSorting: false,
        cell: ({ row }) => (
          <button
            aria-label="Show grant report"
            aria-expanded={open === row.original.grant_id}
            className="text-slate-400 hover:text-slate-700"
          >
            {open === row.original.grant_id ? "▾" : "▸"}
          </button>
        ),
      },
      {
        accessorKey: "grant_id",
        header: "Grant",
        cell: ({ getValue }) => (
          <a
            href={`https://reporter.nih.gov/project-details/${getValue<string>()}`}
            target="_blank"
            rel="noreferrer"
            title="Open in NIH RePORTER (linked by core project number, so RePORTER may list several fiscal years)"
            className="font-medium text-bioc-600 hover:underline"
          >
            {getValue<string>()}
          </a>
        ),
      },
      {
        accessorKey: "agency",
        header: "IC",
        cell: ({ getValue }) => {
          const ic = getValue<string | null>();
          return ic == null ? (
            <Missing />
          ) : (
            <span title={nihIcName(ic)} className="inline-block rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
              {ic}
            </span>
          );
        },
      },
      {
        accessorKey: "title",
        header: "Title",
        cell: ({ getValue }) => {
          const t = getValue<string | null>();
          return t == null ? (
            <Missing />
          ) : (
            <span title={t} className="block max-w-xs truncate text-slate-700">
              {t}
            </span>
          );
        },
      },
      {
        accessorKey: "n_packages_supported",
        header: () => (
          <span className="inline-flex items-center">
            Packages
            <InfoDot tip="Distinct Bioconductor packages whose cite-me paper acknowledges this grant in NIH RePORTER publication links." />
          </span>
        ),
        cell: ({ getValue }) => <span className="tabular-nums">{fmtInt(getValue<number>())}</span>,
      },
      {
        accessorKey: "packages",
        header: "Supported packages",
        enableSorting: false,
        cell: ({ getValue }) => (
          <span className="text-xs text-slate-500">
            {getValue<string>()
              .split(", ")
              .filter(Boolean)
              .map((name, i) => (
                <span key={name}>
                  {i > 0 && ", "}
                  <Link view="package" arg={name} className="text-bioc-600 hover:underline">
                    {name}
                  </Link>
                </span>
              ))}
          </span>
        ),
      },
    ],
    [open],
  );

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
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
  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Grant attribution</h1>
          <p className="mt-1 text-sm text-slate-500">
            {loading ? "Loading…" : `${filtered.length.toLocaleString()} grants`} · NIH awards
            acknowledged by the papers these packages ask users to cite.
          </p>
        </div>
        <button
          onClick={() => downloadCsv("bioc-grant-attribution.csv", exportRows)}
          className="rounded-md bg-bioc-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-bioc-600"
        >
          Export CSV
        </button>
      </div>

      <div className="mb-5 grid gap-4 lg:grid-cols-3">
        <div className="grid grid-cols-3 gap-3 lg:col-span-1 lg:grid-cols-1">
          <StatCard label="Awards" value={fmtInt(filtered.length)} pending={loading} sub="core project numbers" />
          <StatCard label="ICs" value={fmtInt(new Set(filtered.flatMap((g) => (g.agency ? [g.agency] : []))).size)} pending={loading} sub="Institutes/Centers" />
          <StatCard label="Packages supported" value={fmtInt(nPackages)} pending={loading} sub="distinct" />
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 lg:col-span-2">
          {data && <VegaChart spec={icSpec} className="w-full" />}
        </div>
      </div>

      <div className="flex flex-col gap-5 lg:flex-row">
        <div className="shrink-0 lg:w-56">
          <input
            type="search"
            placeholder="Search…"
            value={globalFilter}
            onChange={(e) => setParams("grants", { q: e.target.value })}
            className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-bioc-500 focus:outline-none"
          />
          <label className="mt-4 flex items-start gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              className="mt-1"
              checked={includeLowConfidence}
              onChange={(e) => setIncludeLowConfidence(e.target.checked)}
            />
            <span>
              Include lower-confidence paper links
              <InfoDot tip="Off: the per-grant report drops packages linked to papers only through a DOI in their DESCRIPTION, which sometimes cites a dependency or related work rather than the package's own paper. Links from CITATION files or the package's own DOI are always kept." />
            </span>
          </label>
          <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Institute/Center</div>
          <div className="mt-2 max-h-72 space-y-1 overflow-y-auto">
            {[...agencyCounts.entries()]
              .sort((a, b) => b[1] - a[1])
              .map(([a, n]) => (
                <label key={a} className="flex items-center gap-2 text-sm text-slate-600" title={icLabel(a)}>
                  <input type="checkbox" checked={agencies.has(a)} onChange={() => setParams("grants", { agency: toggleInList(agencyParam, a) })} />
                  <span className="truncate">{icLabel(a)}</span>
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
                {table.getRowModel().rows.map((row) => {
                  const g = row.original;
                  return (
                    <Fragment key={row.id}>
                      <tr
                        onClick={(e) => {
                          if (!(e.target as HTMLElement).closest("a")) setOpen(open === g.grant_id ? null : g.grant_id);
                        }}
                        className="cursor-pointer border-b border-slate-100 align-top last:border-0 hover:bg-slate-50"
                      >
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className="px-3 py-2">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                      {open === g.grant_id && (
                        <tr className="border-b border-slate-100">
                          <td colSpan={row.getVisibleCells().length} className="px-3 pb-3">
                            <GrantReport
                              grant={{ ...g, packages: g.packages.split(", ").filter(Boolean) }}
                              impact={impact}
                              worksByPackage={worksByPackage}
                              includeLowConfidence={includeLowConfidence}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
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
