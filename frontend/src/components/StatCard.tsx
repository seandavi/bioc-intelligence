import type { ReactNode } from "react";
import { InfoDot } from "./InfoDot";

export function StatCard({
  label,
  value,
  sub,
  pending,
  info,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  pending?: boolean;
  info?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
        {info && <InfoDot tip={info} />}
      </div>
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
