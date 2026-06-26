# Frontend — opportunities & spec (living doc)

Zero-backend SPA: **DuckDB-WASM + Vega-Lite + React**, querying the prebuilt
Parquet marts (`data/marts/*.parquet`) directly in the browser. No application
server (spec §8). This doc grows as the backend data shape firms up; it records
*what's buildable now* vs *what unlocks per phase*, so frontend work can start
against stable artifacts instead of waiting on the full pipeline.

## Data contract the frontend consumes

The SPA loads Parquet marts over HTTP(S) and registers them in DuckDB-WASM:

```js
await db.registerFileURL('mart_package_impact.parquet', `${BASE}/mart_package_impact.parquet`);
await conn.query(`SELECT * FROM 'mart_package_impact.parquet' WHERE repo='bioc' ORDER BY total_distinct_ips DESC LIMIT 50`);
```

Marts are the *only* coupling. The frontend never touches the DuckDB file, the
lake, or any API. New columns are additive; renames are breaking → keep mart
column names stable once published (mirror the lake's versioned-view discipline).

### Marts available now

| Mart | Grain | Columns | Notes |
|---|---|---|---|
| `mart_package_impact` | package × repo | downloads/distinct-IPs (total + trailing-12mo), `n_primary_pubs`, `n_citing_works`, `sum_rcr`, `n_distinct_grants_citing` | pub/RCR/grant cols fill after lake enrichment runs; downloads after the stats endpoint returns |
| `mart_grant_attribution` | grant | `agency`, `title`, `n_packages_supported`, `n_citing_works`, `package_names[]` | the grant-narrative payload; populated from RePORTER via lake |
| `mart_package_directory` | package × repo | name, repo, maintainer, `biocviews[]`, `url[]`, `source_doi`, title | the explorer's backing data |
| `mart_release_growth` | bioc_release | `n_packages` (+ `n_new_packages`/`net_downloads` pending history/downloads) | |

All four are exported every `build-marts` run and read directly by the SPA. The
enrichment-sourced columns are present-but-empty until `enrich_from_lake` has run,
so the frontend binds to a stable shape regardless.

> Reality check: download columns are **0 until the Bioconductor stats endpoint
> returns** (currently 404 site-wide). Build the download views now against the
> schema; they light up when the extractor's data lands. Don't hardcode around
> empty data — show an honest "stats unavailable" state.

## Views — buildable now vs phase-gated

### 1. Package explorer — **now**
Searchable/filterable table over `dim_package`: name, repo, maintainer,
biocViews chips, links (URL/BugReports), `source_doi` → resolves to the paper.
Facets: repo, biocViews term, has-DOI. FTS via DuckDB-WASM `fts` over title +
description. *3,810 packages today — this is a complete, useful view on day one.*

### 2. biocViews taxonomy browser — **now**
`dim_package.biocviews[]` is a faceted hierarchy. Treemap / collapsible tree of
package counts per term (Vega-Lite). Pairs with the explorer as a drill-down.
Cheap, high-signal, and needs nothing but Phase-1 data.

### 3. Download trends — **schema now, data on endpoint return**
Distinct-IP time series per package (the defensible proxy, spec §6), with a
**methodology-era band** (pre-Oct-2015 shaded/annotated, never silently joined).
Small-multiples for compare; repo-level rollups. Drives the impact leaderboard's
trailing-12mo sort.

### 4. Impact leaderboard — **partial now, full Phase 2**
Sort/rank by `total_distinct_ips` and `downloads_trailing_12mo` now; add
`n_citing_works` / `sum_rcr` columns when Phase-2 lake enrichment lands. Design
the column set up front so the table just gains columns, not a redesign.

### 5. Ecosystem growth (metaresearch) — **partial now**
`mart_release_growth.n_packages` per release is plottable now (one point today —
grows each release, and backfills when multi-release history lands). `net_downloads`
and `n_new_packages` fill in with downloads + version history.

### 6. Grant-attribution report — **Phase 3**
Exportable (CSV/PDF) narrative for CCSG / renewal: grant → packages supported →
citing works. Gated on `mart_grant_attribution` (RePORTER via lake). Design the
export format early since it's the grant-submission use case (req 1).

## Cross-cutting ideas worth capturing

- **Confidence-aware linkage UI.** `bridge_package_pub` carries `match_method` +
  `confidence`. The grant report should default to **DOI-matched only** (toggle
  to include `title_search`), so reviewers see defensible numbers. Surface the
  method as a badge.
- **Name-collision auditor.** The mention-mining pass (`fact_mention_candidate`)
  needs a human to eyeball FTS hits before judge budget. A tiny review view
  (snippet + section + accept/reject) doubles as the judge-training UI. (spec §6:
  `sva`, `made4`, `qpcR` collide; `limma` doesn't.)
- **"Cite this impact" deep-links.** Every package/grant view → a stable
  permalink + copyable figure for grant narratives. The whole platform's reason
  to exist (req 1) is putting a number in a renewal; make that one click.
- **Snapshot selector.** If dated Parquet snapshots land in R2 (spec §2), a
  date dropdown swaps the mart URLs — point-in-time with zero backend.

## Build-order suggestion

Explorer + biocViews browser first (real data, no dependencies), with the
download/leaderboard views scaffolded against the schema so they activate when
the stats endpoint and lake enrichment land. Defer grant export to Phase 3 but
fix its output format now — it's the headline use case.
