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
| `mart_package_impact` | package × repo | downloads/distinct-IPs (total + trailing-12mo), `distinct_ips_prior_12mo` (the 12 months before the trailing window), `usage_rank_in_repo` (rank by trailing-12mo distinct IPs within the repo), `n_primary_pubs`, `n_citing_works`, `sum_rcr`, `n_distinct_grants_citing` | pub/RCR/grant cols fill after lake enrichment runs; downloads once `extract-downloads` runs in the refresh |
| `mart_grant_attribution` | grant | `agency`, `title`, `n_packages_supported`, `n_citing_works`, `package_names[]` | the grant-narrative payload; populated from RePORTER via lake |
| `mart_package_directory` | package × repo | name, repo, maintainer, title, `description`, `biocviews[]`, `url[]`, `source_doi`, `n_reverse_deps`, `n_deps`, `git_last_commit_date`, `package_status`, `has_news`, `n_vignettes`, `license`, `bioc_url` | the explorer's backing data; no `maintainer_email` (privacy, #33); VIEWS fields from #39 |
| `mart_package_work` | package × repo × work | `work_id`, `doi`, `pmid`, `title`, `year`, `journal`, `citation_count`, `icite_rcr`, `match_method`, `confidence`, `role` | papers the package asks users to cite; highest-confidence edge per pair; metadata NULL until the work is enriched into `dim_work` |
| `mart_release_growth` | bioc_release | `release_date`, `n_software_announced`, `n_packages`, `n_new_packages`, `n_removed`, `net_downloads` (NULL, needs release-windowed downloads) | one row per announced release (1.0 onwards); `n_*` from VIEWS (1.8 onwards, NULL before), all repos with a package counted once by name; new/removed NULL for the first loaded release; sort releases numerically (`string_split(bioc_release,'.')::INT[]`) |
| `mart_release_history` | bioc_release × repo | `release_date`, `n_packages`, `n_new`, `n_removed` | per-repo VIEWS diffs; new = first release listing the package in that repo, removed = in the repo's previous loaded release and not this one; needs `extract-packages --all-releases` once, else current release only |
| `mart_package_person` | package × repo × person | `person_id`, name, `orcid`, `roles[]`, `is_maintainer`, `source` | people credited on a package; no emails (not stored upstream) |
| `mart_person` | person | name, `orcid`, `n_packages`, `n_maintained`, `n_authored`, `package_names[]` | "developers with more than N packages"; identity = ORCID, else normalized name |
| `mart_ecosystem_downloads_yearly` | year × repo × methodology_era | `distinct_ips`, `downloads`, `n_packages_with_downloads` | latest `_snapshot` per repo; eras stay separate rows (2015 has one per era) — draw the boundary, don't join across it; `distinct_ips` is summed over months |
| `mart_package_downloads_monthly` | package × repo × year × month | `distinct_ips`, `downloads`, `methodology_era` | sorted by `package_name, repo, year, month` and written with 2,048-row row groups so DuckDB-WASM can range-read one package; filter on `package_name` |
| `mart_package_funder` | package × repo × funder | `funder_id`, `funder_name`, `curated`, `declared_name`, `grant_number`, `grant_id` | declared (`fnd`) funders only; `grant_id` set when the NIH grant matches a RePORTER core project in `dim_grant`; `curated=false` rows are as-written (many are PIs, not agencies) |
| `mart_work_institution` | work × institution × author position | `ror`, `name`, `country_code`, `country`, `author_position`, `is_corresponding`, `latitude`, `longitude` | OpenAlex authorship affiliations of linked works (`dim_work` rows with an OpenAlex id); best-effort; `author_position='last'` gives senior-author countries; join `mart_package_work` on `work_id` for a package's institutions |

The marts above are exported every `build-marts` run (the SPA registers its own subset in `frontend/src/db/duckdb.ts`). The
enrichment-sourced columns are present-but-empty until `enrich_from_lake` has run,
so the frontend binds to a stable shape regardless.

> Reality check: download columns are **0 until `extract-downloads` runs in the
> monthly refresh** (the stats endpoints 404'd after the BioC 3.23 redesign and
> are back as of 2026-10-01). Build the download views now against the schema;
> they light up when the extractor's data lands. Don't hardcode around
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

### 3. Download trends — **schema now, data once downloads are in the refresh**
Distinct-IP time series per package (the defensible proxy, spec §6), with a
**methodology-era band** (pre-Oct-2015 shaded/annotated, never silently joined).
Small-multiples for compare; repo-level rollups. Drives the impact leaderboard's
trailing-12mo sort.

### 4. Impact leaderboard — **partial now, full Phase 2**
Sort/rank by `total_distinct_ips` and `downloads_trailing_12mo` now; add
`n_citing_works` / `sum_rcr` columns when Phase-2 lake enrichment lands. Design
the column set up front so the table just gains columns, not a redesign.

### 5. Ecosystem growth (metaresearch) — **partial now**
Built (#44): packages per release by repo from `mart_release_history` (2002 onwards,
with 1.0–1.7 drawn dashed from `n_software_announced`), new vs removed per release, and
distinct IPs per year from `mart_ecosystem_downloads_yearly` with the era band.
`net_downloads`, deprecated-per-release and maintainers-per-release are still open
(VIEWS history keeps only package and version per release).

### 6. Grant-attribution report — **Phase 3**
Exportable (CSV/PDF) narrative for CCSG / renewal: grant → packages supported →
citing works. Gated on `mart_grant_attribution` (RePORTER via lake). Design the
export format early since it's the grant-submission use case (req 1).

### 7. Data page and published views file — **now** (#51)
`#/data` shows the `ATTACH` one-liner first (SQL, R, Python), then each mart's
Parquet URL with its size and a client-side CSV export (DuckDB-WASM casts every
column to text, `lib/csv.ts` writes the file), the data dictionary, how to cite
and the Pages hosting note. Sizes and the dictionary come from
`data/datapackage.json`. It and `data/bioc-intelligence.duckdb` (a views-only
file: one view per mart, the honest-default views `package_pubs_confident`,
`downloads_modern_era`, `ecosystem_yearly` and `package_impact_ranked`, and the
`package()`/`grant_report()` macros) are both written by
`build_marts.write_views_db` from `build_marts.DEFINITIONS`, the one place mart
and column definitions live. Add a definition there when a mart gains a column:
the test fails, and so would the refresh.

### 8. Static JSON API and badges — **now** (#52)
`biocintel export-api` (`pipeline/export_api.py`) runs in `deploy-pages.yml` after
`npm run build` and writes into `dist` only, never git: `api/v1/index.json`,
`api/v1/package/<name>.json` (directory, impact, papers, grants, people, funders,
`confident_citations` under the doi + citation_file rule, dependencies once
`mart_package_dependency` is published, last 36 months of downloads),
`api/v1/grant/<id>.json`, and shields.io badges `badges/<name>/{downloads,citations}.json`.
Inputs are the same `public/data` marts the SPA reads. About 12k files and 18 MB at 3,810
packages, rendered in about 2 s. The Data page lists the URL patterns. Follow-ups: dated
snapshot directories (`data/<YYYY-MM-DD>/`) and a Zenodo DOI per snapshot.

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
