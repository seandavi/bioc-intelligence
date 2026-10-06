import { useQuery } from "../db/useQuery";

interface PackagePerson {
  name: string;
  orcid: string | null;
  roles: string; // ','-joined MARC codes
  is_maintainer: boolean;
}

// MARC relator codes seen in Authors@R.
const ROLE_LABEL: Record<string, string> = {
  aut: "author",
  cre: "maintainer",
  ctb: "contributor",
  fnd: "funder",
  cph: "copyright holder",
  ths: "thesis advisor",
  rev: "reviewer",
};

export const roleLabel = (code: string) => ROLE_LABEL[code] ?? code;

export function OrcidLink({ orcid }: { orcid: string }) {
  return (
    <a
      href={`https://orcid.org/${orcid}`}
      target="_blank"
      rel="noreferrer"
      title={`ORCID ${orcid}`}
      className="text-xs text-bioc-600 hover:underline"
    >
      ORCID
    </a>
  );
}

// People credited on one package, maintainer first.
export function PeopleBlock({ name, repo }: { name: string; repo: string }) {
  const esc = (s: string) => s.replace(/'/g, "''");
  const { data, loading, error } = useQuery<PackagePerson>(`
    SELECT name, orcid, array_to_string(roles, ',') AS roles, is_maintainer
    FROM 'mart_package_person.parquet'
    WHERE package_name = '${esc(name)}' AND repo = '${esc(repo)}'
    ORDER BY is_maintainer DESC, name`);

  if (error) return <p className="text-sm text-red-700">Failed to load people: {error.message}</p>;
  if (loading) return <p className="text-sm text-slate-400">Loading people…</p>;
  if (!data?.length) return <p className="text-sm text-slate-500">No people listed in Authors@R.</p>;
  return (
    <ul className="space-y-1 text-sm">
      {data.map((p) => (
        <li key={`${p.name}|${p.orcid ?? ""}`} className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium text-slate-800">{p.name}</span>
          {p.orcid && <OrcidLink orcid={p.orcid} />}
          <span className="text-xs text-slate-500">
            {p.roles
              .split(",")
              .filter(Boolean)
              .map(roleLabel)
              .join(", ")}
          </span>
        </li>
      ))}
    </ul>
  );
}
