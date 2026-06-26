import { useEffect, useRef } from "react";
import embed, { type VisualizationSpec } from "vega-embed";

// Thin wrapper around vega-embed: render a Vega-Lite spec into a div, clean up on
// unmount/spec-change. Specs here carry their data inline (from mart queries).
export function VegaChart({ spec, className }: { spec: VisualizationSpec; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    let view: { finalize: () => void } | undefined;
    let disposed = false;
    embed(ref.current, spec, { actions: false, renderer: "svg" })
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
  }, [spec]);

  return <div ref={ref} className={className} />;
}
