import { useEffect, useState } from "react";
import { fetchManifest } from "../db/duckdb";
import { downloadCsv } from "../lib/csv";
import { fmtFloat, fmtInt } from "../lib/format";
import { nihIcName } from "../lib/nih";
import { Link } from "../lib/router";

export interface PackageImpact {
  package_name: string;
  distinct_ips_trailing_12mo: number;
  total_distinct_ips: number;
  n_primary_pubs: number;
  total_citations: number;
  median_rcr: number | null;
}

export interface PackageWork {
  package_name: string;
  work_id: string;
  citation_count: number | null;
  icite_rcr: number | null;
  match_method: string;
}

function median(xs: number[]): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// A package linked only through a `<doi:…>` in its DESCRIPTION may be citing related work,
// not its own paper (confidence 0.8), so the report drops it unless asked.
export const isDescriptionDoiOnly = (works: PackageWork[] | undefined) =>
  !!works?.length && works.every((w) => w.match_method === "description_doi");

// Per-grant mini-report: the grant's packages with usage and paper metrics, plus a
// copyable summary and CSV for a progress report or renewal narrative.
export function GrantReport({
  grant,
  impact,
  worksByPackage,
  includeLowConfidence,
}: {
  grant: { grant_id: string; agency: string | null; title: string | null; packages: string[] };
  impact: Map<string, PackageImpact>;
  worksByPackage: Map<string, PackageWork[]>;
  includeLowConfidence: boolean;
}) {
  const [snapshot, setSnapshot] = useState("unknown");
  const [copied, setCopied] = useState<string | null>(null);
  useEffect(() => {
    fetchManifest()
      .then((m) => setSnapshot(m.snapshot))
      .catch(() => {});
  }, []);

  const included = grant.packages.filter(
    (p) => includeLowConfidence || !isDescriptionDoiOnly(worksByPackage.get(p)),
  );
  const excluded = grant.packages.filter((p) => !included.includes(p));
  const rows = included
    .map((p) => ({ package_name: p, i: impact.get(p) }))
    .sort((a, b) => (b.i?.distinct_ips_trailing_12mo ?? 0) - (a.i?.distinct_ips_trailing_12mo ?? 0));

  // Papers shared by several packages (e.g. scater/scuttle) count once in the footer.
  const works = new Map<string, PackageWork>();
  for (const p of included) for (const w of worksByPackage.get(p) ?? []) works.set(w.work_id, w);
  const total = {
    ips12: rows.reduce((s, r) => s + (r.i?.distinct_ips_trailing_12mo ?? 0), 0),
    ipsAll: rows.reduce((s, r) => s + (r.i?.total_distinct_ips ?? 0), 0),
    papers: works.size,
    citations: [...works.values()].reduce((s, w) => s + (w.citation_count ?? 0), 0),
    rcr: median([...works.values()].flatMap((w) => (w.icite_rcr == null ? [] : [w.icite_rcr]))),
  };

  const summary = () => {
    const head = [grant.title && `"${grant.title}"`, grant.agency && nihIcName(grant.agency)]
      .filter(Boolean)
      .join(", ");
    const n = included.length;
    return (
      `${grant.grant_id}${head ? ` (${head})` : ""} is acknowledged by the papers that ${n} ` +
      `Bioconductor package${n === 1 ? "" : "s"} ask users to cite: ${included.join(", ")}. ` +
      `In the trailing 12 months these packages were downloaded from ${fmtInt(total.ips12)} distinct IP ` +
      `addresses (${fmtInt(total.ipsAll)} all-time; summed per package). Their ${fmtInt(total.papers)} ` +
      `distinct papers have ${fmtInt(total.citations)} citations (median iCite RCR ${fmtFloat(total.rcr, 2)}).` +
      (excluded.length
        ? ` Excludes ${excluded.length} package${excluded.length === 1 ? "" : "s"} linked only through a DOI in the DESCRIPTION.`
        : "") +
      ` Source: Bioconductor Intelligence, data snapshot ${snapshot}.`
    );
  };

  const copy = () =>
    navigator.clipboard.writeText(summary()).then(
      () => setCopied("Copied"),
      () => setCopied("Copy failed"),
    );

  const csv = () =>
    downloadCsv(
      `bioc-grant-${grant.grant_id}.csv`,
      rows.map(({ package_name, i }) => ({
        grant_id: grant.grant_id,
        package_name,
        distinct_ips_trailing_12mo: i?.distinct_ips_trailing_12mo,
        total_distinct_ips: i?.total_distinct_ips,
        n_papers: i?.n_primary_pubs,
        total_citations: i?.total_citations,
        median_rcr: i?.median_rcr,
        snapshot,
      })),
    );

  const num = "px-2 py-1 text-right tabular-nums";
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <table className="w-full text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-2 py-1 text-left">Package</th>
            <th className="px-2 py-1 text-right">IPs, 12 mo</th>
            <th className="px-2 py-1 text-right">IPs, all-time</th>
            <th className="px-2 py-1 text-right">Papers</th>
            <th className="px-2 py-1 text-right">Citations</th>
            <th className="px-2 py-1 text-right">Median RCR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ package_name, i }) => (
            <tr key={package_name} className="border-t border-slate-200">
              <td className="px-2 py-1">
                <Link view="package" arg={package_name} className="text-bioc-600 hover:underline">
                  {package_name}
                </Link>
              </td>
              <td className={num}>{fmtInt(i?.distinct_ips_trailing_12mo)}</td>
              <td className={num}>{fmtInt(i?.total_distinct_ips)}</td>
              <td className={num}>{fmtInt(i?.n_primary_pubs)}</td>
              <td className={num}>{fmtInt(i?.total_citations)}</td>
              <td className={num}>{fmtFloat(i?.median_rcr, 2)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot className="font-medium text-slate-700">
          <tr className="border-t-2 border-slate-300">
            <td className="px-2 py-1">
              {included.length} package{included.length === 1 ? "" : "s"}
            </td>
            <td className={num}>{fmtInt(total.ips12)}</td>
            <td className={num}>{fmtInt(total.ipsAll)}</td>
            <td className={num}>{fmtInt(total.papers)}</td>
            <td className={num}>{fmtInt(total.citations)}</td>
            <td className={num}>{fmtFloat(total.rcr, 2)}</td>
          </tr>
        </tfoot>
      </table>
      <p className="mt-2 text-xs text-slate-500">
        Packages whose cite-me paper acknowledges this award in NIH RePORTER publication links; this
        does not mean the funded research used the package. IP totals sum each package's distinct IPs
        (an address that downloads two packages counts twice); the paper, citation and median-RCR
        totals count each paper once.
        {excluded.length > 0 && ` Excluded (linked only through a DESCRIPTION DOI): ${excluded.join(", ")}.`}
      </p>
      <div className="mt-2 flex items-center gap-2">
        <button
          onClick={copy}
          className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
        >
          Copy summary
        </button>
        <button
          onClick={csv}
          className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
        >
          Download CSV
        </button>
        {copied && <span className="text-xs text-slate-500">{copied}</span>}
      </div>
    </div>
  );
}
