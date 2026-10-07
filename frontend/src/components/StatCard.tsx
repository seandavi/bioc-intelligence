import type { ReactNode } from "react";
import { InfoDot } from "./InfoDot";

export type Metric = "pubs" | "usage" | "grants" | "people";

// Literal class strings so Tailwind sees them.
export const METRIC_TEXT: Record<Metric, string> = {
  pubs: "text-metric-pubs",
  usage: "text-metric-usage",
  grants: "text-metric-grants",
  people: "text-metric-people",
};
const METRIC_BORDER: Record<Metric, string> = {
  pubs: "border-t-4 border-t-metric-pubs-fill",
  usage: "border-t-4 border-t-metric-usage-fill",
  grants: "border-t-4 border-t-metric-grants-fill",
  people: "border-t-4 border-t-metric-people-fill",
};

export function StatCard({
  label,
  value,
  sub,
  pending,
  info,
  metric,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  pending?: boolean;
  info?: string;
  metric?: Metric;
}) {
  const border = metric ? METRIC_BORDER[metric] : "";
  const text = metric ? METRIC_TEXT[metric] : "text-ink";
  return (
    <div className={`rounded-xl border border-primary-75 bg-white p-4 shadow-sm ${border}`}>
      <div className="text-xs font-medium uppercase tracking-wide text-neutral-300">
        {label}
        {info && <InfoDot tip={info} />}
      </div>
      <div
        className={`mt-1 text-3xl font-semibold tabular-nums ${
          pending ? "italic text-neutral-300" : text
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-neutral-300">{sub}</div>}
    </div>
  );
}
