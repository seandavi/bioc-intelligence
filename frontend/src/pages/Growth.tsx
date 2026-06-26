import { useMemo } from "react";
import { useQuery } from "../db/useQuery";
import { VegaChart } from "../components/VegaChart";
import { horizontalBar } from "../components/charts";
import { StatCard } from "../components/StatCard";
import { fmtInt } from "../lib/format";

interface Release {
  bioc_release: string;
  n_packages: number;
  n_new_packages: number;
}

const RELEASES = `
  SELECT bioc_release, n_packages, n_new_packages
  FROM 'mart_release_growth.parquet' ORDER BY bioc_release`;

const BY_REPO = `
  SELECT repo, count(*)::INT AS n FROM 'mart_package_directory.parquet' GROUP BY repo ORDER BY n DESC`;

export function Growth() {
  const releases = useQuery<Release>(RELEASES);
  const byRepo = useQuery<Record<string, unknown>>(BY_REPO);

  const repoSpec = useMemo(
    () => (byRepo.data ? horizontalBar(byRepo.data, "n", "repo", "Packages per repository") : null),
    [byRepo.data],
  );

  if (releases.error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Failed to load growth data: {releases.error.message}
      </div>
    );
  }

  const rows = releases.data ?? [];
  const latest = rows[rows.length - 1];
  const singleRelease = rows.length <= 1;

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-slate-900">Ecosystem growth</h1>
        <p className="mt-1 text-sm text-slate-500">Bioconductor as an object of study (metaresearch).</p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Current release" value={latest?.bioc_release ?? "—"} sub="Bioconductor" />
        <StatCard label="Packages" value={fmtInt(latest?.n_packages)} sub="this release" />
        <StatCard label="Releases tracked" value={fmtInt(rows.length)} sub="snapshots" />
      </div>

      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
        {repoSpec && <VegaChart spec={repoSpec} className="w-full" />}
      </div>

      {singleRelease && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <span className="font-medium">Release-over-release history is pending.</span> Net growth,
          new-package counts, and net downloads per release light up once per-package version history
          is backfilled from <code className="rounded bg-amber-100 px-1">git.bioconductor.org</code>{" "}
          tags. Today only the current release ({latest?.bioc_release}) is snapshotted.
        </div>
      )}
    </div>
  );
}
