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
import type { VisualizationSpec } from "vega-embed";
import { useQuery } from "../db/useQuery";
import { StatCard } from "../components/StatCard";
import { VegaChart } from "../components/VegaChart";
import { METRIC, TITLE_COLOR } from "../components/charts";
import { OrcidLink } from "../components/PeopleBlock";
import { fmtInt } from "../lib/format";
import { Link, setParams, useRoute } from "../lib/router";

interface Person {
  person_id: string;
  name: string;
  orcid: string | null;
  n_packages: number;
  n_maintained: number;
  n_authored: number;
  packages: string; // ', '-joined
}

interface Coverage {
  orcid_packages: number;
  shared_mailbox: number;
  total_packages: number;
}

const SQL = `
  SELECT person_id, name, orcid, n_packages, n_maintained, n_authored,
         array_to_string(package_names, ', ') AS packages
  FROM 'mart_person.parquet'
  ORDER BY n_packages DESC, name`;

const COVERAGE_SQL = `
  SELECT (SELECT count(DISTINCT package_name || '|' || repo)
          FROM 'mart_package_person.parquet' WHERE orcid IS NOT NULL) AS orcid_packages,
         count(*) FILTER (WHERE maintainer ILIKE '%Package Maintainer%') AS shared_mailbox,
         count(*) AS total_packages
  FROM 'mart_package_directory.parquet'`;

const SHOWN_PACKAGES = 5;
const BUCKETS = ["1", "2", "3", "4", "5", "6–10", "11–20", "21+"];
const bucket = (n: number) =>
  n <= 5 ? String(n) : n <= 10 ? "6–10" : n <= 20 ? "11–20" : "21+";

const histogramSpec = (people: Person[]): VisualizationSpec => {
  const counts = new Map<string, number>();
  for (const p of people) counts.set(bucket(p.n_packages), (counts.get(bucket(p.n_packages)) ?? 0) + 1);
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: { text: "Packages per person", fontSize: 13, color: TITLE_COLOR },
    data: { values: BUCKETS.map((b) => ({ packages: b, people: counts.get(b) ?? 0 })) },
    mark: { type: "bar", color: METRIC.people, cornerRadiusEnd: 3 },
    encoding: {
      x: { field: "packages", type: "ordinal", sort: BUCKETS, axis: { title: "packages", labelAngle: 0 } },
      y: { field: "people", type: "quantitative", axis: { title: "people" } },
      tooltip: [
        { field: "packages", type: "ordinal" },
        { field: "people", type: "quantitative" },
      ],
    },
    width: "container",
    height: 180,
    config: { view: { stroke: null } },
  } as VisualizationSpec;
};

export function People() {
  const { data, loading, error } = useQuery<Person>(SQL);
  const coverage = useQuery<Coverage>(COVERAGE_SQL).data?.[0];
  const { params } = useRoute();
  const globalFilter = params.q ?? "";
  const [sorting, setSorting] = useState<SortingState>([{ id: "n_packages", desc: true }]);

  const people = useMemo(() => data ?? [], [data]);
  const nOrcid = useMemo(() => people.filter((p) => p.orcid).length, [people]);
  const spec = useMemo(() => histogramSpec(people), [people]);

  const columns = useMemo<ColumnDef<Person>[]>(
    () => [
      { accessorKey: "name", header: "Name", cell: ({ getValue }) => <span className="font-medium text-neutral-500">{getValue<string>()}</span> },
      {
        accessorKey: "orcid",
        header: "ORCID",
        cell: ({ row }) => (row.original.orcid ? <OrcidLink orcid={row.original.orcid} /> : <span className="text-neutral-300">—</span>),
      },
      { accessorKey: "n_packages", header: "Packages", cell: ({ getValue }) => <span className="tabular-nums text-metric-people">{fmtInt(getValue<number>())}</span> },
      { accessorKey: "n_maintained", header: "Maintained", cell: ({ getValue }) => <span className="tabular-nums text-metric-people">{fmtInt(getValue<number>())}</span> },
      { accessorKey: "n_authored", header: "Authored", cell: ({ getValue }) => <span className="tabular-nums text-metric-people">{fmtInt(getValue<number>())}</span> },
      {
        accessorKey: "packages",
        header: "Package names",
        enableSorting: false,
        cell: ({ getValue }) => {
          const names = getValue<string>().split(", ").filter(Boolean);
          return (
            <span className="text-xs text-neutral-300">
              {names.slice(0, SHOWN_PACKAGES).map((name, i) => (
                <span key={name}>
                  {i > 0 && ", "}
                  <Link view="package" arg={name} className="text-primary-400 hover:underline">
                    {name}
                  </Link>
                </span>
              ))}
              {names.length > SHOWN_PACKAGES && ` +${names.length - SHOWN_PACKAGES}`}
            </span>
          );
        },
      },
    ],
    [],
  );

  const table = useReactTable({
    data: people,
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
        Failed to load people: {error.message}
      </div>
    );
  }

  const pct = (n: number, d: number) => (d ? `${((100 * n) / d).toFixed(1)}%` : "—");
  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-ink">People</h1>
        <p className="mt-1 text-sm text-neutral-300">
          {loading ? "Loading…" : `${fmtInt(table.getFilteredRowModel().rows.length)} people`} · authors and
          maintainers parsed from each package's <code>Authors@R</code>.
        </p>
      </div>

      <div className="mb-5 grid gap-4 lg:grid-cols-3">
        <div className="grid grid-cols-2 gap-3 lg:col-span-1">
          <StatCard label="People" metric="people" value={fmtInt(people.length)} pending={loading} sub="distinct identities" />
          <StatCard label="With ORCID" metric="people" value={fmtInt(nOrcid)} pending={loading} sub={pct(nOrcid, people.length)} />
          <StatCard
            label="Packages with ORCID" metric="people"
            value={fmtInt(coverage?.orcid_packages)}
            pending={!coverage}
            sub={`${pct(coverage?.orcid_packages ?? 0, coverage?.total_packages ?? 0)} of packages have an author with an ORCID`}
          />
          <StatCard
            label="Shared mailbox" metric="people"
            value={pct(coverage?.shared_mailbox ?? 0, coverage?.total_packages ?? 0)}
            pending={!coverage}
            sub={`${fmtInt(coverage?.shared_mailbox)} packages list a “Package Maintainer” mailbox`}
          />
        </div>
        <div className="rounded-xl border border-primary-75 bg-white p-4 lg:col-span-2">
          {data && <VegaChart spec={spec} className="w-full" />}
        </div>
      </div>

      <p className="mb-4 rounded-lg border border-primary-75 bg-white p-3 text-xs text-neutral-300">
        Identity is the ORCID when a package declares one, otherwise a normalised name. People who share a
        name may be merged into one row, and one person who spells their name differently across packages
        may be split into several.
      </p>

      <input
        type="search"
        placeholder="Search name, ORCID or package…"
        value={globalFilter}
        onChange={(e) => setParams("people", { q: e.target.value })}
        className="mb-3 w-full max-w-sm rounded-md border border-neutral-100 px-3 py-1.5 text-sm focus:border-brand-teal focus:outline-none"
      />

      <div className="overflow-x-auto rounded-xl border border-primary-75 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-primary-75 text-xs uppercase tracking-wide text-neutral-300">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th
                    key={h.id}
                    onClick={h.column.getToggleSortingHandler()}
                    className={`px-3 py-2 ${h.column.getCanSort() ? "cursor-pointer select-none hover:text-neutral-400" : ""}`}
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
              <tr key={row.id} className="border-b border-neutral-75 align-top last:border-0 hover:bg-neutral-50">
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
      <div className="mt-3 flex items-center gap-3 text-sm text-neutral-300">
        <button
          className="rounded border border-neutral-100 px-2 py-1 disabled:opacity-40"
          onClick={() => table.previousPage()}
          disabled={!table.getCanPreviousPage()}
        >
          ← Prev
        </button>
        <span>
          Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount().toLocaleString()}
        </span>
        <button
          className="rounded border border-neutral-100 px-2 py-1 disabled:opacity-40"
          onClick={() => table.nextPage()}
          disabled={!table.getCanNextPage()}
        >
          Next →
        </button>
      </div>
    </div>
  );
}
