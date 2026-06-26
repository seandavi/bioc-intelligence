// A small "?" marker with a hover tooltip explaining a value in a sentence or two.
// CSS-only (group-hover); stops click propagation so it never triggers column sort.
export function InfoDot({ tip }: { tip: string }) {
  return (
    <span
      className="group/info relative ml-1 inline-flex align-middle"
      onClick={(e) => e.stopPropagation()}
    >
      <span className="flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full border border-slate-300 text-[9px] font-bold leading-none text-slate-400">
        ?
      </span>
      <span className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 hidden w-52 -translate-x-1/2 rounded-md bg-slate-800 px-2.5 py-1.5 text-xs font-normal normal-case leading-snug tracking-normal text-white shadow-lg group-hover/info:block">
        {tip}
      </span>
    </span>
  );
}
