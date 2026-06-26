# bioc-intelligence — frontend

Zero-backend SPA (Vite + React + TypeScript + Tailwind) that queries the
pipeline's Parquet marts directly in the browser via **DuckDB-WASM**. No
application server (spec §8). Deployed to GitHub Pages.

## Develop

```bash
npm install
npm run dev          # local dev server
npm run typecheck    # tsc --noEmit
npm run lint         # eslint
npm run build        # tsc + vite build -> dist/
npm run preview      # serve the production build
```

## Data

The app reads `public/data/*.parquet` (bundled into the build) plus a
`manifest.json` snapshot stamp. Refresh them from the pipeline's output with:

```bash
bash scripts/sync-marts.sh   # copies ../data/marts/*.parquet -> public/data/ + manifest
```

DuckDB-WASM boots once (`src/db/duckdb.ts`), registers each mart as a named file,
and exposes `useQuery(sql)` (`src/db/useQuery.ts`). Pages compute their numbers
live from SQL over the marts — so views grow automatically as enrichment fills in.

## Notes

- The DuckDB-WASM runtime is loaded from jsDelivr at startup (keeps the build
  simple); the marts themselves are bundled and served from the site.
- Vega bundles are large (~390 kB gzip); code-splitting them is a future
  optimization, not a correctness issue.
