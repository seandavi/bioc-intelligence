import type { VisualizationSpec } from "vega-embed";

export const ACCENT = "#1f7bbf";

// Horizontal bar of `field` by `label`, sorted descending. Data carries inline.
export function horizontalBar(
  values: Record<string, unknown>[],
  field: string,
  label: string,
  title: string,
): VisualizationSpec {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: { text: title, fontSize: 13, color: "#334155" },
    data: { values },
    mark: { type: "bar", color: ACCENT, cornerRadiusEnd: 3 },
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
