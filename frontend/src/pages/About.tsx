import type { ReactNode } from "react";
import type { Manifest } from "../db/duckdb";

const REPO_URL = "https://github.com/seandavi/bioc-intelligence";
const CORRECTION_URL = `${REPO_URL}/issues/new?template=link-correction.yml`;

const AUDIENCES: [string, string][] = [
  ["Grant writers", "find usage, citation and grant evidence for the Bioconductor software a project relies on or produced."],
  ["Package developers", "see how widely a package is used, which papers it is linked to, and fix a link that is wrong or missing."],
  ["People choosing a tool", "compare packages by real usage and by the papers behind them."],
  ["Bioconductor leadership", "follow the size, growth and funding footprint of the whole ecosystem."],
];

const SOURCES: [string, string][] = [
  ["bioconductor.org package index (VIEWS)", "The list of packages and releases, with each package's title, maintainer and topic tags (biocViews), across all four repositories: software, data experiment, data annotation and workflows."],
  ["bioconductor.org download statistics", "Monthly distinct-IP download counts per package."],
  ["Package CITATION files (github.com/bioconductor-source)", "The paper a package's authors ask users to cite. This is the most reliable source of package-to-paper links."],
  ["OpenAlex", "Paper titles, years and citation counts for the linked papers."],
  ["NIH iCite", "The Relative Citation Ratio (RCR) of each linked paper."],
  ["NIH RePORTER", "The NIH grants acknowledged by those papers."],
];

const LIMITATIONS: [string, ReactNode][] = [
  ["Download stats measure distinct IPs per month, summed.", "Bioconductor publishes monthly distinct-IP counts, so an IP active in several months counts once per month — treat totals as a usage proxy, not unique users. Only complete months load (the in-progress month and the source's zero-fill rows are dropped), and collection methodology changed in Oct 2015. The extractor logs-and-skips a 404 (the endpoints were down for a while after BioC 3.23)."],
  ["Linkage favors precision over recall.", "Package→manuscript links come from DESCRIPTION DOIs and CITATION files (author-asserted, authoritative), read from package source on the bioconductor-source GitHub org's devel branch (a few packages with another default branch fall back to the rendered release page). DOIs cited in the DESCRIPTION Description: field are kept as a separate, lower-confidence description_doi method — they sometimes cite dependencies rather than the package's own paper. Naive title-matching against OpenAlex is deliberately not used — many package names are common words (muscle, gage, tuberculosis), so it floods with false positives (empirically ~1,500 matches, mostly wrong). Consequently, some packages that do have a paper remain unlinked until they ship a DOI/CITATION; a precision-filtered title-candidate → LLM-judge path is on the roadmap."],
  ["Impact coverage is partial.", "RCR and citation counts exist only for linked works present in iCite / OpenAlex. Cited-by edges (fact_citation_edge) and full-text mention mining are built but run on demand (the references table is ~1.3B rows), so the “citing works” surfaces are not yet populated at scale."],
  ["Release-over-release growth is limited", "to the current release until per-package version history is backfilled from git.bioconductor.org tags."],
  ["The dashboard reflects a dated snapshot.", "Marts are committed Parquet (see the snapshot stamp in the header), not live data. A refresh re-runs the pipeline and re-bundles the marts."],
  ["Enrichment requires the private cdsci-lake", "(credentials via Google Secret Manager). The public dashboard ships only the derived marts — no credentials or raw lake access needed to view it."],
  ["Upstream accuracy applies.", "Figures are only as good as OpenAlex / iCite / RePORTER / Bioconductor; a few landmark papers carry very high RCRs, and metadata gaps propagate."],
];

const METHODS: [string, string, string][] = [
  ["doi", "1.0", "A DOI given in the package's own metadata that matches a paper in OpenAlex."],
  ["citation_file", "0.9", "A DOI from the package's CITATION file."],
  ["description_doi", "0.8", "A DOI mentioned in the package description. It sometimes points to related work or a dependency rather than the package's own paper."],
];

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="mt-8">
      <h2 className="mb-3 text-lg font-semibold text-slate-900">{title}</h2>
      <div className="space-y-3 text-sm leading-relaxed text-slate-700">{children}</div>
    </section>
  );
}

const Term = ({ id, children }: { id: string; children: ReactNode }) => (
  <div id={id}>
    <h3 className="font-semibold text-slate-900">{children}</h3>
  </div>
);

const A = ({ href, children }: { href: string; children: ReactNode }) => (
  <a className="text-bioc-600 hover:underline" href={href}>
    {children}
  </a>
);

const TH = "px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500";
const TD = "px-3 py-2 align-top";

export function About({ manifest }: { manifest: Manifest | null }) {
  const snapshot = manifest?.snapshot ?? "unknown";
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold text-slate-900">About and methods</h1>
      <p className="mt-1 text-sm text-slate-500">
        What this site shows, where the numbers come from, and how to cite or correct them.
      </p>

      <Section id="what" title="What this site is">
        <p>
          Bioconductor Intelligence brings together usage, publication, citation and grant
          information for Bioconductor packages, so the impact of the project can be shown with
          evidence rather than anecdote. It is built for:
        </p>
        <ul className="list-disc space-y-1 pl-5">
          {AUDIENCES.map(([who, what]) => (
            <li key={who}>
              <span className="font-medium">{who}</span> — {what}
            </li>
          ))}
        </ul>
      </Section>

      <Section id="sources" title="Data sources">
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className={TH}>Source</th>
                <th className={TH}>What we use it for</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {SOURCES.map(([name, role]) => (
                <tr key={name}>
                  <td className={`${TD} font-medium text-slate-900`}>{name}</td>
                  <td className={TD}>{role}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          The OpenAlex, iCite and RePORTER data are read from the cdsci-lake, a shared research data
          lake, in read-only mode. The data is refreshed monthly. This copy is the{" "}
          <span className="font-medium">{snapshot}</span> snapshot.
        </p>
      </Section>

      <Section id="definitions" title="Definitions">
        <Term id="distinct-ips">Distinct IPs</Term>
        <p>
          Bioconductor reports, for each package and month, how many different IP addresses
          downloaded it. We use that as our usage measure and add the months together. Someone
          active in several months is counted once per month, so it is a usage proxy rather than a
          count of unique people. How downloads are counted changed in October 2015, so numbers
          before and after that date are not directly comparable. The headline figure is therefore
          the trailing 12 months, which sits entirely within the current method.
        </p>
        <Term id="rcr">Relative Citation Ratio (RCR)</Term>
        <p>
          NIH iCite's measure of a paper's citation influence relative to papers in its field. 1.0
          is the NIH average; 2.0 is twice that. When a package has several papers we show the
          median RCR and never add them up.
        </p>
        <Term id="linked-papers">Papers the package asks users to cite</Term>
        <p>
          A package is linked to a paper when the package's authors name it, mainly in the CITATION
          file. Each link records how it was found and how far to trust it:
        </p>
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className={TH}>Match method</th>
                <th className={TH}>Confidence</th>
                <th className={TH}>Meaning</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {METHODS.map(([m, c, d]) => (
                <tr key={m}>
                  <td className={`${TD} font-mono text-xs`}>{m}</td>
                  <td className={TD}>{c}</td>
                  <td className={TD}>{d}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Term id="grant-attribution">Grant attribution</Term>
        <p>
          Grants are listed as the awards acknowledged by the paper a package asks users to cite.
          This is not a claim that the grant funded the package, nor that research using the
          package was funded by it.
        </p>
        <Term id="agency-ic">Agency and NIH Institute/Center</Term>
        <p>
          The agency is the organisation that made the award, for example NIH. Within NIH, the
          Institute or Center (IC) is the part that administers it, shown as a two-letter code such
          as CA for the National Cancer Institute.
        </p>
      </Section>

      <Section id="limitations" title="Known limitations">
        <ul className="list-disc space-y-2 pl-5">
          {LIMITATIONS.map(([lead, rest]) => (
            <li key={lead}>
              <span className="font-medium">{lead}</span> {rest}
            </li>
          ))}
        </ul>
      </Section>

      <Section id="cite" title="How to cite">
        <p className="rounded-lg border border-slate-200 bg-white p-4">
          Davis S. Bioconductor Intelligence: usage, publication and grant impact of Bioconductor
          packages. Snapshot {snapshot}. <A href="https://seandavi.github.io/bioc-intelligence/">https://seandavi.github.io/bioc-intelligence/</A>
        </p>
        <p>
          The code and data are released under the MIT license (see{" "}
          <A href={`${REPO_URL}/blob/main/LICENSE`}>LICENSE</A>). Please also credit the upstream
          sources above.
        </p>
      </Section>

      <Section id="corrections" title="Corrections">
        <p>
          If a package is linked to the wrong paper, or is missing a link, please{" "}
          <A href={CORRECTION_URL}>open a correction request</A>. Verified corrections are kept as
          manual links that override the automatic ones.
        </p>
      </Section>
    </div>
  );
}
