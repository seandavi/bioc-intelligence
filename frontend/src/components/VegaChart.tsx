import { useEffect, useRef } from "react";
import embed, { type VisualizationSpec } from "vega-embed";

// Thin wrapper around vega-embed: render a Vega-Lite spec into a div, clean up on
// unmount/spec-change. Specs here carry their data inline (from mart queries). `subtitle`
// (e.g. the snapshot date) is injected under the title so exported figures are self-describing.
export function VegaChart({
  spec,
  className,
  subtitle,
}: {
  spec: VisualizationSpec;
  className?: string;
  subtitle?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    let view: { finalize: () => void } | undefined;
    let disposed = false;
    const t = (spec as { title?: string | { text?: string } }).title;
    const text = typeof t === "string" ? t : t?.text;
    const titled =
      subtitle && text
        ? ({ ...spec, title: { ...(typeof t === "object" ? t : {}), text, subtitle } } as VisualizationSpec)
        : spec;
    const downloadFileName = (text ?? "bioconductor-intelligence")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 80);
    embed(ref.current, titled, {
      actions: { export: true, source: false, compiled: false, editor: false },
      downloadFileName,
      renderer: "svg",
    })
      .then((result) => {
        if (disposed) result.view.finalize();
        else view = result.view;
      })
      .catch(() => {
        /* spec errors are non-fatal for the dashboard */
      });
    return () => {
      disposed = true;
      view?.finalize();
    };
  }, [spec, subtitle]);

  return <div ref={ref} className={className} />;
}
