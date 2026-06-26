import { useMemo } from "react";
import type { VisualizationSpec } from "vega-embed";
import { useQuery } from "../db/useQuery";
import { StatCard } from "../components/StatCard";
import { VegaChart } from "../components/VegaChart";
import { fmtCompact, fmtFloat, fmtInt } from "../lib/format";

const ACCENT = "#1f7bbf";

const ECOSYSTEM = `
  SELECT
    count(*)::INT AS n_packages,
    count(DISTINCT repo)::INT AS n_repos,
    count(DISTINCT maintainer)::INT AS n_maintainers,
    (count(*) FILTER (WHERE source_doi IS NOT NULL))::INT AS n_with_doi,
    max(latest_release) AS current_release
  FROM 'mart_package_directory.parquet'`;

const BY_REPO = `
  SELECT repo, count(*)::INT AS n
  FROM 'mart_package_directory.parquet' GROUP BY repo ORDER BY n DESC`;

const BIOCVIEWS_TOP = `
  SELECT term, count(*)::INT AS n
  FROM (SELECT unnest(biocviews) AS term FROM 'mart_package_directory.parquet')
  GROUP BY term ORDER BY n DESC LIMIT 12`;

const BIOCVIEWS_COUNT = `
  SELECT count(DISTINCT term)::INT AS n
  FROM (SELECT unnest(biocviews) AS term FROM 'mart_package_directory.parquet')`;

const IMPACT = `
  SELECT
    (count(*) FILTER (WHERE n_primary_pubs > 0))::INT AS n_pkgs_with_pub,
    (sum(n_primary_pubs))::INT AS n_links,
    (sum(n_citing_works))::INT AS n_citing,
    sum(sum_rcr) AS total_rcr,
    (count(*) FILTER (WHERE n_distinct_grants_citing > 0))::INT AS n_pkgs_with_grant,
    (sum(total_distinct_ips))::BIGINT AS total_ips
  FROM 'mart_package_impact.parquet'`;

const GRANTS = `
  SELECT count(*)::INT AS n_grants, count(DISTINCT agency)::INT AS n_agencies
  FROM 'mart_grant_attribution.parquet'`;

const TOP_RCR = `
  SELECT package_name, sum_rcr
  FROM 'mart_package_impact.parquet'
  WHERE sum_rcr IS NOT NULL ORDER BY sum_rcr DESC LIMIT 10`;

interface Eco {
  n_packages: number;
  n_repos: number;
  n_maintainers: number;
  n_with_doi: number;
  current_release: string;
}
interface Impact {
  n_pkgs_with_pub: number;
  n_links: number;
  n_citing: number;
  total_rcr: number | null;
  n_pkgs_with_grant: number;
  total_ips: number;
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

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="mt-8 first:mt-0">
      <div className="mb-3 flex items-baseline gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">{title}</h2>
        {note && <span className="text-xs text-slate-400">{note}</span>}
      </div>
      {children}
    </section>
  );
}

export function ByTheNumbers() {
  const eco = useQuery<Eco>(ECOSYSTEM);
  const byRepo = useQuery<Record<string, unknown>>(BY_REPO);
  const bvTop = useQuery<Record<string, unknown>>(BIOCVIEWS_TOP);
  const bvCount = useQuery<{ n: number }>(BIOCVIEWS_COUNT);
  const impact = useQuery<Impact>(IMPACT);
  const grants = useQuery<{ n_grants: number; n_agencies: number }>(GRANTS);
  const topRcr = useQuery<Record<string, unknown>>(TOP_RCR);

  const repoSpec = useMemo(
    () => (byRepo.data ? barSpec(byRepo.data, "n", "repo", "Packages per repository") : null),
    [byRepo.data],
  );
  const bvSpec = useMemo(
    () => (bvTop.data ? barSpec(bvTop.data, "n", "term", "Top biocViews terms") : null),
    [bvTop.data],
  );
  const rcrSpec = useMemo(
    () => (topRcr.data ? barSpec(topRcr.data, "sum_rcr", "package_name", "Top packages by RCR") : null),
    [topRcr.data],
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
  const downloadsLive = (im?.total_ips ?? 0) > 0;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">The Bioconductor ecosystem, by the numbers</h1>
        <p className="mt-1 text-sm text-slate-500">
          Computed live in your browser from the published marts.
        </p>
      </div>

      <Section title="Ecosystem">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <StatCard label="Packages" value={fmtInt(e.n_packages)} sub={`${e.n_repos} repositories`} />
          <StatCard label="Current release" value={e.current_release} sub="Bioconductor" />
          <StatCard label="Maintainers" value={fmtInt(e.n_maintainers)} sub="distinct" />
          <StatCard label="biocViews terms" value={fmtInt(bvCount.data?.[0]?.n)} sub="distinct" />
          <StatCard label="With source DOI" value={fmtInt(e.n_with_doi)} sub="describing paper" />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            {repoSpec && <VegaChart spec={repoSpec} className="w-full" />}
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            {bvSpec && <VegaChart spec={bvSpec} className="w-full" />}
          </div>
        </div>
      </Section>

      <Section title="Impact" note="linked so far — grows as enrichment fills in">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <StatCard label="Pkgs w/ publication" value={fmtInt(im?.n_pkgs_with_pub)} />
          <StatCard label="Linked works" value={fmtInt(im?.n_links)} />
          <StatCard label="Citing works" value={fmtInt(im?.n_citing)} />
          <StatCard label="Total RCR" value={fmtFloat(im?.total_rcr ?? null)} sub="field-normalized" />
          <StatCard label="NIH grants" value={fmtInt(g?.n_grants)} sub={`${g?.n_agencies ?? 0} agencies`} />
          <StatCard
            label="Distinct-IP downloads"
            value={downloadsLive ? fmtCompact(im?.total_ips) : "pending"}
            sub={downloadsLive ? "all-time" : "stats endpoint offline"}
            pending={!downloadsLive}
          />
        </div>
        <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
          {rcrSpec && <VegaChart spec={rcrSpec} className="w-full" />}
        </div>
      </Section>
    </div>
  );
}
