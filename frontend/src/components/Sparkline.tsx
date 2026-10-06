import { useMemo } from "react";
import type { VisualizationSpec } from "vega-embed";
import { VegaChart } from "./VegaChart";
import { ACCENT } from "./charts";

// One row of mart_package_downloads_monthly. package_name is only needed to tell
// series apart when several packages share a chart.
export interface MonthlyRow {
  package_name?: string;
  year: number;
  month: number;
  distinct_ips: number;
  methodology_era: string;
}

// Download-log collection changed in October 2015; counts either side are not comparable.
export const ERA_START = "2015-10-01";

// Shaded rect over the pre-October-2015 era, from `from` (ISO date) to the boundary.
// Layer it first so it sits under the data. Its x axis must match the data layer's
// (Vega-Lite fails to merge an axis-less layer with an axis-bearing one).
export const eraBand = (from: string, axes = true) => ({
  data: { values: [{ start: from, end: ERA_START }] },
  mark: { type: "rect", color: "#e2e8f0", opacity: 0.7 },
  encoding: {
    x: { field: "start", type: "temporal", ...(axes ? {} : { axis: null }) },
    x2: { field: "end" },
    tooltip: { value: "Before Oct 2015: older download-log methodology, not comparable" },
  },
});

const pad = (m: number) => String(m).padStart(2, "0");

// Monthly distinct IPs as lines, one per package. `detail` on the era breaks each line at
// the methodology boundary so no segment joins the two eras.
export function monthlyIpsSpec(
  rows: MonthlyRow[],
  { height, log = false, axes = false }: { height: number; log?: boolean; axes?: boolean },
): VisualizationSpec {
  // Log scales cannot show zero months.
  const values = rows
    .filter((r) => !log || r.distinct_ips > 0)
    .map((r) => ({ ...r, date: `${r.year}-${pad(r.month)}-01` }));
  const multi = new Set(values.map((r) => r.package_name)).size > 1;
  const crosses = new Set(values.map((r) => r.methodology_era)).size > 1;
  const first = values.reduce((a, r) => (r.date < a ? r.date : a), ERA_START);
  const line = {
    data: { values },
    mark: { type: "line", strokeWidth: axes ? 2 : 1.5, ...(multi ? {} : { color: ACCENT }) },
    encoding: {
      x: { field: "date", type: "temporal", axis: axes ? { title: null } : null },
      y: {
        field: "distinct_ips",
        type: "quantitative",
        scale: { type: log ? "log" : "linear" },
        axis: axes ? { title: "Distinct IPs / month" } : null,
      },
      detail: { field: "methodology_era" },
      ...(multi
        ? { color: { field: "package_name", type: "nominal", legend: { orient: "top", title: null } } }
        : {}),
      tooltip: [
        ...(multi ? [{ field: "package_name", type: "nominal", title: "Package" }] : []),
        { field: "date", type: "temporal", format: "%b %Y", title: "Month" },
        { field: "distinct_ips", type: "quantitative", format: ",", title: "Distinct IPs" },
      ],
    },
  };
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    width: "container",
    height,
    layer: crosses ? [eraBand(first, axes), line] : [line],
    config: { view: { stroke: null } },
  } as VisualizationSpec;
}

// Axis-less monthly distinct-IP trend for one package.
export function Sparkline({ rows, height = 32 }: { rows: MonthlyRow[]; height?: number }) {
  const spec = useMemo(() => monthlyIpsSpec(rows, { height }), [rows, height]);
  return <VegaChart spec={spec} className="w-full" />;
}
