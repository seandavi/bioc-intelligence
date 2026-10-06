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
import { BiocViewChip, Chip, REPO_LABEL, RepoBadge } from "../components/ui";
import { parseList, setParams, toggleInList, useRoute } from "../lib/router";

interface Pkg {
  package_name: string;
  repo: string;
  latest_release: string;
  maintainer: string | null;
  maintainer_email: string | null;
  title: string | null;
  biocviews: string; // '|'-joined
  url: string; // '|'-joined
  bug_reports: string | null;
  source_doi: string | null;
}

// array_to_string keeps list columns simple across the WASM boundary.
const DIR_SELECT = `
  SELECT package_name, repo, latest_release, maintainer, maintainer_email, title,
         array_to_string(biocviews, '|') AS biocviews,
         array_to_string(url, '|')       AS url,
         bug_reports, source_doi
  FROM 'mart_package_directory.parquet'`;
const DIR_SQL = `${DIR_SELECT} ORDER BY package_name`;

const splitList = (s: string | null) => (s ? s.split("|").filter(Boolean) : []);

function DetailPanel({ pkg, onClose }: { pkg: Pkg; onClose?: () => void }) {
  const views = splitList(pkg.biocviews);
  const urls = splitList(pkg.url);
  return (
    <aside className="w-full shrink-0 rounded-xl border border-slate-200 bg-white p-4 lg:w-80">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-lg font-semibold text-slate-900">{pkg.package_name}</div>
          <div className="mt-0.5 flex items-center gap-2">
            <RepoBadge repo={pkg.repo} />
            <span className="text-xs text-slate-400">release {pkg.latest_release}</span>
          </div>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="close">
            ✕
          </button>
        )}
      </div>
      {pkg.title && <p className="mt-3 text-sm text-slate-700">{pkg.title}</p>}
      <dl className="mt-3 space-y-2 text-sm">
        {pkg.maintainer && (
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-400">Maintainer</dt>
            <dd className="text-slate-700">
              {pkg.maintainer_email ? (
                <a className="text-bioc-600 hover:underline" href={`mailto:${pkg.maintainer_email}`}>
                  {pkg.maintainer}
                </a>
              ) : (
                pkg.maintainer
              )}
            </dd>
          </div>
        )}
        {pkg.source_doi && (
          <div>
            <dt className="text-xs uppercase tracking-wide text-slate-400">Describing paper</dt>
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
            <dt className="text-xs uppercase tracking-wide text-slate-400">Links</dt>
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
            <dt className="text-xs uppercase tracking-wide text-slate-400">biocViews</dt>
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
  const { data, loading, error } = useQuery<Pkg>(
    `${DIR_SELECT} WHERE package_name = '${name.replaceAll("'", "''")}'`,
  );
  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Failed to load package: {error.message}
      </div>
    );
  }
  if (loading) return <p className="text-sm text-slate-500">Loading {name}…</p>;
  if (!data?.length) return <p className="text-sm text-slate-500">No package named “{name}”.</p>;
  return <DetailPanel pkg={data[0]} />;
}

export function Explorer() {
  const { data, loading, error } = useQuery<Pkg>(DIR_SQL);
  const { params } = useRoute();
  const { q: globalFilter = "", view: viewTerm = "" } = params;
  const doiOnly = params.doi === "1";
  const repoParam = params.repo;
  const repos = useMemo(() => new Set(parseList(repoParam)), [repoParam]);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [selected, setSelected] = useState<Pkg | null>(null);

  const all = useMemo(() => data ?? [], [data]);

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
          (!doiOnly || p.source_doi != null) &&
          (!viewTerm || splitList(p.biocviews).includes(viewTerm)),
      ),
    [all, repos, doiOnly, viewTerm],
  );

  const columns = useMemo<ColumnDef<Pkg>[]>(
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
              {v.length > 3 && <span className="text-xs text-slate-400">+{v.length - 3}</span>}
            </div>
          );
        },
      },
      {
        accessorKey: "source_doi",
        header: "DOI",
        cell: ({ getValue }) => {
          const doi = getValue<string | null>();
          return doi ? (
            <a
              className="text-bioc-600 hover:underline"
              href={`https://doi.org/${doi}`}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
            >
              link
            </a>
          ) : (
            <span className="text-slate-300">—</span>
          );
        },
      },
    ],
    [],
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
    initialState: { pagination: { pageSize: 50 } },
  });

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
          <input
            type="search"
            placeholder="Search…"
            value={globalFilter}
            onChange={(e) => setParams("explorer", { q: e.target.value })}
            className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-bioc-500 focus:outline-none"
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
                    <span className="ml-auto text-xs text-slate-400">{n}</span>
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
            <input type="checkbox" checked={doiOnly} onChange={(e) => setParams("explorer", { doi: e.target.checked ? "1" : "" })} />
            Has describing DOI
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
                      <th
                        key={h.id}
                        onClick={h.column.getToggleSortingHandler()}
                        className={`px-3 py-2 ${
                          h.column.getCanSort() ? "cursor-pointer select-none hover:text-slate-700" : ""
                        }`}
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
                  <tr key={row.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-3 py-2 align-top">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Pagination */}
          <div className="mt-3 flex items-center gap-3 text-sm text-slate-500">
            <button
              className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              ← Prev
            </button>
            <span>
              Page {table.getState().pagination.pageIndex + 1} of{" "}
              {table.getPageCount().toLocaleString()}
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

        {/* Detail */}
        {selected && <DetailPanel pkg={selected} onClose={() => setSelected(null)} />}
      </div>
    </div>
  );
}
