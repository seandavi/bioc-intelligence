// Explorer search: compare with case and whitespace removed on both sides, so
// "differential expression" matches the biocViews term "DifferentialExpression".
export const normalise = (s: string) => s.toLowerCase().replace(/\s+/g, "");

// One precomputed haystack per row. Fields are joined with a control character so a
// query cannot match across the boundary between two fields.
export const searchKey = (...fields: (string | null | undefined)[]) =>
  fields.map((f) => normalise(f ?? "")).join("\u0001");
