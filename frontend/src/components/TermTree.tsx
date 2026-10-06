import { useMemo } from "react";
import { fmtInt } from "../lib/format";

export interface TreeNode {
  data: string;
  attr: { id: string; packageList?: string };
  children?: TreeNode[];
}

interface Term {
  id: string;
  n: number;
  children: Term[];
}

// "Term (123)" -> package count; the id lives in attr.id.
function toTerm(node: TreeNode): Term {
  const n = Number(/\((\d+)\)\s*$/.exec(node.data)?.[1] ?? 0);
  return { id: node.attr.id, n, children: (node.children ?? []).map(toTerm) };
}

// Keep a node when it or any descendant matches; matching branches render open.
function prune(t: Term, q: string): Term | null {
  const children = t.children.map((c) => prune(c, q)).filter((c): c is Term => c !== null);
  return children.length || t.id.toLowerCase().includes(q) ? { ...t, children } : null;
}

function TermRow({ term, maxN, depth, filtering }: { term: Term; maxN: number; depth: number; filtering: boolean }) {
  const row = (
    <span className="flex items-center gap-2 py-0.5 text-sm">
      <a
        href={`#/explorer?view=${encodeURIComponent(term.id)}`}
        className="text-bioc-700 hover:underline"
        onClick={(e) => e.stopPropagation()}
      >
        {term.id}
      </a>
      <span className="ml-auto h-1.5 w-24 shrink-0 rounded bg-slate-100">
        <span
          className="block h-1.5 rounded bg-bioc-500"
          style={{ width: `${(term.n / maxN) * 100}%` }}
        />
      </span>
      <span className="w-12 shrink-0 text-right text-xs tabular-nums text-slate-500">
        {fmtInt(term.n)}
      </span>
    </span>
  );
  if (!term.children.length) return <div className="pl-4">{row}</div>;
  return (
    // key includes `filtering` so toggling the filter re-applies the default open state
    <details key={String(filtering)} open={filtering || depth === 0} className="pl-4 [&>summary]:cursor-pointer">
      <summary>{row}</summary>
      {term.children.map((c) => (
        <TermRow key={c.id} term={c} maxN={maxN} depth={depth + 1} filtering={filtering} />
      ))}
    </details>
  );
}

// Collapsible biocViews hierarchy; roots are open one level by default.
export function TermTree({ roots, filter }: { roots: TreeNode[]; filter: string }) {
  const terms = useMemo(() => roots.map(toTerm), [roots]);
  const q = filter.trim().toLowerCase();
  const shown = useMemo(
    () => (q ? terms.map((t) => prune(t, q)).filter((t): t is Term => t !== null) : terms),
    [terms, q],
  );
  if (!shown.length) return <p className="px-3 py-4 text-center text-sm text-slate-400">no matching terms</p>;
  return (
    <div className="-ml-4">
      {shown.map((t) => (
        // each root's bars are scaled against its own total
        <TermRow key={t.id} term={t} maxN={t.n || 1} depth={0} filtering={q !== ""} />
      ))}
    </div>
  );
}
