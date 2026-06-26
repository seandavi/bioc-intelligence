// Small shared presentational bits used across views.

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
