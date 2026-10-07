// Small shared presentational bits used across views.
import type { ReactNode } from "react";
import { Link } from "../lib/router";
import { InfoDot } from "./InfoDot";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    info?: string;
  }
}

// Visible keyboard focus ring shared by every text input and select.
export const INPUT_CLASS =
  "rounded-md border border-neutral-100 px-3 py-1.5 text-sm focus:border-brand-teal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal";

// Visually hidden text that screen readers still announce (input labels).
export function SrLabel({ htmlFor, children }: { htmlFor: string; children: ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="sr-only">
      {children}
    </label>
  );
}

// Column header cell: a real <button> toggles sorting, aria-sort exposes the state.
// `info` renders an InfoDot beside (not inside) the button, since buttons can't nest.
export function SortableTh({
  sorted,
  onToggle,
  info,
  className = "",
  children,
}: {
  sorted: false | "asc" | "desc";
  onToggle?: (event: unknown) => void;
  info?: string;
  className?: string;
  children: ReactNode;
}) {
  if (!onToggle) {
    return (
      <th scope="col" className={`px-3 py-2 ${className}`}>
        {children}
        {info && <InfoDot tip={info} />}
      </th>
    );
  }
  return (
    <th
      scope="col"
      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
      className={`px-3 py-2 ${className}`}
    >
      <button
        type="button"
        onClick={onToggle}
        className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-neutral-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
      >
        {children}
        <span aria-hidden className={sorted ? "" : "text-neutral-300"}>
          {sorted === "asc" ? "↑" : sorted === "desc" ? "↓" : "↕"}
        </span>
      </button>
      {info && <InfoDot tip={info} />}
    </th>
  );
}

export const REPO_LABEL: Record<string, string> = {
  bioc: "Software",
  "data-experiment": "Experiment",
  "data-annotation": "Annotation",
  workflows: "Workflow",
};

export function RepoBadge({ repo }: { repo: string }) {
  return (
    <span className="inline-block rounded bg-primary-50 px-1.5 py-0.5 text-xs text-primary-400">
      {REPO_LABEL[repo] ?? repo}
    </span>
  );
}

export function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-block rounded bg-primary-50 px-1.5 py-0.5 text-xs text-primary-400">
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
      className="inline-block rounded bg-secondary-75 px-1.5 py-0.5 text-xs text-secondary-600 hover:bg-secondary-100 hover:underline"
    >
      {term}
    </Link>
  );
}
