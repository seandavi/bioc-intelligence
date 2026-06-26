# bioc-intelligence

Research-intelligence and impact-analytics platform for the **Bioconductor**
ecosystem — package releases, downloads, publications, citations, and grant
linkages, for grant-impact evidence, a public dashboard, and metaresearch.

See [`bioc-intelligence-spec.md`](bioc-intelligence-spec.md) for the architecture
and [`CLAUDE.md`](CLAUDE.md) for orientation. Frontend ideas live in
[`docs/frontend-spec.md`](docs/frontend-spec.md).

## Architecture in one breath

Framework-free extract modules write into a single canonical **DuckDB** file;
`build_marts` exports **Parquet** marts that a zero-backend SPA reads directly.
Shared enrichment corpora (OpenAlex, iCite, RePORTER, PMC full text) are read
**read-only from the sibling [`cdsci-lake`](../cdsci-lake)** DuckLake — not
re-fetched from APIs. The local store stays a plain file; the lake is a
build-time input.

## Quickstart

```bash
uv venv && uv pip install -e '.[dev]'

uv run biocintel init-db                    # create the DuckDB store + schema
uv run biocintel extract-packages           # VIEWS -> dim_package(_version), all 4 repos
uv run biocintel extract-downloads          # stats tabs -> fact_download (see note)
uv run biocintel build-marts                # derive mart_* -> data/marts/*.parquet
uv run biocintel all                        # the three above, in order

uv run pytest                               # parser/unit tests
uv run ruff check src tests                 # lint
```

The DuckDB file and Parquet marts are written under `data/` (gitignored) and are
rebuildable from the commands above.

## Status

**Phase 1 (MVP) — packages × versions × downloads.** Package extraction is live
and verified against `bioconductor.org`. Download extraction is implemented and
unit-tested, but the Bioconductor stats `.tab` endpoints currently 404 site-wide
(BioC 3.23 site redesign); the extractor logs-and-skips per `BiocPkgTools`
convention until they return. Phases 2–4 (lake enrichment, grants, mention
mining) are designed in the spec and stubbed for wiring next.
