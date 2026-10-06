// Confidence-aware paper aggregates from mart_package_work rows (one row per package × work ×
// match_method). The impact mart sums over every link; these exclude `description_doi` by default
// because that link only says the DESCRIPTION text mentions a paper (it may be a dependency).

export interface WorkLink {
  package_name: string;
  repo: string;
  work_id: string;
  title: string | null;
  citation_count: number | null;
  icite_rcr: number | null;
  match_method: string;
}

export interface LinkedWork {
  work_id: string;
  title: string | null;
  citation_count: number;
  icite_rcr: number | null;
  methods: string[];
  others: string[]; // other packages linked to this work under the same filter
}

export interface PackageAgg {
  n_pubs: number;
  total_citations: number;
  median_rcr: number | null;
  works: LinkedWork[];
  shared: boolean; // any of this package's works is also linked to another package
}

export const LOW_CONFIDENCE_METHODS = ["description_doi"];
// SQL fragment for queries that apply the same default filter.
export const HIGH_CONFIDENCE_SQL = "match_method IN ('doi', 'citation_file')";

export const pkgKey = (repo: string, name: string) => `${repo}/${name}`;

const median = (xs: number[]): number | null => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

// Keyed by pkgKey(repo, package_name); packages with no remaining link are absent.
export function aggregateByPackage(
  rows: WorkLink[],
  includeLowConfidence: boolean,
): { byPackage: Map<string, PackageAgg>; sharedWorkIds: Set<string> } {
  const kept = includeLowConfidence
    ? rows
    : rows.filter((r) => !LOW_CONFIDENCE_METHODS.includes(r.match_method));

  // package -> work -> link; the same work reached by two methods counts once.
  const perPkg = new Map<string, Map<string, LinkedWork>>();
  const pkgsOfWork = new Map<string, Set<string>>();
  for (const r of kept) {
    const key = pkgKey(r.repo, r.package_name);
    const works = perPkg.get(key) ?? new Map<string, LinkedWork>();
    perPkg.set(key, works);
    const w = works.get(r.work_id);
    if (w) w.methods.push(r.match_method);
    else
      works.set(r.work_id, {
        work_id: r.work_id,
        title: r.title,
        citation_count: Number(r.citation_count ?? 0),
        icite_rcr: r.icite_rcr,
        methods: [r.match_method],
        others: [],
      });
    const pkgs = pkgsOfWork.get(r.work_id) ?? new Set<string>();
    pkgsOfWork.set(r.work_id, pkgs.add(r.package_name));
  }

  const sharedWorkIds = new Set([...pkgsOfWork].filter(([, p]) => p.size > 1).map(([id]) => id));
  const byPackage = new Map<string, PackageAgg>();
  for (const [key, map] of perPkg) {
    const name = key.slice(key.indexOf("/") + 1);
    const works = [...map.values()];
    for (const w of works)
      w.others = [...(pkgsOfWork.get(w.work_id) ?? [])].filter((p) => p !== name).sort();
    byPackage.set(key, {
      n_pubs: works.length,
      total_citations: works.reduce((s, w) => s + w.citation_count, 0),
      median_rcr: median(works.flatMap((w) => (w.icite_rcr == null ? [] : [w.icite_rcr]))),
      works,
      shared: works.some((w) => sharedWorkIds.has(w.work_id)),
    });
  }
  return { byPackage, sharedWorkIds };
}
