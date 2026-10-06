import { useEffect, useMemo, useState } from "react";
import type { VisualizationSpec } from "vega-embed";
import { fetchManifest } from "../db/duckdb";
import { useQuery } from "../db/useQuery";
import { StatCard } from "../components/StatCard";
import { VegaChart } from "../components/VegaChart";
import { REPO_LABEL } from "../components/ui";
import { Link } from "../lib/router";
import { fmtCompact, fmtFloat, fmtInt } from "../lib/format";

const ACCENT = "#1f7bbf";

const ECOSYSTEM = `
  SELECT
    count(*)::INT AS n_packages,
    count(DISTINCT repo)::INT AS n_repos,
    count(DISTINCT maintainer)::INT AS n_maintainers,
    max(latest_release) AS current_release
  FROM 'mart_package_directory.parquet'`;

const BY_REPO = `
  SELECT repo, count(*)::INT AS n
  FROM 'mart_package_directory.parquet' GROUP BY repo ORDER BY n DESC`;

// The four roots of the biocViews taxonomy tag nearly every package; they say nothing in a ranking.
const BIOCVIEWS_ROOTS = "('Software', 'AnnotationData', 'ExperimentData', 'Workflow')";

const BIOCVIEWS_TOP = `
  SELECT term, count(*)::INT AS n
  FROM (SELECT unnest(biocviews) AS term FROM 'mart_package_directory.parquet')
  WHERE term NOT IN ${BIOCVIEWS_ROOTS}
  GROUP BY term ORDER BY n DESC LIMIT 12`;

const BIOCVIEWS_COUNT = `
  SELECT count(DISTINCT term)::INT AS n
  FROM (SELECT unnest(biocviews) AS term FROM 'mart_package_directory.parquet')`;

const IMPACT = `
  SELECT
    (count(*) FILTER (WHERE n_primary_pubs > 0))::INT AS n_pkgs_with_pub,
    (sum(total_distinct_ips))::BIGINT AS total_ips,
    (sum(distinct_ips_trailing_12mo))::BIGINT AS ips_12mo
  FROM 'mart_package_impact.parquet'`;

const GRANTS = `
  SELECT count(*)::INT AS n_grants, count(DISTINCT agency)::INT AS n_institutes
  FROM 'mart_grant_attribution.parquet'`;

// RCR is a normalized rate → summarize by median + p10/p90, never a sum.
const WORKS = `
  SELECT median(icite_rcr) AS median_rcr,
         quantile_cont(icite_rcr, 0.1) AS p10,
         quantile_cont(icite_rcr, 0.9) AS p90,
         (sum(citation_count))::BIGINT AS total_citations,
         (count(*))::INT AS n_works,
         (count(icite_rcr))::INT AS n_with_rcr
  FROM 'mart_work.parquet'`;

const CITES_BY_YEAR = `
  SELECT year, (sum(citation_count))::BIGINT AS citations
  FROM 'mart_work.parquet'
  WHERE year IS NOT NULL AND year BETWEEN 2000 AND 2026
  GROUP BY year ORDER BY year`;

const WORKS_BY_YEAR = `
  SELECT year, (count(*))::INT AS papers
  FROM 'mart_work.parquet'
  WHERE year IS NOT NULL AND year BETWEEN 2000 AND 2026
  GROUP BY year ORDER BY year`;

const TOP_RCR = `
  SELECT package_name, median_rcr
  FROM 'mart_package_impact.parquet'
  WHERE median_rcr IS NOT NULL ORDER BY median_rcr DESC LIMIT 10`;

interface Eco {
  n_packages: number;
  n_repos: number;
  n_maintainers: number;
  current_release: string;
}
interface Impact {
  n_pkgs_with_pub: number;
  total_ips: number;
  ips_12mo: number;
}
interface Works {
  median_rcr: number | null;
  p10: number | null;
  p90: number | null;
  total_citations: number;
  n_works: number;
  n_with_rcr: number;
}

function barSpec(
  values: Record<string, unknown>[],
  field: string,
  label: string,
  title: string,
): VisualizationSpec {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: { text: title, fontSize: 13, color: "#334155" },
    data: { values },
    mark: { type: "bar", color: ACCENT, cornerRadiusEnd: 3 },
    encoding: {
      y: { field: label, type: "nominal", sort: "-x", axis: { title: null, labelLimit: 160 } },
      x: { field, type: "quantitative", axis: { title: null, grid: false } },
      tooltip: [
        { field: label, type: "nominal" },
        { field, type: "quantitative" },
      ],
    },
    width: "container",
    height: { step: 22 },
    config: { view: { stroke: null } },
  } as VisualizationSpec;
}

function yearSpec(
  values: Record<string, unknown>[],
  field: string,
  title: string,
): VisualizationSpec {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: { text: title, fontSize: 13, color: "#334155" },
    data: { values },
    mark: { type: "bar", color: ACCENT },
    encoding: {
      x: { field: "year", type: "ordinal", axis: { title: null, labelAngle: 0, labelOverlap: true } },
      y: { field, type: "quantitative", axis: { title: null, grid: false } },
      tooltip: [
        { field: "year", type: "ordinal" },
        { field, type: "quantitative" },
      ],
    },
    width: "container",
    height: 170,
    config: { view: { stroke: null } },
  } as VisualizationSpec;
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="mt-8 first:mt-0">
      <div className="mb-3 flex items-baseline gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">{title}</h2>
        {note && <span className="text-xs text-slate-500">{note}</span>}
      </div>
      {children}
    </section>
  );
}

const ENTRY_POINTS = [
  {
    view: "grants",
    title: "Writing a grant renewal",
    text: "Find the packages and papers your award produced, with citations and usage to quote.",
  },
  {
    view: "explorer",
    title: "Maintaining a package",
    text: "See how your package is used and cited, and which grants and papers it is linked to.",
  },
  {
    view: "explorer",
    title: "Choosing a tool",
    text: "Search and compare packages by topic, popularity and the papers behind them.",
  },
];

export function ByTheNumbers() {
  const [snapshot, setSnapshot] = useState<string | null>(null);
  useEffect(() => {
    fetchManifest().then((m) => setSnapshot(m.snapshot)).catch(() => setSnapshot(null));
  }, []);
  const snapshotNote = snapshot ? `Snapshot ${snapshot}` : undefined;

  const eco = useQuery<Eco>(ECOSYSTEM);
  const byRepo = useQuery<Record<string, unknown>>(BY_REPO);
  const bvTop = useQuery<Record<string, unknown>>(BIOCVIEWS_TOP);
  const bvCount = useQuery<{ n: number }>(BIOCVIEWS_COUNT);
  const impact = useQuery<Impact>(IMPACT);
  const grants = useQuery<{ n_grants: number; n_institutes: number }>(GRANTS);
  const works = useQuery<Works>(WORKS);
  const byYear = useQuery<Record<string, unknown>>(CITES_BY_YEAR);
  const papersByYear = useQuery<Record<string, unknown>>(WORKS_BY_YEAR);
  const topRcr = useQuery<Record<string, unknown>>(TOP_RCR);

  const repoSpec = useMemo(
    () =>
      byRepo.data
        ? barSpec(
            byRepo.data.map((r) => ({ ...r, repo: REPO_LABEL[r.repo as string] ?? r.repo })),
            "n",
            "repo",
            "Packages per repository",
          )
        : null,
    [byRepo.data],
  );
  const bvSpec = useMemo(
    () => (bvTop.data ? barSpec(bvTop.data, "n", "term", "Top biocViews terms") : null),
    [bvTop.data],
  );
  const rcrSpec = useMemo(
    () =>
      topRcr.data
        ? barSpec(topRcr.data, "median_rcr", "package_name", "Top packages by median RCR")
        : null,
    [topRcr.data],
  );
  const yearChart = useMemo(
    () =>
      byYear.data
        ? yearSpec(byYear.data, "citations", "Citations to describing papers, by the paper's publication year")
        : null,
    [byYear.data],
  );
  const papersChart = useMemo(
    () =>
      papersByYear.data
        ? yearSpec(papersByYear.data, "papers", "Describing papers published per year")
        : null,
    [papersByYear.data],
  );

  if (eco.error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Failed to load data: {eco.error.message}
      </div>
    );
  }
  if (!eco.data) {
    return <div className="py-24 text-center text-slate-400">Booting DuckDB-WASM…</div>;
  }

  const e = eco.data[0];
  const im = impact.data?.[0];
  const g = grants.data?.[0];
  const w = works.data?.[0];
  const downloadsLive = (im?.total_ips ?? 0) > 0;
  const rcrSpread =
    w?.p10 != null && w?.p90 != null ? `p10–p90 ${fmtFloat(w.p10)}–${fmtFloat(w.p90)}` : null;
  const rcrSub = [w ? `n = ${fmtInt(w.n_with_rcr)} of ${fmtInt(w.n_works)}` : null, rcrSpread]
    .filter(Boolean)
    .join(" · ");

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">The Bioconductor ecosystem, by the numbers</h1>
        <p className="mt-1 text-sm text-slate-500">
          Computed live in your browser from the published marts.
        </p>
      </div>

      <div className="mb-8">
        <p className="text-sm text-slate-600">
          Impact analytics for the Bioconductor ecosystem: packages, usage, publications, grants.
          Updated monthly.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {ENTRY_POINTS.map((c) => (
            <Link
              key={c.title}
              view={c.view}
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-bioc-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bioc-500"
            >
              <div className="text-sm font-semibold text-slate-900">{c.title}</div>
              <div className="mt-1 text-xs text-slate-500">{c.text}</div>
            </Link>
          ))}
        </div>
      </div>

      <Section title="Ecosystem">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Packages" value={fmtInt(e.n_packages)} sub={`${e.n_repos} repositories`}
            info="Distinct packages across all four Bioconductor repositories (software, experiment data, annotation, workflows)." />
          <StatCard label="Current release" value={e.current_release} sub="Bioconductor" />
          <StatCard label="Maintainers" value={fmtInt(e.n_maintainers)} sub="distinct"
            info="Distinct package maintainers (by the DESCRIPTION Maintainer field)." />
          <StatCard label="biocViews terms" value={fmtInt(bvCount.data?.[0]?.n)} sub="distinct"
            info="Distinct terms in Bioconductor's controlled vocabulary that classifies what each package does." />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            {repoSpec && <VegaChart spec={repoSpec} subtitle={snapshotNote} className="w-full" />}
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            {bvSpec && <VegaChart spec={bvSpec} subtitle={snapshotNote} className="w-full" />}
          </div>
        </div>
      </Section>

      <Section title="Impact" note="linked so far — grows as enrichment fills in">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <StatCard label="Pkgs w/ publication" value={fmtInt(im?.n_pkgs_with_pub)}
            info="Packages linked to at least one paper the package asks users to cite (via an embedded DOI or the package's CITATION file)." />
          <StatCard label="Linked works" value={fmtInt(w?.n_works)} sub="papers to cite"
            info="Distinct publications linked to packages as papers the package asks users to cite." />
          <StatCard label="Total citations" value={fmtCompact(w?.total_citations)} sub="OpenAlex"
            info="Sum of OpenAlex citation counts across all linked papers the packages ask users to cite. Citations are counts, so summing is meaningful." />
          <StatCard label="Median RCR" value={fmtFloat(w?.median_rcr ?? null, 2)} sub={rcrSub || undefined}
            info="Relative Citation Ratio (NIH iCite): a field- and time-normalized citation rate where 1.0 = the NIH-wide average. Shown as the median across linked papers, with the 10th–90th percentile spread." />
          <StatCard label="NIH grants" value={fmtInt(g?.n_grants)} sub={`${g?.n_institutes ?? 0} NIH Institutes/Centers`}
            info="Distinct NIH awards whose publications are described by a Bioconductor package (linked via NIH RePORTER)." />
          <StatCard
            label="Distinct-IP downloads"
            value={downloadsLive ? fmtCompact(im?.ips_12mo) : "pending"}
            sub={downloadsLive ? `last 12 months · ${fmtCompact(im?.total_ips)} all-time` : "stats endpoint offline"}
            pending={!downloadsLive}
            info="Sum of monthly distinct downloading IPs — the usage proxy (less gameable than raw downloads). An IP active in several months counts once per month. Collection methodology changed in Oct 2015, so all-time totals span two eras."
          />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            {papersChart && <VegaChart spec={papersChart} subtitle={snapshotNote} className="w-full" />}
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            {yearChart && <VegaChart spec={yearChart} subtitle={snapshotNote} className="w-full" />}
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            {rcrSpec && <VegaChart spec={rcrSpec} subtitle={snapshotNote} className="w-full" />}
          </div>
        </div>
      </Section>
    </div>
  );
}
