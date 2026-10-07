import { useMemo, useState } from "react";
import type { VisualizationSpec } from "vega-embed";
import { useQuery } from "../db/useQuery";
import { VegaChart } from "../components/VegaChart";
import { eraBand, ERA_START } from "../components/Sparkline";
import { CATEGORY, horizontalBar, METRIC, TITLE_COLOR } from "../components/charts";
import { StatCard } from "../components/StatCard";
import { REPO_LABEL } from "../components/ui";
import { fmtInt } from "../lib/format";

interface Release {
  bioc_release: string;
  date: string;
  n_software_announced: number | null;
  n_packages: number | null;
  n_new_packages: number | null;
  n_removed: number | null;
}

interface RepoRelease {
  bioc_release: string;
  date: string;
  repo: string;
  n_packages: number;
  n_new: number | null;
  n_removed: number | null;
}

interface YearRow {
  year: number;
  methodology_era: string;
  distinct_ips: number;
}

// Release order is numeric (3.9 < 3.10).
const RELEASE_ORDER = "string_split(bioc_release, '.')::INT[]";

const RELEASES = `
  SELECT bioc_release, strftime(release_date, '%Y-%m-%d') AS date, n_software_announced,
         n_packages, n_new_packages, n_removed
  FROM 'mart_release_growth.parquet' ORDER BY ${RELEASE_ORDER}`;

const BY_REPO = `
  SELECT bioc_release, strftime(release_date, '%Y-%m-%d') AS date, repo, n_packages, n_new, n_removed
  FROM 'mart_release_history.parquet' ORDER BY ${RELEASE_ORDER}, repo`;

const YEARLY = `
  SELECT year, methodology_era, sum(distinct_ips)::BIGINT AS distinct_ips
  FROM 'mart_ecosystem_downloads_yearly.parquet' GROUP BY year, methodology_era ORDER BY year`;

interface CountryRow {
  country: string;
  n_works: number;
}

interface InstitutionRow {
  name: string;
  country: string | null;
  n_works: number;
}

interface Coverage {
  with_institution: number;
  total: number;
}

// Works are distinct: a paper with several authors at one institution or country counts once.
const countryQuery = (seniorOnly: boolean) => `
  SELECT country, count(DISTINCT work_id)::INT AS n_works
  FROM 'mart_work_institution.parquet'
  WHERE country IS NOT NULL ${seniorOnly ? "AND author_position = 'last'" : ""}
  GROUP BY country ORDER BY n_works DESC, country LIMIT 15`;

const INSTITUTIONS = `
  SELECT name, any_value(country) AS country, count(DISTINCT work_id)::INT AS n_works
  FROM 'mart_work_institution.parquet'
  GROUP BY ror, name ORDER BY n_works DESC, name LIMIT 25`;

const COVERAGE = `
  SELECT (SELECT count(DISTINCT work_id) FROM 'mart_work_institution.parquet')::INT
           AS with_institution,
         (SELECT count(*) FROM 'mart_work.parquet')::INT AS total`;

const VIEWS_SOURCE = "Release VIEWS";
const ANNOUNCED_SOURCE = "Announced count only";

const title = (text: string) => ({ text, fontSize: 13, color: TITLE_COLOR });
const repoLabel = (repo: string) => REPO_LABEL[repo] ?? repo;

// Per-repo counts come from each release's VIEWS (1.8 onwards). Releases 1.0–1.7 have only
// the software count from the release announcements: drawn dashed, joined to 1.8 so the
// line reads continuously from 2002.
function packagesSpec(byRepo: RepoRelease[], releases: Release[]): VisualizationSpec {
  const firstViews = byRepo[0]?.bioc_release;
  const cut = releases.findIndex((r) => r.bioc_release === firstViews);
  const announced = releases
    .slice(0, cut + 1)
    .filter((r) => r.n_software_announced != null && r.date)
    .map((r) => ({ ...r, repo: "Software", n: r.n_software_announced, source: ANNOUNCED_SOURCE }));
  const values = [
    ...announced,
    ...byRepo.map((r) => ({ ...r, repo: repoLabel(r.repo), n: r.n_packages, source: VIEWS_SOURCE })),
  ];
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: title("Packages per release, by repository"),
    data: { values },
    mark: { type: "line", point: true },
    encoding: {
      x: { field: "date", type: "temporal", axis: { title: null, format: "%Y" } },
      y: { field: "n", type: "quantitative", axis: { title: null } },
      color: {
        field: "repo",
        type: "nominal",
        scale: { range: CATEGORY },
        legend: { orient: "top", title: null },
      },
      strokeDash: {
        field: "source",
        type: "nominal",
        sort: [VIEWS_SOURCE, ANNOUNCED_SOURCE],
        legend: { orient: "top", title: null, symbolType: "stroke", labelLimit: 200 },
      },
      tooltip: [
        { field: "bioc_release", type: "nominal", title: "Release" },
        { field: "date", type: "nominal", title: "Date" },
        { field: "repo", type: "nominal", title: "Repo" },
        { field: "n", type: "quantitative", format: ",", title: "Packages" },
        { field: "source", type: "nominal", title: "Source" },
      ],
    },
    width: "container",
    height: 280,
    config: { view: { stroke: null } },
  } as VisualizationSpec;
}

// New above zero, removed below, stacked by repo. The first release with VIEWS has no
// predecessor, so it has no bars.
function churnSpec(byRepo: RepoRelease[]): VisualizationSpec {
  const order = [...new Set(byRepo.map((r) => r.bioc_release))];
  const values = byRepo
    .filter((r) => r.n_new != null)
    .flatMap((r) => [
      { ...r, repo: repoLabel(r.repo), kind: "New", n: r.n_new },
      { ...r, repo: repoLabel(r.repo), kind: "Removed", n: -(r.n_removed ?? 0) },
    ]);
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: title("New (up) and removed (down) packages per release"),
    data: { values },
    mark: { type: "bar" },
    encoding: {
      x: { field: "bioc_release", type: "ordinal", sort: order, axis: { title: null, labelAngle: -60 } },
      y: { field: "n", type: "quantitative", axis: { title: null } },
      color: {
        field: "repo",
        type: "nominal",
        scale: { range: CATEGORY },
        legend: { orient: "top", title: null },
      },
      tooltip: [
        { field: "bioc_release", type: "nominal", title: "Release" },
        { field: "repo", type: "nominal", title: "Repo" },
        { field: "kind", type: "nominal", title: "Change" },
        { field: "n", type: "quantitative", format: ",", title: "Packages (removed < 0)" },
      ],
    },
    width: "container",
    height: 260,
    config: { view: { stroke: null } },
  } as VisualizationSpec;
}

// 2015 is split at the methodology boundary into Jan–Sep and Oct–Dec rows; plot each at
// the middle of the months it covers so they fall either side of the band.
const yearX = (year: number, era: string) =>
  year === 2015 ? (era === "modern" ? "2015-11-15" : "2015-05-01") : `${year}-07-01`;

function usageSpec(rows: YearRow[]): VisualizationSpec {
  const values = rows.map((r) => ({ ...r, x: yearX(r.year, r.methodology_era) }));
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: title("Distinct IPs per year, all repositories"),
    width: "container",
    height: 240,
    layer: [
      eraBand(`${Math.min(...rows.map((r) => r.year))}-01-01`),
      {
        data: { values },
        mark: { type: "line", point: true, color: METRIC.usage },
        encoding: {
          x: { field: "x", type: "temporal", axis: { title: null, format: "%Y" } },
          y: { field: "distinct_ips", type: "quantitative", axis: { title: null } },
          detail: { field: "methodology_era" },
          tooltip: [
            { field: "year", type: "ordinal", title: "Year" },
            { field: "methodology_era", type: "nominal", title: "Era" },
            { field: "distinct_ips", type: "quantitative", format: ",", title: "Distinct IPs" },
          ],
        },
      },
    ],
    config: { view: { stroke: null } },
  } as VisualizationSpec;
}

// Hidden until the institution mart is published, and if it fails to load.
function PaperOrigins() {
  const [seniorOnly, setSeniorOnly] = useState(true);
  const countries = useQuery<CountryRow>(countryQuery(seniorOnly));
  const institutions = useQuery<InstitutionRow>(INSTITUTIONS);
  const coverage = useQuery<Coverage>(COVERAGE);

  const chart = useMemo(
    () =>
      countries.data?.length
        ? horizontalBar(
            countries.data as unknown as Record<string, unknown>[],
            "n_works",
            "country",
            seniorOnly
              ? "Linked papers by senior-author country"
              : "Linked papers by country of any author",
            METRIC.pubs,
          )
        : null,
    [countries.data, seniorOnly],
  );

  if (countries.error || institutions.error || coverage.error) return null;
  const cov = coverage.data?.[0];

  return (
    <div className={PANEL}>
      <h2 className="text-lg font-semibold text-ink">Where the papers come from</h2>
      <p className="mt-1 text-sm text-neutral-300">
        {cov
          ? `${fmtInt(cov.with_institution)} of ${fmtInt(cov.total)} linked papers have at least one institution. `
          : ""}
        Affiliations come from the OpenAlex authorships of the papers packages ask users to cite,
        not from package maintainers.
      </p>
      <label className="mt-3 flex items-center gap-2 text-sm text-neutral-400">
        <input
          type="checkbox"
          checked={!seniorOnly}
          onChange={(e) => setSeniorOnly(!e.target.checked)}
        />
        Any author position (default: senior, i.e. last, author only)
      </label>
      <div className="mt-2">{chart && <VegaChart spec={chart} className="w-full" />}</div>
      <p className="mt-2 text-xs text-neutral-300">
        Distinct papers per country; a paper with authors in several countries counts once in each.
      </p>

      <h3 className="mt-5 text-sm font-semibold text-neutral-400">Top institutions</h3>
      <table className="mt-2 w-full text-sm">
        <thead className="text-xs uppercase tracking-wide text-neutral-300">
          <tr>
            <th className="px-2 py-1 text-left">Institution</th>
            <th className="px-2 py-1 text-left">Country</th>
            <th className="px-2 py-1 text-right">Papers</th>
          </tr>
        </thead>
        <tbody>
          {(institutions.data ?? []).map((r) => (
            <tr key={`${r.name}|${r.country}`} className="border-t border-primary-75">
              <td className="px-2 py-1">{r.name}</td>
              <td className="px-2 py-1">{r.country ?? "—"}</td>
              <td className="px-2 py-1 text-right tabular-nums text-metric-pubs">{fmtInt(r.n_works)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const PANEL = "mt-4 rounded-xl border border-primary-75 bg-white p-4";

export function Growth() {
  const releases = useQuery<Release>(RELEASES);
  const byRepo = useQuery<RepoRelease>(BY_REPO);
  const yearly = useQuery<YearRow>(YEARLY);

  const packages = useMemo(
    () => (byRepo.data?.length && releases.data ? packagesSpec(byRepo.data, releases.data) : null),
    [byRepo.data, releases.data],
  );
  const churn = useMemo(() => (byRepo.data?.length ? churnSpec(byRepo.data) : null), [byRepo.data]);
  const usage = useMemo(() => (yearly.data?.length ? usageSpec(yearly.data) : null), [yearly.data]);

  const error = releases.error ?? byRepo.error;
  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Failed to load growth data: {error.message}
      </div>
    );
  }

  const rows = releases.data ?? [];
  const withViews = rows.filter((r) => r.n_packages != null);
  const latest = withViews[withViews.length - 1];

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-ink">Ecosystem growth</h1>
        <p className="mt-1 text-sm text-neutral-300">
          Bioconductor release by release since {rows[0]?.date?.slice(0, 4) ?? "—"}, from each
          release's package index and the release announcements.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Current release" value={latest?.bioc_release ?? "—"} sub={latest?.date} />
        <StatCard label="Packages" value={fmtInt(latest?.n_packages)} sub="all repositories, this release" />
        <StatCard
          label="New this release"
          value={fmtInt(latest?.n_new_packages)}
          sub={`${fmtInt(latest?.n_removed)} removed`}
          info="A package is new in the first release whose package index lists it, in any repository; removed means listed in the previous release and not in this one."
        />
        <StatCard
          label="Releases"
          value={fmtInt(rows.length)}
          sub={`${fmtInt(withViews.length)} with a package index (1.8 onwards)`}
        />
      </div>

      <div className={PANEL}>
        {packages && <VegaChart spec={packages} className="w-full" />}
        <p className="mt-2 text-xs text-neutral-300">
          Releases before 1.8 have no package index online; the dashed line is the software count
          from the release announcements, with no per-repository breakdown.
        </p>
      </div>

      <div className={PANEL}>
        {churn && <VegaChart spec={churn} className="w-full" />}
        <p className="mt-2 text-xs text-neutral-300">
          Annotation-package counts swing sharply in a few early releases (1.9, 2.0, 2.2), as listed
          in those releases' package indexes. The first indexed release (1.8) has no predecessor to
          diff against.
        </p>
      </div>

      <div className={PANEL}>
        {usage && <VegaChart spec={usage} className="w-full" />}
        <p className="mt-2 text-xs text-neutral-300">
          Distinct IPs summed over packages and months. The shaded region is before{" "}
          {ERA_START.slice(0, 7)}, when download-log collection changed; counts either side are
          not comparable, so the line breaks at the boundary. The latest year is year-to-date.
        </p>
      </div>

      <PaperOrigins />
    </div>
  );
}
