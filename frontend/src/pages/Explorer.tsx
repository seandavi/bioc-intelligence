import { useMemo, useState } from "react";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useQuery } from "../db/useQuery";
import { BiocViewChip, Chip, INPUT_CLASS, REPO_LABEL, RepoBadge, SortableTh, SrLabel } from "../components/ui";
import { fmtFloat, fmtInt } from "../lib/format";
import { parseList, setParams, toggleInList, useRoute } from "../lib/router";
import { normalise, searchKey } from "../lib/search";

interface Pkg {
  package_name: string;
  repo: string;
  latest_release: string;
  maintainer: string | null;
  title: string | null;
  description: string | null;
  biocviews: string; // '|'-joined
  url: string; // '|'-joined
  bug_reports: string | null;
  source_doi: string | null;
}

interface Work {
  package_name: string;
  doi: string;
  title: string | null;
  year: number | null;
  journal: string | null;
  citation_count: number | null;
  icite_rcr: number | null;
  match_method: string;
  confidence: number;
}

interface Row extends Pkg {
  papers: Work[];
  n_papers: number;
  search_key: string;
}

// array_to_string keeps list columns simple across the WASM boundary.
const DIR_SELECT = `
  SELECT package_name, repo, latest_release, maintainer, title, description,
         array_to_string(biocviews, '|') AS biocviews,
         array_to_string(url, '|')       AS url,
         bug_reports, source_doi
  FROM 'mart_package_directory.parquet'`;
const DIR_SQL = `${DIR_SELECT} ORDER BY package_name`;

// ~1.1k rows: load once and join to packages in the browser.
const WORK_SELECT = `
  SELECT package_name, doi, title, year, journal, citation_count, icite_rcr, match_method, confidence
  FROM 'mart_package_work.parquet'`;
const WORK_ORDER = "ORDER BY package_name, year DESC NULLS LAST, doi";

const sqlStr = (s: string) => `'${s.replaceAll("'", "''")}'`;

const splitList = (s: string | null) => (s ? s.split("|").filter(Boolean) : []);

function PaperItem({ w }: { w: Work }) {
  return (
    <li>
      <a
        className="text-bioc-600 hover:underline"
        href={`https://doi.org/${w.doi}`}
        target="_blank"
        rel="noreferrer"
      >
        {w.title ?? w.doi}
      </a>
      <div className="text-xs text-slate-500">
        {[w.year, w.journal].filter(Boolean).join(" · ")}
        {(w.year || w.journal) && " · "}
        {fmtInt(w.citation_count)} citations · RCR {fmtFloat(w.icite_rcr, 2)}
      </div>
      <div className="mt-0.5 text-xs text-slate-500">
        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
          {w.match_method}
        </span>{" "}
        confidence {w.confidence}
      </div>
    </li>
  );
}

function DetailPanel({ pkg, papers, onClose }: { pkg: Pkg; papers: Work[]; onClose?: () => void }) {
  const views = splitList(pkg.biocviews);
  const urls = splitList(pkg.url);
  return (
    <aside className="w-full shrink-0 rounded-xl border border-slate-200 bg-white p-4 lg:w-80">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-lg font-semibold text-slate-900">{pkg.package_name}</div>
          <div className="mt-0.5 flex items-center gap-2">
            <RepoBadge repo={pkg.repo} />
            <span className="text-xs text-slate-500">release {pkg.latest_release}</span>
          </div>
          <a
            className="mt-1 block text-xs text-bioc-600 hover:underline"
            href={`https://bioconductor.org/packages/${pkg.package_name}/`}
            target="_blank"
            rel="noreferrer"
          >
            bioconductor.org page ↗
          </a>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700" aria-label="close">
            ✕
          </button>
        )}
      </div>
      {pkg.title && <p className="mt-3 text-sm text-slate-700">{pkg.title}</p>}
      <dl className="mt-3 space-y-2 text-sm">
        {pkg.maintainer && (
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-500">Maintainer</dt>
            <dd className="text-slate-700">{pkg.maintainer}</dd>
          </div>
        )}
        {papers.length > 0 ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-500">
              Papers the package asks users to cite
            </dt>
            <dd>
              <ul className="mt-1 space-y-2">
                {papers.map((w) => (
                  <PaperItem key={w.doi} w={w} />
                ))}
              </ul>
            </dd>
          </div>
        ) : pkg.source_doi && (
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-500">Describing paper</dt>
            <dd>
              <a
                className="text-bioc-600 hover:underline"
                href={`https://doi.org/${pkg.source_doi}`}
                target="_blank"
                rel="noreferrer"
              >
                {pkg.source_doi}
              </a>
            </dd>
          </div>
        )}
        {(urls.length > 0 || pkg.bug_reports) && (
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-500">Links</dt>
            <dd className="space-y-0.5">
              {urls.map((u) => (
                <a
                  key={u}
                  className="block truncate text-bioc-600 hover:underline"
                  href={u}
                  target="_blank"
                  rel="noreferrer"
                >
                  {u}
                </a>
              ))}
              {pkg.bug_reports && (
                <a
                  className="block truncate text-bioc-600 hover:underline"
                  href={pkg.bug_reports}
                  target="_blank"
                  rel="noreferrer"
                >
                  Bug reports
                </a>
              )}
            </dd>
          </div>
        )}
        {views.length > 0 && (
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-500">biocViews</dt>
            <dd className="mt-1 flex flex-wrap gap-1">
              {views.map((v) => (
                <BiocViewChip key={v} term={v} />
              ))}
            </dd>
          </div>
        )}
      </dl>
    </aside>
  );
}

// #/package/<name>: the drawer content as a page. The full profile is a later issue.
export function PackagePage({ name }: { name: string }) {
  const { data, loading, error: dirError } = useQuery<Pkg>(
    `${DIR_SELECT} WHERE package_name = ${sqlStr(name)}`,
  );
  const works = useQuery<Work>(`${WORK_SELECT} WHERE package_name = ${sqlStr(name)} ${WORK_ORDER}`);
  const error = dirError ?? works.error;
  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Failed to load package: {error.message}
      </div>
    );
  }
  if (loading || works.loading) return <p className="text-sm text-slate-500">Loading {name}…</p>;
  if (!data?.length) return <p className="text-sm text-slate-500">No package named “{name}”.</p>;
  return <DetailPanel pkg={data[0]} papers={works.data ?? []} />;
}

export function Explorer() {
  const dir = useQuery<Pkg>(DIR_SQL);
  const works = useQuery<Work>(`${WORK_SELECT} ${WORK_ORDER}`);
  const loading = dir.loading || works.loading;
  const error = dir.error ?? works.error;
  const { params } = useRoute();
  const { q = "", view: viewTerm = "" } = params;
  // `doi=1` is the pre-#31 spelling of `paper=1`; old links keep working.
  const paperOnly = params.paper === "1" || params.doi === "1";
  const repoParam = params.repo;
  const repos = useMemo(() => new Set(parseList(repoParam)), [repoParam]);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [selected, setSelected] = useState<Row | null>(null);

  const all = useMemo<Row[]>(() => {
    const byPkg = new Map<string, Work[]>();
    for (const w of works.data ?? []) {
      const l = byPkg.get(w.package_name);
      if (l) l.push(w);
      else byPkg.set(w.package_name, [w]);
    }
    return (dir.data ?? []).map((p) => {
      const papers = byPkg.get(p.package_name) ?? [];
      return {
        ...p,
        papers,
        n_papers: papers.length,
        search_key: searchKey(p.package_name, p.title, p.description, p.biocviews, p.maintainer),
      };
    });
  }, [dir.data, works.data]);

  const paperCount = useMemo(() => all.filter((p) => p.n_papers > 0).length, [all]);
  const needle = normalise(q);

  const repoCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of all) m.set(p.repo, (m.get(p.repo) ?? 0) + 1);
    return m;
  }, [all]);

  const filtered = useMemo(
    () =>
      all.filter(
        (p) =>
          (repos.size === 0 || repos.has(p.repo)) &&
          (!paperOnly || p.n_papers > 0) &&
          (!viewTerm || splitList(p.biocviews).includes(viewTerm)) &&
          (!needle || p.search_key.includes(needle)),
      ),
    [all, repos, paperOnly, viewTerm, needle],
  );

  const columns = useMemo<ColumnDef<Row>[]>(
    () => [
      {
        accessorKey: "package_name",
        header: "Package",
        cell: ({ row }) => (
          <button
            className="font-medium text-bioc-700 hover:underline"
            onClick={() => setSelected(row.original)}
          >
            {row.original.package_name}
          </button>
        ),
      },
      {
        accessorKey: "repo",
        header: "Repo",
        cell: ({ getValue }) => <RepoBadge repo={getValue<string>()} />,
      },
      { accessorKey: "maintainer", header: "Maintainer" },
      {
        accessorKey: "biocviews",
        header: "biocViews",
        enableSorting: false,
        cell: ({ getValue }) => {
          const v = splitList(getValue<string>());
          return (
            <div className="flex flex-wrap gap-1">
              {v.slice(0, 3).map((t) => (
                <BiocViewChip key={t} term={t} />
              ))}
              {v.length > 3 && <span className="text-xs text-slate-500">+{v.length - 3}</span>}
            </div>
          );
        },
      },
      {
        accessorKey: "n_papers",
        header: "Papers",
        sortDescFirst: true,
        cell: ({ getValue }) => {
          const n = getValue<number>();
          return n > 0 ? n : <span className="text-slate-500">—</span>;
        },
      },
    ],
    [],
  );

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 50 } },
  });

  const total = filtered.length;
  const { pageIndex, pageSize } = table.getState().pagination;

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Failed to load packages: {error.message}
      </div>
    );
  }

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-slate-900">Package explorer</h1>
        <p className="mt-1 text-sm text-slate-500">
          {loading ? "Loading packages…" : `${filtered.length.toLocaleString()} packages`}
          {" · search, sort, and filter the ecosystem."}
        </p>
      </div>

      <div className="flex flex-col gap-5 lg:flex-row">
        {/* Facets */}
        <div className="shrink-0 lg:w-48">
          <SrLabel htmlFor="explorer-search">Search packages</SrLabel>
          <input
            id="explorer-search"
            type="search"
            placeholder="Search…"
            value={q}
            onChange={(e) => setParams("explorer", { q: e.target.value })}
            className={`w-full ${INPUT_CLASS}`}
          />
          <div className="mt-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Repo</div>
            <div className="mt-2 space-y-1">
              {[...repoCounts.entries()]
                .sort((a, b) => b[1] - a[1])
                .map(([r, n]) => (
                  <label key={r} className="flex items-center gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      checked={repos.has(r)}
                      onChange={() => setParams("explorer", { repo: toggleInList(repoParam, r) })}
                    />
                    {REPO_LABEL[r] ?? r}
                    <span className="ml-auto text-xs text-slate-500">{n}</span>
                  </label>
                ))}
            </div>
          </div>
          {viewTerm && (
            <div className="mt-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                biocViews
              </div>
              <div className="mt-2">
                <Chip>
                  {viewTerm}
                  <button
                    className="ml-1 text-bioc-700 hover:text-slate-900"
                    aria-label={`remove ${viewTerm} filter`}
                    onClick={() => setParams("explorer", { view: "" })}
                  >
                    ✕
                  </button>
                </Chip>
              </div>
            </div>
          )}
          <label className="mt-4 flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={paperOnly}
              onChange={(e) => setParams("explorer", { paper: e.target.checked ? "1" : "", doi: "" })}
            />
            Has linked paper
            <span className="ml-auto text-xs text-slate-500">{paperCount}</span>
          </label>
        </div>

        {/* Table */}
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
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-3 py-2 align-top">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
                {!loading && total === 0 && (
                  <tr>
                    <td colSpan={columns.length} className="px-3 py-8 text-center text-slate-500">
                      {q ? `No packages match “${q}”.` : "No packages match these filters."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {/* Pagination */}
          {total > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-500">
              <button
                className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
              >
                ← Prev
              </button>
              <span>
                Page {pageIndex + 1} of{" "}
                {table.getPageCount().toLocaleString()}
              </span>
              <button
                className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
              >
                Next →
              </button>
              <span>
                Showing {(pageIndex * pageSize + 1).toLocaleString()}–
                {Math.min((pageIndex + 1) * pageSize, total).toLocaleString()} of {total.toLocaleString()}
              </span>
              <select
                aria-label="Rows per page"
                className="rounded border border-slate-300 bg-white px-1 py-1"
                value={pageSize}
                onChange={(e) => table.setPageSize(Number(e.target.value))}
              >
                {[25, 50, 100, 250].map((n) => (
                  <option key={n} value={n}>
                    {n} / page
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Detail */}
        {selected && (
          <DetailPanel pkg={selected} papers={selected.papers} onClose={() => setSelected(null)} />
        )}
      </div>
    </div>
  );
}
