import { useMemo, useState } from "react";
import type { VisualizationSpec } from "vega-embed";
import { useQuery } from "../db/useQuery";
import { VegaChart } from "../components/VegaChart";
import { CATEGORY, METRIC, TITLE_COLOR } from "../components/charts";
import { ERA_START, eraBand, monthlyIpsSpec, Sparkline, type MonthlyRow } from "../components/Sparkline";
import { Chip, INPUT_CLASS, REPO_LABEL, RepoBadge, SrLabel } from "../components/ui";
import { Link, parseList, setParams, useRoute } from "../lib/router";
import { fmtFloat, fmtInt } from "../lib/format";

interface YearRow {
  year: number;
  repo: string;
  methodology_era: string;
  n_packages_with_downloads: number;
}

interface InstallerRow {
  year: number;
  methodology_era: string;
  installer_distinct_ips: number;
}

interface TrendRow {
  package_name: string;
  repo: string;
  trailing: number;
  prior: number;
  ratio: number;
}

const YEARLY_SQL = `
  SELECT year, repo, methodology_era, n_packages_with_downloads
  FROM 'mart_ecosystem_downloads_yearly.parquet' ORDER BY year, repo`;

// Project-level installs per year: the installer package's monthly distinct IPs, summed. Only
// calendar years with all 12 months loaded, so the first partial year and the current one drop.
const INSTALLER_SQL = `
  WITH full_years AS (
    SELECT year FROM 'mart_installer_downloads_monthly.parquet' GROUP BY year HAVING count(*) = 12)
  SELECT year, methodology_era, sum(installer_distinct_ips)::BIGINT AS installer_distinct_ips
  FROM 'mart_installer_downloads_monthly.parquet'
  WHERE year IN (SELECT year FROM full_years)
  GROUP BY year, methodology_era ORDER BY year`;

const NAMES_SQL = `SELECT package_name FROM 'mart_package_directory.parquet' ORDER BY package_name`;

// Growth ratio over the last two 12-month windows. The history and prior-12 floors keep
// brand-new packages out, and Infrastructure is excluded because newly split infrastructure
// (e.g. Seqinfo) otherwise dominates raw growth.
const TRENDING_SQL = `
  WITH hist AS (
    SELECT package_name, repo, count(*) AS n_months
    FROM 'mart_package_downloads_monthly.parquet' GROUP BY package_name, repo)
  SELECT i.package_name, i.repo,
         i.distinct_ips_trailing_12mo AS trailing, i.distinct_ips_prior_12mo AS prior,
         i.distinct_ips_trailing_12mo / i.distinct_ips_prior_12mo AS ratio
  FROM 'mart_package_impact.parquet' i
  JOIN hist USING (package_name, repo)
  JOIN 'mart_package_directory.parquet' d USING (package_name, repo)
  WHERE hist.n_months >= 24 AND i.distinct_ips_prior_12mo >= 1200
    AND NOT list_contains(coalesce(d.biocviews, []), 'Infrastructure')
  ORDER BY ratio DESC LIMIT 25`;

const MAX_COMPARE = 5;
const sqlList = (names: string[]) => names.map((n) => `'${n.replace(/'/g, "''")}'`).join(", ");
const monthlySql = (names: string[]) => `
  SELECT package_name, year, month, distinct_ips, methodology_era
  FROM 'mart_package_downloads_monthly.parquet'
  WHERE package_name IN (${sqlList(names)}) ORDER BY package_name, year, month`;

// 2015 is split at the boundary into Jan–Sep and Oct–Dec rows; plot each at the middle of
// the months it covers so they fall either side of the band.
const yearX = (year: number, era: string) =>
  year === 2015 ? (era === "modern" ? "2015-11-15" : "2015-05-01") : `${year}-07-01`;

function installerSpec(rows: InstallerRow[]): VisualizationSpec {
  const values = rows.map((r) => ({ ...r, x: yearX(r.year, r.methodology_era) }));
  const title = "Machines installing Bioconductor per year";
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: { text: title, fontSize: 13, color: TITLE_COLOR },
    width: "container",
    height: 260,
    layer: [
      eraBand(`${Math.min(...rows.map((r) => r.year))}-01-01`),
      {
        data: { values },
        mark: { type: "line", point: true, color: METRIC.usage },
        encoding: {
          x: { field: "x", type: "temporal", axis: { title: null, format: "%Y" } },
          y: { field: "installer_distinct_ips", type: "quantitative", axis: { title: null } },
          detail: { field: "methodology_era" },
          tooltip: [
            { field: "year", type: "ordinal", title: "Year" },
            { field: "methodology_era", type: "nominal", title: "Era" },
            { field: "installer_distinct_ips", type: "quantitative", format: ",", title: "Distinct IPs (installer)" },
          ],
        },
      },
    ],
    config: { view: { stroke: null } },
  } as VisualizationSpec;
}

function yearlySpec(rows: YearRow[], field: keyof YearRow, title: string): VisualizationSpec {
  const values = rows.map((r) => ({
    ...r,
    repo: REPO_LABEL[r.repo] ?? r.repo,
    x: yearX(r.year, r.methodology_era),
  }));
  const first = `${Math.min(...rows.map((r) => r.year))}-01-01`;
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: { text: title, fontSize: 13, color: TITLE_COLOR },
    width: "container",
    height: 260,
    layer: [
      eraBand(first),
      {
        data: { values },
        mark: { type: "line", point: true },
        encoding: {
          x: { field: "x", type: "temporal", axis: { title: null, format: "%Y" } },
          y: { field, type: "quantitative", axis: { title: null } },
          color: {
            field: "repo",
            type: "nominal",
            scale: { range: CATEGORY },
            legend: { orient: "top", title: null },
          },
          detail: { field: "methodology_era" },
          tooltip: [
            { field: "repo", type: "nominal", title: "Repo" },
            { field: "year", type: "ordinal", title: "Year" },
            { field: "methodology_era", type: "nominal", title: "Era" },
            { field, type: "quantitative", format: ",", title },
          ],
        },
      },
    ],
    config: { view: { stroke: null } },
  } as VisualizationSpec;
}

function EraCaption({ fullYears = false }: { fullYears?: boolean }) {
  return (
    <p className="mt-2 text-xs text-neutral-300">
      The shaded region is before {ERA_START.slice(0, 7)}, when download-log collection changed;
      counts either side are not comparable, so lines break at the boundary. 2015 appears as two
      partial-year points (Jan–Sep, Oct–Dec)
      {fullYears ? "; only complete calendar years are shown." : ", and the latest year is year-to-date."}
    </p>
  );
}

function Compare() {
  const { params } = useRoute();
  const picked = useMemo(() => parseList(params.pkgs).slice(0, MAX_COMPARE), [params.pkgs]);
  const log = params.log === "1";
  const names = useQuery<{ package_name: string }>(NAMES_SQL);
  const known = useMemo(() => new Set((names.data ?? []).map((r) => r.package_name)), [names.data]);
  const [draft, setDraft] = useState("");
  const series = useQuery<MonthlyRow>(picked.length ? monthlySql(picked) : null);
  const spec = useMemo(
    () => (series.data?.length ? monthlyIpsSpec(series.data, { height: 300, log, axes: true }) : null),
    [series.data, log],
  );

  const setPicked = (l: string[]) => setParams("trends", { pkgs: l.join("|") });
  const add = () => {
    const name = draft.trim();
    if (!known.has(name) || picked.includes(name) || picked.length >= MAX_COMPARE) return;
    setPicked([...picked, name]);
    setDraft("");
  };

  return (
    <section className="mt-6 rounded-xl border border-primary-75 bg-white p-4">
      <h2 className="text-sm font-semibold text-neutral-400">Compare packages</h2>
      <p className="mt-1 text-xs text-neutral-300">
        Monthly distinct IPs for up to {MAX_COMPARE} packages.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <SrLabel htmlFor="trends-package">Package name</SrLabel>
        <input
          id="trends-package"
          list="trends-package-names"
          placeholder="Package name…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          disabled={picked.length >= MAX_COMPARE}
          className={`w-56 ${INPUT_CLASS} disabled:opacity-50`}
        />
        <datalist id="trends-package-names">
          {(names.data ?? []).map((r) => (
            <option key={r.package_name} value={r.package_name} />
          ))}
        </datalist>
        <button
          onClick={add}
          disabled={!known.has(draft.trim()) || picked.length >= MAX_COMPARE}
          className="rounded-md bg-primary-400 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-400 focus-visible:ring-offset-2 disabled:opacity-40"
        >
          Add
        </button>
        {picked.map((p) => (
          <Chip key={p}>
            {p}
            <button
              className="ml-1 text-primary-400 hover:text-ink"
              aria-label={`remove ${p}`}
              onClick={() => setPicked(picked.filter((x) => x !== p))}
            >
              ✕
            </button>
          </Chip>
        ))}
        <label className="ml-auto flex items-center gap-2 text-sm text-neutral-400">
          <input
            type="checkbox"
            checked={log}
            onChange={(e) => setParams("trends", { log: e.target.checked ? "1" : "" })}
          />
          Log scale
        </label>
      </div>
      {series.error && (
        <p className="mt-3 text-sm text-red-700">Failed to load monthly data: {series.error.message}</p>
      )}
      {picked.length === 0 ? (
        <p className="mt-4 text-sm text-neutral-300">Add a package to plot its monthly usage.</p>
      ) : series.loading ? (
        <p className="mt-4 text-sm text-neutral-300">Loading…</p>
      ) : spec ? (
        <div className="mt-4">
          <VegaChart spec={spec} className="w-full" />
          <EraCaption />
        </div>
      ) : (
        <p className="mt-4 text-sm text-neutral-300">No download history for these packages.</p>
      )}
    </section>
  );
}

function Trending() {
  const { data, loading, error } = useQuery<TrendRow>(TRENDING_SQL);
  const names = useMemo(() => (data ?? []).map((r) => r.package_name), [data]);
  const series = useQuery<MonthlyRow>(names.length ? monthlySql(names) : null);
  const byPkg = useMemo(() => {
    const m = new Map<string, MonthlyRow[]>();
    for (const r of series.data ?? []) {
      const l = m.get(r.package_name!);
      if (l) l.push(r);
      else m.set(r.package_name!, [r]);
    }
    return m;
  }, [series.data]);

  return (
    <section className="mt-6 rounded-xl border border-primary-75 bg-white p-4">
      <h2 className="text-sm font-semibold text-neutral-400">Trending</h2>
      <p className="mt-1 text-xs text-neutral-300">
        Distinct IPs in the last 12 months over the 12 before. Packages need at least 24 months of
        history and 1,200 distinct IPs in the prior 12; packages tagged Infrastructure are excluded.
      </p>
      {error ? (
        <p className="mt-3 text-sm text-red-700">Failed to load trending packages: {error.message}</p>
      ) : loading ? (
        <p className="mt-3 text-sm text-neutral-300">Loading…</p>
      ) : (
        <table className="mt-3 w-full text-left text-sm">
          <thead className="border-b border-primary-75 text-xs uppercase tracking-wide text-neutral-300">
            <tr>
              <th scope="col" className="px-3 py-2">Package</th>
              <th scope="col" className="px-3 py-2">Repo</th>
              <th scope="col" className="px-3 py-2 text-right">Prior 12 mo</th>
              <th scope="col" className="px-3 py-2 text-right">Last 12 mo</th>
              <th scope="col" className="px-3 py-2 text-right">Growth</th>
              <th scope="col" className="px-3 py-2">Monthly distinct IPs</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((r) => (
              <tr key={r.package_name} className="border-b border-neutral-75 last:border-0">
                <td className="px-3 py-2">
                  <Link view="package" arg={r.package_name} className="font-medium text-primary-400 hover:underline">
                    {r.package_name}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <RepoBadge repo={r.repo} />
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-metric-usage">{fmtInt(r.prior)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-metric-usage">{fmtInt(r.trailing)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-metric-usage">{fmtFloat(r.ratio, 2)}×</td>
                <td className="w-48 px-3 py-1">
                  {byPkg.has(r.package_name) && <Sparkline rows={byPkg.get(r.package_name)!} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function Trends() {
  const yearly = useQuery<YearRow>(YEARLY_SQL);
  const installer = useQuery<InstallerRow>(INSTALLER_SQL);
  const installsSpec = useMemo(
    () => (installer.data?.length ? installerSpec(installer.data) : null),
    [installer.data],
  );
  const packagesSpec = useMemo(
    () =>
      yearly.data?.length
        ? yearlySpec(yearly.data, "n_packages_with_downloads", "Packages with downloads per year")
        : null,
    [yearly.data],
  );
  const error = yearly.error ?? installer.error;

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-ink">Usage trends</h1>
        <p className="mt-1 text-sm text-neutral-300">
          Download telemetry from the Bioconductor stats logs. Distinct IPs are the usage proxy.
        </p>
      </div>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
          Failed to load yearly downloads: {error.message}
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-primary-75 bg-white p-4">
            {installsSpec && <VegaChart spec={installsSpec} className="w-full" />}
            <p className="mt-2 text-xs text-neutral-300">
              Distinct IPs downloading the installer package each month, summed over the year:
              BiocVersion (installed by BiocManager) since 2018, BiocInstaller before it.
            </p>
            <EraCaption fullYears />
          </div>
          <div className="rounded-xl border border-primary-75 bg-white p-4">
            {packagesSpec && <VegaChart spec={packagesSpec} className="w-full" />}
            <EraCaption />
          </div>
        </div>
      )}
      <p className="mt-3 text-xs text-neutral-300">
        The series below are per package. Distinct IPs do not add up across packages: one machine
        installing 50 packages counts once in each.
      </p>

      <Compare />
      <Trending />
    </div>
  );
}
