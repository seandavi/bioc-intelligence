# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

**Phase 1 (MVP) backend is implemented and live-verified.** `bioc-intelligence-spec.md` remains
the source of truth (architecture + settled decisions below); `docs/frontend-spec.md` tracks
frontend opportunities. Package extraction runs against `bioconductor.org` and loads 3,810
packages across all four repos. Download stats (2009–present, ~669k package-months across all four repos) load
in the monthly refresh; the `.tab` endpoints 404'd for a while after the BioC 3.23 redesign and
were back by 2026-10, and a 404 still logs-and-skips per `BiocPkgTools` convention. Phase 2–3 lake
enrichment (works, RCR, grants) runs monthly; cited-by edges and Phase-4 mention mining/judging
are built but opt-in and not yet run at scale.

## Commands

Python project managed with `uv` (Python ≥3.11). Deps: `duckdb`, `httpx`, `pyyaml`.

```bash
uv venv && uv pip install -e '.[dev]'   # setup

uv run biocintel init-db                 # create DuckDB store + schema
uv run biocintel extract-packages        # VIEWS -> dim_package(_version), all 4 repos (~25s live)
uv run biocintel extract-packages --devel --repos bioc   # add devel channel / scope repos
uv run biocintel extract-packages --all-releases          # + every past release's VIEWS (~7 min cold)
uv run biocintel extract-downloads       # stats tabs -> fact_download (skips a repo on 404)
uv run biocintel extract-citations       # CITATION/Description DOIs -> bridge_package_pub (all 4 repos; lake-free)
uv run biocintel extract-people          # Authors@R -> dim_person/dim_funder + bridge_package_person/_funder (lake-free; no emails stored)
uv run biocintel build-marts             # derive mart_* -> data/marts/*.parquet
uv run biocintel all                     # the three extract/build steps in order

uv run pytest                            # tests (parsers; no network)
uv run pytest tests/test_dcf.py          # a single test file
uv run ruff check src tests              # lint (must stay clean)
```

Phase-2 enrichment reads the lake, so it needs the cdsci-lake client + the prod backend:

```bash
uv pip install -e ../cdsci-lake                                  # one-time, local sibling
CU_OPENALEX_LAKE_BACKEND=postgres uv run python -m biocintel.pipeline.link_works
CU_OPENALEX_LAKE_BACKEND=postgres uv run python -m biocintel.pipeline.link_works --title-fallback
```

`link_works` joins `dim_package.source_doi` to `lake.openalex.works.doi` (authoritative) and writes
`bridge_package_pub`. Then `enrich_from_lake` fills the rest:

```bash
CU_OPENALEX_LAKE_BACKEND=postgres uv run python -m biocintel.pipeline.enrich_from_lake
CU_OPENALEX_LAKE_BACKEND=postgres uv run python -m biocintel.pipeline.enrich_from_lake --steps works,grants,citations
```

- `works` (default) — linked OpenAlex works + iCite RCR → `dim_work`.
- `institutions` (default) — `openalex.works_authorships` + `openalex.institutions` for every
  `dim_work` row with an OpenAlex id → `dim_institution` + `bridge_work_institution` (rebuilt each
  run; ~12 min, the authorships scan). Best-effort: a failure is logged and the run continues.
- `grants` (default) — `reporter.publink`/`projects` → `dim_grant` + `bridge_work_grant`.
- `citations` (**opt-in**) — `openalex.work_references` cited-by → `fact_citation_edge`. Scans the
  **1.29B-row** references table plus a second `works` pass; run deliberately for a full refresh.

Mention mining + judging (spec §6 — mine once, judge later, decoupled):

```bash
# Mine full-text mentions from lake.pmc.passages (~974M rows). Explicit packages required;
# --passage-limit bounds the scan for a cheap smoke test (omit for the full corpus).
CU_OPENALEX_LAKE_BACKEND=postgres uv run python -m biocintel.pipeline.mine_mentions \
    --packages limma,DESeq2 --passage-limit 200000
# Judge stored candidates (LOCAL only, no lake). null judge by default — wire a real judge.
uv run python -m biocintel.pipeline.judge_mentions
```

`judge_mentions` operates purely on the local store and takes a pluggable `judge(cands)->verdicts`
callable; no model is wired yet (`null_judge` is a no-op for plumbing). Confirmed candidates get
promoted into `fact_citation_edge` (`mention_type='fulltext'`).

The works scan over 114M rows takes ~80s; that's expected for a batch step. The lake dep is lazy
(imported only inside `lake.connect_with_lake`), so the offline tests and CI never need it.

**Lake contract gotchas found as first consumer** (verified live; candidates for upstream
versioned-view aliases): `openalex.works.doi` is bare-lowercase (no `doi.org/` prefix);
`openalex.works.pmid` is a nullable BIGINT; **`reporter.publink.project_number` is a *core* project
number — join `reporter.projects.core_project_num`, not `project_num`.**

The monthly refresh runs on **onclappc02** as a systemd `--user` timer, not GitHub Actions (the
Actions runner couldn't reach the lake Postgres; see commit `8538472` and the README's *Scheduled
refresh*). `systemd/biocintel-refresh.service` runs the extract → link → enrich → build-marts →
`sync-marts.sh` → `systemd/publish-marts.sh` steps; the last commits `data: monthly mart refresh`
and pushes, which triggers Deploy Pages. The units under `~/.config/systemd/user/` are **copies**,
not symlinks — re-copy and `systemctl --user daemon-reload` after editing them here.

`sync-marts.sh` also writes `frontend/public/data/bioc-intelligence.duckdb` and `datapackage.json`
via `biocintel build-marts --marts-dir <marts> --views-db <out> --public-base <url>`
(`build_marts.write_views_db`; #51). The views file holds no data: views over the absolute Parquet
URLs, written with `STORAGE_VERSION 'v1.0.0'`. Every view inlines `read_parquet(url)` because DuckDB
1.0 can't resolve a sibling view or macro under a client's alias. `CREATE VIEW` binds, so it reads
the *published* Parquet at build time. 1.0 clients fail with "Contents of view were altered" if
the published types later differ, so a mart schema change needs the views file regenerated after
the new marts deploy (the generator warns when the bound schema differs from the local one). Column
definitions live in `build_marts.DEFINITIONS`; a mart column without one fails the build.

Release history (#44): `extract-packages --release 3.0,3.1` (or `--all-releases`) adds past
releases' `packages/<ver>/<repo>/VIEWS` to `dim_package_version` only (`dim_package` stays the
current release), force-cached since they're immutable; VIEWS exist from 1.8 (2006), older
releases and missing repos 404 and are skipped. Every run loads `dim_release` (date + announced
software count for all releases) from the release-announcements page and sets
`dim_package.first_seen_release` to the earliest loaded release ("1.8" means 1.8 or earlier).
Past-release rows persist across runs, so one `--all-releases` run on a store is enough; the
monthly refresh then adds each new release. `mart_release_history` / `mart_release_growth`
diff consecutive loaded releases.

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
  doi.py         # DOI regex + normalisation shared by every DOI-harvesting extractor
  db.py          # DuckDB connect + schema bootstrap
  schema.sql     # canonical DDL (all spec §5 tables)
  pipeline/      # framework-free, independently runnable modules
    extract_packages.py   extract_downloads.py   build_marts.py
  cli.py         # `biocintel` dispatch
tests/           # parser unit tests (fixture-based; runnable offline)
```

Each pipeline module is runnable standalone (`python -m biocintel.pipeline.extract_packages`) and
exposes a `run()` callable the CLI and the systemd refresh unit both call.

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
   extract modules) run monthly by a systemd `--user` timer on onclappc02. Two kinds of module: *bespoke extracts* of
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
(`bridge_package_pub`, `bridge_work_grant`, `bridge_package_person`, `bridge_package_funder`) carry
provenance. People/funders (`dim_person`, `dim_funder`) come from `Authors@R`, parsed without
evaluating it (`authors.py`); funder spellings are normalized via `funder_aliases.yaml`. Marts
(`mart_package_impact`, `mart_grant_attribution`, `mart_release_growth`, `mart_package_person`,
`mart_person`, `mart_package_funder`) are derived and exported.

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
  `lake.openalex.works.title` and take the top hit (`match_method = 'title_search'`). A lake-free
  `extract-citations` step (all four repos) also harvests DOIs from package *source* on the
  `bioconductor-source` GitHub org (raw fetches of `devel/inst/CITATION` and `CITATION.cff` —
  CFF top-level/`preferred-citation` DOI only, never `references:`), falling back to the
  rendered `.../citations/<pkg>/citation.html` when `inst/CITATION` isn't on the org, as
  `match_method = 'citation_file'` (confidence 0.9); `<doi:…>` in DESCRIPTION `Description:`
  becomes `description_doi` (0.8 — it sometimes cites dependencies/related work). DOI
  harvesting + normalisation lives in `biocintel/doi.py`. CITATION files rotate (edgeR's devel
  CITATION lists only its 2025 paper), so `extract-citations` also unions the DOIs on every past
  release's rendered `packages/<ver>/<repo>/citations/<pkg>/citation.html` (3.0 → current−1,
  from `config.yaml`) as `citation_file` (0.9), with `bridge_package_pub.source_release` =
  `devel` | `release` | the newest past release listing it. Those pages are immutable, so they're
  fetched with `get_text(force_cache=True)`, which caches (404s too) even under
  `BIOCINTEL_NO_CACHE=1`; the first full run is ~88k GETs, later runs only fetch a new release.
  `--packages a,b --releases 3.16,3.19` bounds a run (only those packages' rows are replaced;
  `--releases ''` skips the pass). Every edge
  **must** carry `match_method` (`doi` | `citation_file` | `description_doi` | `title_search` |
  `manual`) and
  `confidence` so the dashboard can filter to high-confidence linkages for grant reporting.
  Scored fuzzy matching
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
