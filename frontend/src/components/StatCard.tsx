import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  sub,
  pending,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  pending?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div
        className={`mt-1 text-3xl font-semibold tabular-nums ${
          pending ? "text-slate-300" : "text-slate-900"
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}
