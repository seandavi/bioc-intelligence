# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

**Phase 1 (MVP) backend is implemented and live-verified.** `bioc-intelligence-spec.md` remains
the source of truth (architecture + settled decisions below); `docs/frontend-spec.md` tracks
frontend opportunities. Package extraction runs against `bioconductor.org` and loads 3,810
packages across all four repos. Download extraction is built + unit-tested but the Bioconductor
stats `.tab` endpoints currently **404 site-wide** (BioC 3.23 redesign), so it logs-and-skips per
`BiocPkgTools` convention until they return. Phases 2–4 (lake enrichment, grants, mention mining)
are designed and stubbed.

## Commands

Python project managed with `uv` (Python ≥3.11). Deps: `duckdb`, `httpx`, `pyyaml`.

```bash
uv venv && uv pip install -e '.[dev]'   # setup

uv run biocintel init-db                 # create DuckDB store + schema
uv run biocintel extract-packages        # VIEWS -> dim_package(_version), all 4 repos (~25s live)
uv run biocintel extract-packages --devel --repos bioc   # add devel channel / scope repos
uv run biocintel extract-downloads       # stats tabs -> fact_download (currently skips: 404)
uv run biocintel build-marts             # derive mart_* -> data/marts/*.parquet
uv run biocintel all                     # the three extract/build steps in order

uv run pytest                            # tests (parsers; no network)
uv run pytest tests/test_dcf.py          # a single test file
uv run ruff check src tests              # lint (must stay clean)
```

HTTP responses are cached under `data/cache/` (set `BIOCINTEL_NO_CACHE=1` to bypass). The DuckDB
file (`data/biocintel.duckdb`) and marts are gitignored and fully rebuildable. Inspect the store
directly with `duckdb data/biocintel.duckdb`.

## Layout

```
src/biocintel/
  config.py      # source URLs, the 4 repos (note: VIEWS/stats dir/stats-file names diverge),
                 # release metadata from config.yaml, methodology-era boundary
  http.py        # retrying GET + on-disk cache; HttpError(404) lets callers skip-not-fail
  dcf.py         # DCF parser for VIEWS/DESCRIPTION (+ list/maintainer helpers)
  db.py          # DuckDB connect + schema bootstrap
  schema.sql     # canonical DDL (all spec §5 tables)
  pipeline/      # framework-free, independently runnable modules
    extract_packages.py   extract_downloads.py   build_marts.py
  cli.py         # `biocintel` dispatch
tests/           # parser unit tests (fixture-based; runnable offline)
```

Each pipeline module is runnable standalone (`python -m biocintel.pipeline.extract_packages`) and
exposes a `run()` callable the CLI and (future) GitHub Actions orchestrator both call.

## What this is

A research-intelligence and impact-analytics platform for the **Bioconductor** ecosystem. It
captures package releases, metadata, publications, citations, download telemetry, and grant
linkages to serve three use cases: grant-submission impact evidence, a public impact dashboard,
and metaresearch (Bioconductor as an object of study). It follows the "UCCC research-intelligence
pattern": identity-anchored spine, OpenAlex / iCite / NIH RePORTER enrichment, DuckDB + Parquet,
zero-backend SPA frontend.

## Upstream: cdsci-lake (the enrichment source)

All shared enrichment corpora come **read-only from `../cdsci-lake`** — the
cancerdatasci research-data lake (DuckLake: Postgres catalog + Cloudflare R2
data). This project is its first external consumer; it consumes the *data
contract*, not the lake's code, and does **not** re-fetch from OpenAlex / iCite /
RePORTER / Europe PMC APIs. The "no lake" decision (below) governs this project's
*own* store, not its sourcing — we read the shared lake, we don't build one.

Connect via the lake's read client. **The `.env` deliberately leaves the backend
unset (defaults to a small local dev catalog), so prod reads need the override:**

```bash
cd ../cdsci-lake && CU_OPENALEX_LAKE_BACKEND=postgres uv run python -c "
from cdsci.lake import lake_connect
con = lake_connect(read_only=True)   # ATTACHes DuckLake as 'lake'; creds from GSM via gcloud
"
```

Credentials (Postgres password + R2 keys) come from Google Secret Manager
(project `cdsci-infra`) via the `gcloud` CLI — the user has authorized this
access; the read client fetches them itself. DuckLake tables are **not** visible
via `information_schema`/`SHOW ALL TABLES`; introspect with `duckdb_tables()` /
`duckdb_schemas()` filtered to `database_name='lake'`, or query `lake.<schema>.<table>` directly.

Verified tables this project depends on (all under the `lake` catalog):

| Need | Lake table | Key columns |
|---|---|---|
| Package→manuscript (DOI + title) | `openalex.works` (114M) | `doi`, `pmid`, `title`, `cited_by_count`, `fwci`, `grants` |
| `fact_citation_edge` (cited-by) | `openalex.work_references` (1.29B) | `work_id`, `referenced_work_id` |
| `dim_work` RCR/citation | `icite.metadata` | `pmid`, `doi`, `rcr`, `nih_percentile`, `citation_count` |
| Grants | `reporter.publink` + `reporter.projects` | `pmid`→`project_number`; full grant detail |
| Publication spine | `omicidx.pubmed_article` | `pmid`, `doi`, `references` |
| Full-text mentions | `pmc.passages` (974M) | `pmcid`, `section_type`, `text` |

What stays bespoke (not in the lake): Bioconductor package manifest +
DESCRIPTION, download-stats tabs, CITATION parsing, git tags.

## Architecture (the big picture)

Three layers, single direction of data flow:

1. **Extract/enrich pipeline** — a thin orchestrator (the "omicidx pattern": framework-free
   extract modules) over GitHub Actions. Two kinds of module: *bespoke extracts* of
   Bioconductor-native sources (`extract_packages.py`, `extract_downloads.py`) that fetch over
   HTTP/parse, and *lake-sourced* steps that `ATTACH` cdsci-lake read-only and enrich via
   **cross-catalog SQL** rather than API clients (`link_works.py`, `enrich_from_lake.py`,
   `mine_mentions.py` — these replace the old per-API `enrich_openalex`/`enrich_icite`/
   `enrich_reporter`/`mine_epmc` modules). Then `judge_mentions.py` and `build_marts.py`. All write
   into the one local DuckDB file. See spec §7.
2. **Canonical store** — a single DuckDB file is the working lakehouse. `build_marts.py` runs
   DuckDB SQL to export `mart_*` tables to **Parquet**, which is the publishable/distributable
   artifact.
3. **Frontend** — a zero-backend SPA (DuckDB-WASM + Vega-Lite + React) that queries the prebuilt
   Parquet marts directly in the browser. No application server.

**Data model shape (spec §5):** dimensions (`dim_package`, `dim_package_version`, `dim_work`,
`dim_grant`) are *rebuilt per release*. Fact tables (`fact_download`, `fact_citation_edge`,
`fact_mention_candidate`) are *append-only and snapshot-stamped* (`_snapshot` column). Bridges
(`bridge_package_pub`, `bridge_work_grant`) carry provenance. Marts (`mart_package_impact`,
`mart_grant_attribution`, `mart_release_growth`) are derived and exported.

## Settled decisions — do not re-litigate

These were deliberately chosen in the spec (§2, §10). Honor them unless the user explicitly
reopens the question:

- **No DuckLake / catalog / time-travel for this project's own store.** Single-writer,
  batch-refresh workload. Historization that matters is *domain time* (downloads/citations over
  time) and lives as explicit snapshot columns/rows, **not** catalog versions. Point-in-time, if
  ever needed, = dated Parquet snapshots in R2 — not a catalog layer. (This is about the local
  store only — upstream enrichment *is* read from the shared cdsci-lake DuckLake; see above.)
- **Single DuckDB file** is canonical; **Parquet marts** are distribution. One file, copy it, done.
- **All four repos** (`bioc`, `data-experiment`, `data-annotation`, `workflows`); `bioc` is tier-1,
  the rest tier-2 (enriched lazily).
- **Maintainer → ROR is best-effort** — populate when it falls out cleanly, **never block a
  pipeline on it**.
- **Mention text is stored raw, then judged on a separate, later pass** (see below).

## Two patterns that drive the design (spec §6)

- **Package → manuscript linkage (`bridge_package_pub`).** Kept simple for now: join a DOI
  (from DESCRIPTION `URL`/`BugReports` or CITATION) to `lake.openalex.works.doi`
  (`match_method = 'doi'`, authoritative), else FTS the title against
  `lake.openalex.works.title` and take the top hit (`match_method = 'title_search'`). Every edge
  **must** carry `match_method` (`doi` | `title_search` | `manual`) and `confidence` so the
  dashboard can filter to high-confidence (DOI) linkages for grant reporting. Scored fuzzy matching
  against Crossref and a human-curated override table are **deferred** — revisit only if title
  search is too noisy.
- **Decoupled mention extract → judge.** The full-text corpus is already in the lake
  (`lake.pmc.passages`, ~974M passages), so mining informal package mentions is an FTS query over
  the lake, **not** a rate-limited Europe PMC API crawl. Still materialize candidates **once** into
  `fact_mention_candidate` (storing verbatim `mention_text`) — FTS over ~10⁹ passages isn't free,
  and the judge is decoupled. A later LLM-as-judge pass (independent cadence) fills the nullable
  judge columns (`is_genuine_mention`, `package_confidence`, `usage_vs_passing_reference`) and
  promotes confirmed candidates into `fact_citation_edge` with `mention_type = 'fulltext'`. Use the
  DuckDB `fts` extension over `mention_text` to audit name collisions (e.g. `sva`, `made4`, `qpcR`
  collide with common words; `limma` does not) *before* spending judge budget.

## Domain gotchas

- **Download stats:** prefer **distinct IPs** as the usage proxy, not raw downloads. Collection
  methodology changed ~Oct 2015 — carry a `methodology_era` column; never silently concatenate
  eras.
- **Work identity:** PMID preferred, DOI fallback, OpenAlex ID is an enrichment handle only.

## Phasing (spec §9)

Build in order: (1) MVP packages × versions × downloads → SPA; (2) CITATION linkage + OpenAlex
cited-by; (3) RePORTER / OpenAlex grant enrichment; (4) EPMC full-text mining + LLM judge +
ecosystem analytics.
