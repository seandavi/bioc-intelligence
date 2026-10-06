import { useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchManifest } from "../db/duckdb";
import { useQuery } from "../db/useQuery";
import { FundersBlock } from "../components/FundersBlock";
import { InfoDot } from "../components/InfoDot";
import { PeopleBlock } from "../components/PeopleBlock";
import { monthlyIpsSpec, type MonthlyRow } from "../components/Sparkline";
import { StatCard } from "../components/StatCard";
import { BiocViewChip, Chip, REPO_LABEL, RepoBadge } from "../components/ui";
import { VegaChart } from "../components/VegaChart";
import { LOW_CONFIDENCE_METHODS } from "../lib/confidence";
import { fmtFloat, fmtInt } from "../lib/format";
import { nihIcName } from "../lib/nih";
import { Link } from "../lib/router";

// mart_package_directory. Fields after source_doi arrive with #39; older bundles lack them.
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
  n_reverse_deps?: number | null;
  n_deps?: number | null;
  git_last_commit_date?: string | number | Date | null;
  package_status?: string | null;
  has_news?: boolean | null;
  n_vignettes?: number | null;
  license?: string | null;
  bioc_url?: string | null;
}

interface Impact {
  total_distinct_ips: number | null;
  distinct_ips_trailing_12mo: number | null;
  distinct_ips_prior_12mo: number | null;
  usage_rank_in_repo: number | null;
  n_in_repo: number;
}

interface Paper {
  work_id: string;
  doi: string | null;
  pmid: string | null;
  title: string | null;
  year: number | null;
  journal: string | null;
  citation_count: number | null;
  icite_rcr: number | null;
  match_method: string;
  confidence: number;
}

interface Grant {
  grant_id: string;
  agency: string | null;
  ic_name?: string | null;
  title: string | null;
}

interface Dep {
  package_name: string;
  dep: string;
  kind: string;
  in_bioc: boolean;
}

const sqlStr = (s: string) => `'${s.replaceAll("'", "''")}'`;
const splitList = (s: string | null) => (s ? s.split("|").filter(Boolean) : []);

const fmtDate = (v: Pkg["git_last_commit_date"]) => {
  if (v == null) return null;
  const d = new Date(v);
  return isNaN(d.getTime()) ? String(v) : d.toISOString().slice(0, 10);
};

const METHOD_LABEL: Record<string, string> = {
  doi: "DESCRIPTION DOI",
  citation_file: "CITATION",
  description_doi: "Description text",
  title_search: "title search",
  manual: "manual",
};

const KIND_ORDER = ["depends", "imports", "linking_to", "suggests"];
const KIND_LABEL: Record<string, string> = {
  depends: "Depends",
  imports: "Imports",
  linking_to: "LinkingTo",
  suggests: "Suggests",
};

function Section({ title, info, children }: { title: string; info?: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
        {info && <InfoDot tip={info} />}
      </h2>
      {children}
    </section>
  );
}

function CopyButton({ text, label = "Copy" }: { text: () => string; label?: string }) {
  const [status, setStatus] = useState<string | null>(null);
  return (
    <button
      type="button"
      onClick={() =>
        navigator.clipboard.writeText(text()).then(
          () => setStatus("Copied"),
          () => setStatus("Copy failed"),
        )
      }
      className="shrink-0 rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100"
    >
      {status ?? label}
    </button>
  );
}

const Muted = ({ children }: { children: ReactNode }) => (
  <p className="text-sm text-slate-500">{children}</p>
);

function QueryError({ what, error }: { what: string; error: Error }) {
  return (
    <p className="text-sm text-red-700">
      Failed to load {what}: {error.message}
    </p>
  );
}

function DepList({ deps, field }: { deps: Dep[]; field: "dep" | "package_name" }) {
  const kinds = KIND_ORDER.filter((k) => deps.some((d) => d.kind === k));
  return (
    <dl className="space-y-2 text-sm">
      {kinds.map((k) => (
        <div key={k}>
          <dt className="text-xs text-slate-500">{KIND_LABEL[k] ?? k}</dt>
          <dd className="flex flex-wrap gap-x-2 gap-y-0.5">
            {deps
              .filter((d) => d.kind === k)
              .map((d) =>
                d.in_bioc ? (
                  <Link
                    key={d[field]}
                    view="package"
                    arg={d[field]}
                    className="text-bioc-600 hover:underline"
                  >
                    {d[field]}
                  </Link>
                ) : (
                  <span key={d[field]} className="text-slate-600" title="Not a Bioconductor package">
                    {d[field]}
                  </span>
                ),
              )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Profile({ pkg }: { pkg: Pkg }) {
  const name = sqlStr(pkg.package_name);
  const repo = sqlStr(pkg.repo);
  const [snapshot, setSnapshot] = useState("unknown");
  useEffect(() => {
    fetchManifest()
      .then((m) => setSnapshot(m.snapshot))
      .catch(() => {});
  }, []);

  const impact = useQuery<Impact>(`
    SELECT total_distinct_ips, distinct_ips_trailing_12mo, distinct_ips_prior_12mo,
           usage_rank_in_repo,
           (SELECT count(*) FROM 'mart_package_impact.parquet' WHERE repo = ${repo}) AS n_in_repo
    FROM 'mart_package_impact.parquet' WHERE package_name = ${name} AND repo = ${repo}`);
  const monthly = useQuery<MonthlyRow>(`
    SELECT year, month, distinct_ips, methodology_era
    FROM 'mart_package_downloads_monthly.parquet'
    WHERE package_name = ${name} AND repo = ${repo} ORDER BY year, month`);
  const papers = useQuery<Paper>(`
    SELECT work_id, doi, pmid, title, year, journal, citation_count, icite_rcr,
           match_method, confidence
    FROM 'mart_package_work.parquet' WHERE package_name = ${name} AND repo = ${repo}
    ORDER BY confidence DESC, year DESC NULLS LAST, work_id`);
  const grants = useQuery<Grant>(`
    SELECT * EXCLUDE (package_names) FROM 'mart_grant_attribution.parquet'
    WHERE list_contains(package_names, ${name}) ORDER BY grant_id`);
  // Dependency edges both ways; in_bioc marks names that have a profile to link to.
  const deps = useQuery<Dep>(`
    SELECT d.package_name, d.dep, d.kind,
           (SELECT count(*) FROM 'mart_package_directory.parquet' p
             WHERE p.package_name = CASE WHEN d.package_name = ${name}
                                         THEN d.dep ELSE d.package_name END) > 0 AS in_bioc
    FROM 'mart_package_dependency.parquet' d
    WHERE (d.package_name = ${name} AND d.repo = ${repo}) OR d.dep = ${name}
    ORDER BY d.kind, d.dep, d.package_name`);

  const imp = impact.data?.[0];
  const t12 = imp?.distinct_ips_trailing_12mo ?? 0;
  const p12 = imp?.distinct_ips_prior_12mo ?? 0;
  const change = p12 > 0 ? (t12 - p12) / p12 : null;
  const series = monthly.data;
  const chartSpec = useMemo(
    () => ({
      ...monthlyIpsSpec(series ?? [], { height: 120, axes: true }),
      title: `${pkg.package_name}: distinct IPs per month`,
    }),
    [series, pkg.package_name],
  );

  const highPapers = (papers.data ?? []).filter(
    (p) => !LOW_CONFIDENCE_METHODS.includes(p.match_method),
  );
  const forward = (deps.data ?? []).filter((d) => d.package_name === pkg.package_name);
  const reverse = (deps.data ?? []).filter((d) => d.dep === pkg.package_name);
  const views = splitList(pkg.biocviews);
  const bioc = pkg.bioc_url ?? `https://bioconductor.org/packages/${pkg.package_name}/`;
  const install = `BiocManager::install("${pkg.package_name}")`;
  const lastCommit = fmtDate(pkg.git_last_commit_date);

  const summary = () => {
    const nCit = highPapers.reduce((s, p) => s + (p.citation_count ?? 0), 0);
    const rank =
      t12 > 0 && imp?.usage_rank_in_repo
        ? `, rank ${fmtInt(imp.usage_rank_in_repo)} of ${fmtInt(imp.n_in_repo)} in its repository`
        : "";
    const paperPart = highPapers.length
      ? ` Its ${highPapers.length} linked paper${highPapers.length === 1 ? "" : "s"} ` +
        `ha${highPapers.length === 1 ? "s" : "ve"} ${fmtInt(nCit)} citations.`
      : "";
    return (
      `${pkg.package_name}${pkg.title ? ` (${pkg.title})` : ""}, a Bioconductor ` +
      `${(REPO_LABEL[pkg.repo] ?? pkg.repo).toLowerCase()} package, was downloaded from ` +
      `${fmtInt(t12)} distinct IP addresses in the trailing 12 months ` +
      `(summed monthly; ${fmtInt(imp?.total_distinct_ips ?? 0)} all-time${rank}).` +
      `${paperPart} Source: Bioconductor Intelligence, data snapshot ${snapshot}.`
    );
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <header className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold text-slate-900">{pkg.package_name}</h1>
          <RepoBadge repo={pkg.repo} />
          <span className="text-xs text-slate-500">release {pkg.latest_release}</span>
          {pkg.package_status === "Deprecated" && (
            <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-700">
              Deprecated
            </span>
          )}
        </div>
        {pkg.title && <p className="mt-1 text-slate-700">{pkg.title}</p>}
        {pkg.description && (
          <p className="mt-2 text-sm text-slate-600">{pkg.description}</p>
        )}
        <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          {pkg.maintainer && (
            <div>
              <dt className="inline text-slate-500">Maintainer: </dt>
              <dd className="inline text-slate-700">{pkg.maintainer}</dd>
            </div>
          )}
          {lastCommit && (
            <div>
              <dt className="inline text-slate-500">Last commit: </dt>
              <dd className="inline text-slate-700">{lastCommit}</dd>
            </div>
          )}
          {pkg.license && (
            <div>
              <dt className="inline text-slate-500">License: </dt>
              <dd className="inline text-slate-700">{pkg.license}</dd>
            </div>
          )}
          {(pkg.n_vignettes != null || pkg.has_news != null) && (
            <div className="flex gap-1">
              {pkg.n_vignettes != null && (
                <Chip>
                  {pkg.n_vignettes} vignette{pkg.n_vignettes === 1 ? "" : "s"}
                </Chip>
              )}
              {pkg.has_news != null && <Chip>{pkg.has_news ? "NEWS" : "no NEWS"}</Chip>}
            </div>
          )}
        </dl>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <code className="rounded bg-slate-100 px-2 py-1 font-mono text-sm text-slate-800">
            {install}
          </code>
          <CopyButton text={() => install} />
          <a
            className="text-sm text-bioc-600 hover:underline"
            href={bioc}
            target="_blank"
            rel="noreferrer"
          >
            bioconductor.org page ↗
          </a>
          {pkg.bug_reports && (
            <a
              className="text-sm text-bioc-600 hover:underline"
              href={pkg.bug_reports}
              target="_blank"
              rel="noreferrer"
            >
              Bug reports ↗
            </a>
          )}
        </div>
      </header>

      {/* Usage */}
      <Section
        title="Usage"
        info="Distinct IP addresses downloading the package, summed over months. Counts before Oct 2015 used an older methodology (shaded) and are not comparable."
      >
        {impact.error ? (
          <QueryError what="usage" error={impact.error} />
        ) : impact.loading ? (
          <Muted>Loading usage…</Muted>
        ) : (
          <div className="grid gap-3 sm:grid-cols-4">
            <StatCard label="Distinct IPs, 12 mo" value={fmtInt(t12)} />
            <StatCard
              label="vs prior 12 mo"
              value={change == null ? "—" : `${change >= 0 ? "+" : ""}${(change * 100).toFixed(0)}%`}
              sub={`${fmtInt(p12)} the year before`}
            />
            <StatCard
              label="Rank in repo"
              value={t12 > 0 && imp?.usage_rank_in_repo ? fmtInt(imp.usage_rank_in_repo) : "—"}
              sub={
                t12 > 0 && imp
                  ? `of ${fmtInt(imp.n_in_repo)} ${REPO_LABEL[pkg.repo] ?? pkg.repo} packages`
                  : "no downloads in the last 12 months"
              }
            />
            <StatCard
              label="All-time"
              value={fmtInt(imp?.total_distinct_ips ?? 0)}
              sub="summed across methodology eras"
            />
          </div>
        )}
        <div className="mt-4">
          {monthly.error ? (
            <QueryError what="monthly downloads" error={monthly.error} />
          ) : monthly.loading ? (
            <Muted>Loading monthly downloads…</Muted>
          ) : series?.length ? (
            <VegaChart spec={chartSpec} subtitle={`snapshot ${snapshot}`} className="w-full" />
          ) : (
            <Muted>No monthly download records.</Muted>
          )}
        </div>
      </Section>

      {/* Papers */}
      <Section
        title="Papers"
        info="Papers the package asks users to cite, from its CITATION file and DESCRIPTION. Links found only in the Description text are greyed: they may cite a dependency or related work."
      >
        {papers.error ? (
          <QueryError what="papers" error={papers.error} />
        ) : papers.loading ? (
          <Muted>Loading papers…</Muted>
        ) : !papers.data?.length ? (
          <Muted>
            No papers linked yet. Maintainers: add the paper's DOI to the package's{" "}
            <code className="font-mono">inst/CITATION</code> file so it is picked up at the next
            refresh.
          </Muted>
        ) : (
          <ul className="space-y-3">
            {papers.data.map((w) => {
              const low = LOW_CONFIDENCE_METHODS.includes(w.match_method);
              const href = w.doi
                ? `https://doi.org/${w.doi}`
                : w.pmid
                  ? `https://pubmed.ncbi.nlm.nih.gov/${w.pmid}/`
                  : null;
              return (
                <li key={w.work_id} className={low ? "opacity-60" : ""}>
                  {href ? (
                    <a
                      className="text-bioc-600 hover:underline"
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {w.title ?? w.doi ?? w.work_id}
                    </a>
                  ) : (
                    <span className="text-slate-800">{w.title ?? w.work_id}</span>
                  )}
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                    <span
                      className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600"
                      title={`match_method ${w.match_method}, confidence ${w.confidence}`}
                    >
                      {METHOD_LABEL[w.match_method] ?? w.match_method}
                    </span>
                    {[w.year, w.journal].filter(Boolean).join(" · ")}
                    <span>
                      {fmtInt(w.citation_count)} citations · RCR {fmtFloat(w.icite_rcr, 2)}
                    </span>
                  </div>
                  {low && (
                    <div className="mt-0.5 text-xs italic text-slate-500">
                      Low confidence: found only as a DOI in the Description text, which sometimes
                      cites a dependency or related work. Excluded from the summary below.
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      {/* Funding */}
      <Section
        title="Funding"
        info="NIH grants acknowledged by the papers this package asks users to cite (via RePORTER), and funders declared in Authors@R."
      >
        <h3 className="mb-1 text-xs font-medium text-slate-500">NIH grants via linked papers</h3>
        {grants.error ? (
          <QueryError what="grants" error={grants.error} />
        ) : grants.loading ? (
          <Muted>Loading grants…</Muted>
        ) : !grants.data?.length ? (
          <Muted>No NIH grants linked yet.</Muted>
        ) : (
          <ul className="space-y-1 text-sm">
            {grants.data.map((g) => (
              <li key={g.grant_id} className="flex flex-wrap items-baseline gap-x-2">
                <a
                  href={`https://reporter.nih.gov/project-details/${g.grant_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-bioc-600 hover:underline"
                >
                  {g.grant_id}
                </a>
                {g.title && <span className="text-slate-700">{g.title}</span>}
                {g.agency && (
                  <span className="text-xs text-slate-500">
                    {g.ic_name ?? nihIcName(g.agency)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        <h3 className="mb-1 mt-4 text-xs font-medium text-slate-500">Declared funders</h3>
        <FundersBlock name={pkg.package_name} repo={pkg.repo} />
      </Section>

      {/* Ecosystem */}
      <Section title="Ecosystem">
        <div className="grid gap-5 md:grid-cols-2">
          <div>
            <h3 className="mb-1 text-xs font-medium text-slate-500">
              Used by
              {pkg.n_reverse_deps != null && ` · ${fmtInt(pkg.n_reverse_deps)} packages`}
              <InfoDot tip="Packages that depend on, import or link to this one (reverse dependencies, from VIEWS). The list adds packages that only suggest it." />
            </h3>
            {deps.error ? (
              <Muted>Dependency data is not published yet.</Muted>
            ) : deps.loading ? (
              <Muted>Loading…</Muted>
            ) : reverse.length ? (
              <DepList deps={reverse} field="package_name" />
            ) : (
              <Muted>No Bioconductor package depends on this one.</Muted>
            )}
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium text-slate-500">
              Depends on
              {pkg.n_deps != null && ` · ${fmtInt(pkg.n_deps)} packages`}
            </h3>
            {deps.error ? (
              <Muted>Dependency data is not published yet.</Muted>
            ) : deps.loading ? (
              <Muted>Loading…</Muted>
            ) : forward.length ? (
              <DepList deps={forward} field="dep" />
            ) : (
              <Muted>No declared dependencies besides R.</Muted>
            )}
          </div>
        </div>
        {views.length > 0 && (
          <>
            <h3 className="mb-1 mt-4 text-xs font-medium text-slate-500">biocViews</h3>
            <div className="flex flex-wrap gap-1">
              {views.map((v) => (
                <BiocViewChip key={v} term={v} />
              ))}
            </div>
          </>
        )}
      </Section>

      {/* People */}
      <Section title="People">
        <PeopleBlock name={pkg.package_name} repo={pkg.repo} />
      </Section>

      {/* Cite this */}
      <Section title="Cite this">
        <p className="text-sm text-slate-700">{summary()}</p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <CopyButton text={summary} label="Copy summary" />
          <span className="text-xs text-slate-500">
            The usage chart's “…” menu exports it as PNG or SVG.
          </span>
        </div>
      </Section>
    </div>
  );
}

// #/package/<name>: one package across every mart.
export function PackagePage({ name }: { name: string }) {
  const { data, loading, error } = useQuery<Pkg>(`
    SELECT * REPLACE (array_to_string(biocviews, '|') AS biocviews,
                      array_to_string(url, '|') AS url)
    FROM 'mart_package_directory.parquet'
    WHERE package_name = ${sqlStr(name)}
    ORDER BY repo <> 'bioc', repo LIMIT 1`);
  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Failed to load package: {error.message}
      </div>
    );
  }
  if (loading) return <Muted>Loading {name}…</Muted>;
  if (!data?.length) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <h1 className="text-lg font-semibold text-slate-900">No package named “{name}”</h1>
        <p className="mt-1 text-sm text-slate-600">
          It is not in the current Bioconductor release.{" "}
          <Link view="explorer" params={{ q: name }} className="text-bioc-600 underline">
            Search the Explorer
          </Link>
        </p>
      </div>
    );
  }
  return <Profile key={`${data[0].repo}/${data[0].package_name}`} pkg={data[0]} />;
}
