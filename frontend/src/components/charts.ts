import type { VisualizationSpec } from "vega-embed";

// Chart fills per metric family; the same hex values as --metric-*-fill in index.css.
export const METRIC = {
  pubs: "#0087af",
  usage: "#18a603",
  grants: "#f1c736",
  people: "#5d657c",
} as const;
// Counts with no metric family (packages, biocViews terms).
export const NEUTRAL = "#797f92";
// Nominal series (repos, compared packages): teal and slate steps, so no category reads as
// a metric colour.
export const CATEGORY = ["#035771", "#8bc0cf", "#5d657c", "#59a5bb", "#a1a6b3"];
export const TITLE_COLOR = "#414757";

// Horizontal bar of `field` by `label`, sorted descending. Data carries inline.
export function horizontalBar(
  values: Record<string, unknown>[],
  field: string,
  label: string,
  title: string,
  color: string,
): VisualizationSpec {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: { text: title, fontSize: 13, color: TITLE_COLOR },
    data: { values },
    mark: { type: "bar", color, cornerRadiusEnd: 3 },
    encoding: {
      y: { field: label, type: "nominal", sort: "-x", axis: { title: null, labelLimit: 160 } },
      x: { field, type: "quantitative", axis: { title: null, grid: false } },
      tooltip: [
        { field: label, type: "nominal" },
        { field, type: "quantitative" },
      ],
    },
    width: "container",
    height: { step: 20 },
    config: { view: { stroke: null } },
  } as VisualizationSpec;
}
