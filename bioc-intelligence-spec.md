# Bioconductor Intelligence Platform — Specification

## 1. Overview

A research-intelligence and impact-analytics platform for the Bioconductor
ecosystem. Captures package releases, metadata, publications, citations,
download telemetry, and grant linkages to support three use cases:

- **Grant submission** — impact evidence for renewals and new proposals.
- **Public visibility** — dynamic dashboard of ecosystem activity and impact.
- **Metaresearch** — Bioconductor itself as an object of study.

Architecture follows the UCCC research-intelligence pattern: identity-anchored
spine, OpenAlex / iCite / NIH RePORTER enrichment, DuckDB + Parquet, zero-backend
SPA frontend.

## 2. Storage

**Upstream source:** [cdsci-lake](../cdsci-lake) (read-only) for all shared
enrichment corpora — see §4. **Canonical store:** a single DuckDB file holding
this project's own Bioconductor-native spine, facts, and marts. **Distribution:**
Parquet marts for the WASM frontend (and any external consumers).

The "no lake" decision below governs **this project's own store**, not its
sourcing: we read the shared DuckLake, we don't build one. Both are DuckDB, so
the lake attaches alongside the local file and enrichment is cross-catalog SQL
(`lake.openalex.works` joined to local `dim_package`), not an API client.

No DuckLake / catalog time-travel for the local store. This is a single-writer, batch-refresh,
canonical-data workload — there are no concurrent writers, no cross-table
transactional-rollback need, and no system-time audit requirement. The
historization that matters here is **domain time** (downloads over time,
citation counts over time), which lives in the data model as explicit snapshot
columns, not in a catalog layer. "What were the downloads last month" is a row,
not a table version.

Benefits of the plain file:

- Full extension ecosystem — `fts` (full-text search over mention text), `vss`
  (vector similarity for future mention/abstract dedup or judging), `json`,
  `httpfs`, `parquet`, `spatial` (available if geography is ever in scope).
- Simple ops: one file, copy it, done. No catalog metadata to manage.
- The file *is* the working lakehouse; Parquet marts are the publishable artifact.

Point-in-time, if ever wanted, is satisfied by keeping **dated Parquet snapshots
in R2** — cheaper and simpler than catalog time-travel, and decoupled from the
main `cdsci` data lifecycle.

## 3. Identity Spine

| Entity          | Canonical key                                      | Notes |
|-----------------|----------------------------------------------------|-------|
| Package         | `package_name` + `repo`                            | `repo ∈ {bioc, data-experiment, data-annotation, workflows}` |
| Package version | `(package_name, repo, version, bioc_release)`      | `version` = DESCRIPTION Version; `bioc_release` e.g. `3.20` |
| Work (pub)      | PMID preferred, DOI fallback, OpenAlex ID as enrichment handle | publication spine |
| Grant           | agency-native ID (NIH core project #, etc.)        | normalized agency vocab |
| Institution     | ROR                                                | best-effort maintainer attribution only |

**Scope decisions (settled):**

- **Repos:** all four. `bioc` is tier-1; the rest are tier-2 (enriched lazily).
- **Maintainer → ROR:** best-effort, keep it simple. Populate when it falls out
  cleanly; never block a pipeline on it.

## 4. Data Sources

| Domain                        | Source                                                      | Access   | Cadence    |
|-------------------------------|------------------------------------------------------------|----------|------------|
| Package list/metadata (release) | release manifest + `BiocPkgTools::biocPkgList()`         | HTTP / R | per release |
| Package metadata (devel)      | `packages/devel/<repo>/` + DESCRIPTION                     | HTTP     | weekly     |
| Package DOI / URL             | DESCRIPTION (`URL`, `BugReports`), CITATION                | parse    | per release |
| Package → manuscript          | DESCRIPTION/CITATION DOI → `openalex.works`; title search fallback | parse + lake | per release |
| Citing literature             | `openalex.work_references` (cited-by); `pmc.passages` full-text mentions | lake | monthly    |
| Download stats                | `packages/stats/<repo>/<pkg>/<pkg>_stats.tab`              | HTTP     | monthly    |
| Field-normalized impact       | `icite.metadata` (RCR, citation counts)                    | lake     | monthly    |
| Grants (describing + citing)  | `reporter.publink`/`reporter.projects`; `openalex.works.grants` | lake | monthly    |
| Version/release history       | `git.bioconductor.org` tags                                | git      | per release |

**Source of record for all "lake" rows: [cdsci-lake](../cdsci-lake)** — the
shared cancerdatasci research-data lake (DuckLake: Postgres catalog + R2 data),
read-only via its `lake_connect(read_only=True)` client. Every enrichment corpus
(OpenAlex works + references + grants, iCite, NIH RePORTER, PMC/Europe PMC
full text, the PubMed spine) already lives there — this project consumes the
data contract rather than re-fetching from APIs. Bioconductor-native rows
(package manifest, DESCRIPTION, CITATION, download-stats tabs, git tags) remain
bespoke HTTP/parse extracts. This project is cdsci-lake's first external
consumer — surfacing contract gaps is expected and welcome.

## 5. Schema

All tables live in the single DuckDB file. Fact tables are append-only and
snapshot-stamped; dimensions are rebuilt per release.

### Dimensions

```text
dim_package(
  package_name, repo,
  first_seen_release, latest_release,
  maintainer, maintainer_ror?,        -- best-effort
  biocviews[], description,
  url[], bug_reports,
  source_doi?                          -- DOI of describing manuscript, if known
)

dim_package_version(
  package_name, repo,
  version, bioc_release, release_date,
  in_devel bool
)

dim_work(
  work_id,                             -- PMID preferred, else DOI
  pmid, doi, openalex_id,
  title, year, journal,
  icite_rcr, citation_count,
  _snapshot
)

dim_grant(
  grant_id, agency, project_num,
  fy?, title?
)
```

### Facts & bridges

```text
fact_download(
  package_name, repo,
  year, month,
  distinct_ips, downloads,
  methodology_era,                     -- flags pre-Oct-2015 collection change
  _snapshot
)

bridge_package_pub(
  package_name, repo, work_id,
  role,                                -- 'primary' | 'companion'
  match_method,                        -- 'doi' | 'title_search' | 'manual'
  confidence
)

fact_citation_edge(
  cited_work_id, citing_work_id,
  source,                              -- 'openalex' | 'epmc'
  mention_type,                        -- 'formal' | 'fulltext'
  _snapshot
)

bridge_work_grant(
  work_id, grant_id, source
)
```

### Mention candidates (store raw, judge later)

```text
fact_mention_candidate(
  package_name, repo,
  citing_work_id,                      -- PMID/DOI of mentioning paper
  source,                              -- 'epmc' etc.
  mention_text,                        -- surrounding snippet, verbatim
  section,                             -- 'methods' | 'results' | ... if available
  match_offset,                        -- optional position in text
  _extracted_snapshot,

  -- judge columns, nullable, filled by a later pass:
  judged_at,
  is_genuine_mention,
  package_confidence,
  usage_vs_passing_reference
)
```

### Derived marts (exported to Parquet)

```text
mart_package_impact(
  package_name, repo,
  total_downloads, downloads_trailing_12mo,
  n_primary_pubs, n_citing_works,
  sum_rcr, n_distinct_grants_citing
)

mart_grant_attribution(
  grant_id, agency,
  n_packages_supported, n_citing_works,
  package_names[]                      -- for renewal narratives
)

mart_release_growth(
  bioc_release,
  n_packages, n_new_packages, net_downloads
)
```

## 6. The Hard Parts

**Package → manuscript linkage (`bridge_package_pub`).** Keep it simple for now:

1. **DOI** — when a DOI is available from DESCRIPTION (`URL`/`BugReports`) or the
   CITATION file, join it directly to `lake.openalex.works.doi`
   (`match_method = 'doi'`). This is authoritative.
2. **Title search** — otherwise, FTS the package/CITATION title against
   `lake.openalex.works.title` and take the top hit
   (`match_method = 'title_search'`).

Every edge still carries `match_method` + `confidence` so the dashboard can
filter to high-confidence (DOI) linkages for grant reporting. Scored fuzzy
title/author/year matching against Crossref and a human-curated override table
are **deferred** — revisit only if title search proves too noisy.

**Mention-based citation (decoupled extract → judge).** Formal DOI citations
substantially undercount real usage. Full-text search over methods sections
("X Bioconductor package", "using X version Y") recovers informal mentions. The
corpus is already in the lake — `lake.pmc.passages` (~974M passages, carrying
`section_type` + `text`) — so mining is an FTS query against the lake, **not** a
rate-limited Europe PMC API crawl. **Store the raw mention text now; apply the
judge later.** This decoupling is still the right design:

1. The judge model improves — re-run over stored text, no re-mining.
2. Mining still costs (FTS over ~10⁹ passages); materialize candidates once.
3. `fts` over `mention_text` lets you audit name collisions interactively
   *before* committing judge budget (e.g. `sva`, `made4`, `qpcR` collide with
   common words; `limma` does not).

The judge emits `{is_genuine_mention, package_confidence,
usage_vs_passing_reference}` (reusing the catchment-workbench multidimensional
LLM-as-judge pattern). A confirmed candidate is promoted into
`fact_citation_edge` with `mention_type = 'fulltext'`.

**Download-stat semantics.** The stats tabs report distinct IPs and raw
downloads per month; **distinct IPs is the defensible usage proxy.** Collection
methodology changed around Oct 2015 — carry a `methodology_era` column rather
than silently concatenating eras.

## 7. Pipeline

Thin orchestrator over framework-free extract modules (omicidx pattern). Each
module writes into the DuckDB file; marts export to Parquet. Enrichment is no
longer an API client — it's cross-catalog SQL against an `ATTACH`ed cdsci-lake
(read-only), so the former `enrich_openalex` / `enrich_icite` / `enrich_reporter`
modules collapse into one lake-read step.

```text
-- Bioconductor-native extracts (bespoke HTTP/parse):
extract_packages.py        manifest + DESCRIPTION         -> dim_package*
extract_downloads.py       stats tabs (incremental)       -> fact_download

-- Lake-sourced (read-only SQL against ATTACHed cdsci-lake):
link_works.py              DOI/title -> lake.openalex.works         -> bridge_package_pub
enrich_from_lake.py        icite.metadata -> dim_work; openalex.work_references
                           -> fact_citation_edge; reporter.* + works.grants
                           -> dim_grant / bridge_work_grant
mine_mentions.py           FTS over lake.pmc.passages               -> fact_mention_candidate

-- Judge + export:
judge_mentions.py          LLM judge over stored text     -> promote to fact_citation_edge
build_marts.py             DuckDB SQL                      -> mart_* Parquet
```

Orchestration: GitHub Actions. Monthly cron for telemetry/enrichment; on-release
trigger for dimensions. `judge_mentions.py` runs on its own cadence (independent
of mining).

## 8. Frontend

Zero-backend SPA — DuckDB-WASM + Vega-Lite + React — over prebuilt Parquet marts
published per refresh. Views:

- Package explorer (metadata, versions, DOIs, links).
- Download trends (distinct-IP series, methodology-era aware).
- Impact leaderboard.
- Grant-attribution report (exportable for CCSG / renewal narratives).
- Ecosystem-growth metaresearch.

## 9. Phasing

1. **MVP (reqs 1–3, 6):** packages × versions × downloads → SPA. Days, not weeks.
2. **Publications (4, partial 5):** CITATION linkage + OpenAlex cited-by.
3. **Grants (7–8):** RePORTER / OpenAlex enrichment + `mart_grant_attribution`.
4. **Metaresearch (full 5):** EPMC full-text mining + LLM judge; ecosystem analytics.

## 10. Settled Decisions

- **No lake.** Single DuckDB file (canonical) + Parquet marts (distribution);
  optional dated Parquet snapshots in R2 for point-in-time.
- **All four repos**, `bioc` tier-1.
- **Maintainer → ROR best-effort**, never blocking.
- **Mention text stored raw**, judged on a later, independent pass.
