const intFmt = new Intl.NumberFormat("en-US");
const compactFmt = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export function fmtInt(n: number | null | undefined): string {
  return n == null ? "—" : intFmt.format(n);
}

export function fmtCompact(n: number | null | undefined): string {
  return n == null ? "—" : compactFmt.format(n);
}

export function fmtFloat(n: number | null | undefined, digits = 1): string {
  return n == null ? "—" : n.toFixed(digits);
}
