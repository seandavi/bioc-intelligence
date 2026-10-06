import { Fragment, useMemo, useState } from "react";
import {
  type ColumnDef,
  type SortingState,
  type Updater,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useQuery } from "../db/useQuery";
import { Chip, INPUT_CLASS, RepoBadge, SortableTh, SrLabel } from "../components/ui";
import { Link, parseList, setParams, toggleInList, useRoute } from "../lib/router";
import { fmtCompact, fmtFloat, fmtInt } from "../lib/format";
import { type PackageAgg, type WorkLink, aggregateByPackage, pkgKey } from "../lib/confidence";

interface Row {
  package_name: string;
  repo: string;
  total_distinct_ips: number;
  distinct_ips_trailing_12mo: number;
  usage_rank_in_repo: number;
  biocviews: string; // '|'-joined
  n_primary_pubs: number;
  total_citations: number;
  median_rcr: number | null;
  n_distinct_grants_citing: number;
  agg: PackageAgg | undefined; // confidence-filtered paper links; undefined = none
}

type ImpactRow = Omit<Row, "n_primary_pubs" | "total_citations" | "median_rcr" | "agg">;

const SQL = `
  SELECT i.package_name, i.repo, i.total_distinct_ips, i.distinct_ips_trailing_12mo,
         i.usage_rank_in_repo, array_to_string(d.biocviews, '|') AS biocviews,
         i.n_distinct_grants_citing
  FROM 'mart_package_impact.parquet' i
  LEFT JOIN 'mart_package_directory.parquet' d USING (package_name, repo)`;

// Paper-derived columns are recomputed from the links so low-confidence ones can be excluded.
const WORK_SQL = `
  SELECT package_name, repo, work_id, title, citation_count, icite_rcr, match_method
  FROM 'mart_package_work.parquet'`;

const METHOD_LABEL: Record<string, string> = {
  doi: "DOI",
  citation_file: "CITATION",
  description_doi: "DESCRIPTION",
};

// Quick-sort presets — the metrics a reviewer actually ranks by.
const PRESETS: { id: string; label: string; col: keyof Row }[] = [
  { id: "rcr", label: "Median RCR", col: "median_rcr" },
  { id: "cites", label: "Total citations", col: "total_citations" },
  { id: "pubs", label: "Linked publications", col: "n_primary_pubs" },
  { id: "grants", label: "Grants", col: "n_distinct_grants_citing" },
  { id: "recent", label: "Last 12 mo", col: "distinct_ips_trailing_12mo" },
];

const DEFAULT_SORT = "median_rcr";
const SORT_COLS = new Set(["package_name", "repo", ...PRESETS.map((p) => p.col as string), "total_distinct_ips", "usage_rank_in_repo"]);

// URL form of the sort: "<col>" is descending, "<col>:asc" ascending.
const parseSort = (s: string | undefined): SortingState => {
  const [id, dir] = (s ?? "").split(":");
  return SORT_COLS.has(id) ? [{ id, desc: dir !== "asc" }] : [{ id: DEFAULT_SORT, desc: true }];
};
const formatSort = (s: SortingState) => (s[0] ? `${s[0].id}${s[0].desc ? "" : ":asc"}` : "");

function PaperLinks({ agg }: { agg: PackageAgg }) {
  return (
    <ul className="space-y-1.5 text-xs text-slate-600">
      {agg.works.map((w) => (
        <li key={w.work_id}>
          <span className="font-medium text-slate-800">{w.title ?? w.work_id}</span>
          <span className="ml-2 tabular-nums">
            {fmtInt(w.citation_count)} citations · RCR {fmtFloat(w.icite_rcr, 2)}
          </span>
          {w.methods.map((m) => (
            <span key={m} className="ml-1.5 rounded bg-slate-200 px-1.5 py-0.5 text-slate-600">
              {METHOD_LABEL[m] ?? m}
            </span>
          ))}
          {w.others.length > 0 && (
            <span className="ml-2 text-amber-700">⇄ also linked to {w.others.join(", ")}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

export function ImpactLeaderboard() {
  const impact = useQuery<ImpactRow>(SQL);
  const links = useQuery<WorkLink>(WORK_SQL);
  const { params } = useRoute();
  const { q: globalFilter = "", sort: sortParam, view: viewTerm = "" } = params;
  const noInfra = params.noinfra === "1";
  const includeLow = params.conf === "1";
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const repoParam = params.repo;
  const repos = useMemo(() => new Set(parseList(repoParam)), [repoParam]);
  const sorting = useMemo(() => parseSort(sortParam), [sortParam]);
  const setSorting = (u: Updater<SortingState>) =>
    setParams("impact", { sort: formatSort(typeof u === "function" ? u(sorting) : u) });

  const loading = impact.loading || links.loading;
  const error = impact.error ?? links.error;
  const all = useMemo<Row[]>(() => {
    const { byPackage } = aggregateByPackage(links.data ?? [], includeLow);
    return (impact.data ?? []).map((r) => {
      const agg = byPackage.get(pkgKey(r.repo, r.package_name));
      return {
        ...r,
        agg,
        n_primary_pubs: agg?.n_pubs ?? 0,
        total_citations: agg?.total_citations ?? 0,
        median_rcr: agg?.median_rcr ?? null,
      };
    });
  }, [impact.data, links.data, includeLow]);
  const repoCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of all) m.set(p.repo, (m.get(p.repo) ?? 0) + 1);
    return m;
  }, [all]);
  const viewCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of all) for (const v of parseList(p.biocviews)) m.set(v, (m.get(v) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [all]);
  const filtered = useMemo(
    () =>
      all.filter((p) => {
        const views = parseList(p.biocviews);
        return (
          (repos.size === 0 || repos.has(p.repo)) &&
          (!noInfra || !views.includes("Infrastructure")) &&
          (!viewTerm || views.includes(viewTerm))
        );
      }),
    [all, repos, noInfra, viewTerm],
  );

  const downloadsLive = useMemo(() => all.some((r) => r.total_distinct_ips > 0), [all]);

  const num = (
    key: keyof Row,
    fmt: (n: number | null) => string,
    header: string,
    info?: string,
  ): ColumnDef<Row> => ({
    accessorKey: key as string,
    header,
    meta: { info },
    cell: ({ getValue }) => <span className="tabular-nums">{fmt(getValue<number | null>())}</span>,
    sortUndefined: "last",
    sortingFn: "basic",
  });

  const columns = useMemo<ColumnDef<Row>[]>(
    () => [
      {
        accessorKey: "package_name",
        header: "Package",
        cell: ({ row, getValue }) => {
          const key = pkgKey(row.original.repo, getValue<string>());
          const agg = row.original.agg;
          const open = expanded.has(key);
          const others = [...new Set(agg?.works.flatMap((w) => w.others))].sort();
          return (
            <>
              <Link
                view="package"
                arg={getValue<string>()}
                className="font-medium text-bioc-700 hover:underline"
              >
                {getValue<string>()}
              </Link>
              {agg?.shared && (
                <span
                  className="ml-1.5 cursor-help text-xs text-amber-600"
                  title={`Shared: a linked paper is also linked to ${others.join(", ")}`}
                  aria-label={`Shared paper with ${others.join(", ")}`}
                >
                  ⇄
                </span>
              )}
              {agg && (
                <button
                  type="button"
                  aria-expanded={open}
                  aria-label={`${open ? "Hide" : "Show"} linked papers for ${getValue<string>()}`}
                  onClick={() =>
                    setExpanded((s) => {
                      const n = new Set(s);
                      if (!n.delete(key)) n.add(key);
                      return n;
                    })
                  }
                  className="ml-1.5 text-xs text-slate-500 hover:text-slate-900"
                >
                  {open ? "▾" : "▸"}
                </button>
              )}
            </>
          );
        },
      },
      { accessorKey: "repo", header: "Repo", cell: ({ getValue }) => <RepoBadge repo={getValue<string>()} /> },
      num("median_rcr", (n) => fmtFloat(n, 2), "Median RCR",
        "Relative Citation Ratio (NIH iCite), field-normalized so 1.0 = average. Median across the package's describing papers (distinct works)."),
      num("total_citations", (n) => fmtCompact(n), "Citations",
        "Total OpenAlex citations of the package's describing papers."),
      num("n_primary_pubs", (n) => fmtInt(n), "Pubs",
        "Number of describing publications linked to the package."),
      num("n_distinct_grants_citing", (n) => fmtInt(n), "Grants",
        "Distinct NIH grants whose publications are described by this package (via RePORTER)."),
      num("total_distinct_ips", (n) => (downloadsLive ? fmtCompact(n) : "—"), "Distinct IPs",
        "Sum of monthly distinct downloading IPs — the usage proxy (less gameable than raw downloads). An IP active in several months counts once per month."),
      num("distinct_ips_trailing_12mo", (n) => (downloadsLive ? fmtCompact(n) : "—"), "Last 12 mo",
        "Sum of monthly distinct IPs over the latest 12 months of download stats."),
      num("usage_rank_in_repo", (n) => (downloadsLive && n != null ? `#${fmtInt(n)}` : "—"), "Repo rank",
        "Rank by last-12-month distinct IPs within the package's repository (1 = most used)."),
    ],
    [downloadsLive, expanded],
  );

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    enableSortingRemoval: false,
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

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-slate-900">Impact leaderboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          {loading ? "Loading…" : `${filtered.length.toLocaleString()} packages`} · rank by impact
          signal. Paper columns use{" "}
          {includeLow ? "all paper links" : "DOI and CITATION links only"}; ⇄ marks papers
          shared with other packages.{" "}
          {!downloadsLive && (
            <span className="text-slate-500">Download stats pending (endpoint offline).</span>
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
          <SrLabel htmlFor="impact-search">Search packages</SrLabel>
          <input
            id="impact-search"
            type="search"
            placeholder="Search…"
            value={globalFilter}
            onChange={(e) => setParams("impact", { q: e.target.value })}
            className={`w-full ${INPUT_CLASS}`}
          />
          <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Repo</div>
          <div className="mt-2 space-y-1">
            {[...repoCounts.entries()]
              .sort((a, b) => b[1] - a[1])
              .map(([r, n]) => (
                <label key={r} className="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={repos.has(r)} onChange={() => setParams("impact", { repo: toggleInList(repoParam, r) })} />
                  <RepoBadge repo={r} />
                  <span className="ml-auto text-xs text-slate-500">{n}</span>
                </label>
              ))}
          </div>
          <label className="mt-4 flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={includeLow}
              onChange={(e) => setParams("impact", { conf: e.target.checked ? "1" : "" })}
            />
            Include lower-confidence paper links
          </label>
          <label className="mt-2 flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={noInfra}
              onChange={(e) => setParams("impact", { noinfra: e.target.checked ? "1" : "" })}
            />
            Exclude Infrastructure
          </label>
          <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">biocViews</div>
          {viewTerm ? (
            <div className="mt-2">
              <Chip>
                {viewTerm}
                <button
                  className="ml-1 text-bioc-700 hover:text-slate-900"
                  aria-label={`remove ${viewTerm} filter`}
                  onClick={() => setParams("impact", { view: "" })}
                >
                  ✕
                </button>
              </Chip>
            </div>
          ) : (
            <select
              aria-label="Filter by biocViews term"
              value=""
              onChange={(e) => setParams("impact", { view: e.target.value })}
              className="mt-2 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bioc-500"
            >
              <option value="">Any term</option>
              {viewCounts.map(([v, n]) => (
                <option key={v} value={v}>
                  {v} ({n})
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h) => (
                      <SortableTh
                        key={h.id}
                        sorted={h.column.getIsSorted()}
                        onToggle={h.column.getCanSort() ? h.column.getToggleSortingHandler() : undefined}
                        info={h.column.columnDef.meta?.info}
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                      </SortableTh>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row, i) => (
                  <Fragment key={row.id}>
                    <tr className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                      {row.getVisibleCells().map((cell, j) => (
                        <td key={cell.id} className="px-3 py-2">
                          {j === 0 && (
                            <span className="mr-2 text-xs text-slate-500">
                              {table.getState().pagination.pageIndex * 25 + i + 1}
                            </span>
                          )}
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                    {row.original.agg && expanded.has(pkgKey(row.original.repo, row.original.package_name)) && (
                      <tr className="border-b border-slate-100 bg-slate-50">
                        <td colSpan={columns.length} className="px-3 py-2">
                          <PaperLinks agg={row.original.agg} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
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
