// Small shared presentational bits used across views.
import { Link } from "../lib/router";

export const REPO_LABEL: Record<string, string> = {
  bioc: "Software",
  "data-experiment": "Experiment",
  "data-annotation": "Annotation",
  workflows: "Workflow",
};

export function RepoBadge({ repo }: { repo: string }) {
  return (
    <span className="inline-block rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
      {REPO_LABEL[repo] ?? repo}
    </span>
  );
}

export function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-block rounded bg-bioc-50 px-1.5 py-0.5 text-xs text-bioc-700">
      {children}
    </span>
  );
}

// A biocViews term that links to the Explorer filtered by it.
export function BiocViewChip({ term }: { term: string }) {
  return (
    <Link
      view="explorer"
      params={{ view: term }}
      className="inline-block rounded bg-bioc-50 px-1.5 py-0.5 text-xs text-bioc-700 hover:bg-bioc-100 hover:underline"
    >
      {term}
    </Link>
  );
}
