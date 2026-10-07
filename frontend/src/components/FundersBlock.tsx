import { useQuery } from "../db/useQuery";
import { Link } from "../lib/router";

interface PackageFunder {
  funder_name: string;
  declared_name: string | null;
  grant_number: string | null;
  grant_id: string | null;
}

// Funders a package declares in Authors@R (role fnd); grant_id is set when the number matched an NIH grant.
export function FundersBlock({ name, repo }: { name: string; repo: string }) {
  const esc = (s: string) => s.replace(/'/g, "''");
  const { data, loading, error } = useQuery<PackageFunder>(`
    SELECT funder_name, declared_name, grant_number, grant_id
    FROM 'mart_package_funder.parquet'
    WHERE package_name = '${esc(name)}' AND repo = '${esc(repo)}'
    ORDER BY funder_name, grant_number`);

  if (error) return <p className="text-sm text-red-700">Failed to load funders: {error.message}</p>;
  if (loading) return <p className="text-sm text-neutral-300">Loading funders…</p>;
  if (!data?.length) return <p className="text-sm text-neutral-300">No funders declared.</p>;
  return (
    <ul className="space-y-1 text-sm">
      {data.map((f, i) => (
        <li key={i} className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium text-neutral-500">{f.funder_name}</span>
          {f.declared_name && f.declared_name !== f.funder_name && (
            <span className="text-xs text-neutral-300">declared as “{f.declared_name}”</span>
          )}
          {f.grant_id ? (
            <Link
              view="grants"
              params={{ q: f.grant_id }}
              className="text-xs text-primary-400 hover:underline"
            >
              {f.grant_number ?? f.grant_id}
            </Link>
          ) : (
            f.grant_number && <span className="text-xs text-neutral-300">{f.grant_number}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
