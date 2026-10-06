import { useId, useState } from "react";

// A small "?" button with a tooltip explaining a value in a sentence or two.
// Shown on hover, on keyboard focus, and pinned open by click/tap (blur or Escape closes);
// stops click propagation so it never triggers column sort or row expansion.
export function InfoDot({ tip }: { tip: string }) {
  const id = useId();
  const [pinned, setPinned] = useState(false);
  return (
    <span className="group/info relative ml-1 inline-flex align-middle">
      <button
        type="button"
        aria-label="More info"
        aria-describedby={id}
        onClick={(e) => {
          e.stopPropagation();
          setPinned(!pinned);
        }}
        onBlur={() => setPinned(false)}
        onKeyDown={(e) => e.key === "Escape" && setPinned(false)}
        className="flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full border border-slate-400 text-[9px] font-bold leading-none text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bioc-500"
      >
        ?
      </button>
      <span
        id={id}
        role="tooltip"
        className={`pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 w-52 -translate-x-1/2 rounded-md bg-slate-800 px-2.5 py-1.5 text-xs font-normal normal-case leading-snug tracking-normal text-white shadow-lg group-hover/info:block group-has-[:focus-visible]/info:block ${
          pinned ? "block" : "hidden"
        }`}
      >
        {tip}
      </span>
    </span>
  );
}
