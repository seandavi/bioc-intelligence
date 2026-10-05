# Roadmap

Possible future work, grouped by theme. This is a backlog of ideas, not a commitment. Items marked _(built)_ exist in code but
are not yet run at scale; _(new)_ items are not started.

Current state: pipeline (packages → CITATION/DOI linkage → lake enrichment → Parquet marts) and a
6-view zero-backend dashboard, live at <https://seandavi.github.io/bioc-intelligence/> and refreshed
monthly by a systemd timer on onclappc02. See
[`bioc-intelligence-spec.md`](bioc-intelligence-spec.md) for the design and the README for caveats.

## Linkage — push past 959 packages, keep precision

- **Title-candidate → LLM judge** _(new)_ — generate title-match candidates against
  `lake.openalex.works`, store them like `fact_mention_candidate`, and have a multidimensional LLM
  judge confirm each against the package's description/abstract. Salvages the long tail without the
  false-positive flood that killed naive title matching (see README caveats). Confidence stays below
  DOI/CITATION; never auto-promoted for grant reporting.
- **CITATION extraction for the other three repos** _(done)_ — `extract_citation_files` reads
  `inst/CITATION` + `CITATION.cff` from the `bioconductor-source` org for all four repos (#20).
- **iCite DOI→PMID fallback** _(done, #24)_ — bridge DOIs missing from `openalex.works.doi` but in
  `icite.metadata` (e.g. Rbowtie, specL, twoddpcr) get a `dim_work` row built from iCite.
- **Human-curated override table** _(new)_ — `match_method='manual'` for authoritative corrections.
- **Crossref fuzzy fallback** _(new, deferred from spec §6)_ — scored title/author/year matching for
  packages with neither a DOI nor a CITATION.

## Enrichment depth

- **Cited-by edges at scale** _(built — `enrich_from_lake --steps citations`)_ — run the 1.29B-row
  `openalex.work_references` scan to populate `fact_citation_edge`, lighting up the "citing works"
  surfaces. Currently opt-in to respect R2 egress.
- **Full-text mention mining + judge** _(built — `mine_mentions`, `judge_mentions`)_ — run FTS over
  the ~974M `pmc.passages` to recover informal package usage, then the LLM judge; promote confirmed
  mentions to `fact_citation_edge (mention_type='fulltext')`. Wire a real (Anthropic) judge.
- **Maintainer → ROR** _(new, spec §3)_ — best-effort institution attribution.

## Download stats — unblock the usage proxy

- **Locate the relocated stats endpoint** _(resolved)_ — the `*_pkg_stats.tab` files 404'd after the
  BioC 3.23 redesign but are back at the original paths (2009–2026 history, verified 2026-10-01).
  `extract-downloads` runs in the monthly refresh (first loaded 2026-10-01).

## Versioning & growth

- **Version history from git tags** _(new)_ — backfill per-package history from
  `git.bioconductor.org` tags → `first_seen_release`, `n_new_packages`, `net_downloads`, and real
  release-over-release growth (currently a single-release snapshot).
- **Dated Parquet snapshots in R2** _(new, spec §2)_ — point-in-time marts + a snapshot selector in
  the UI (swap mart URLs, zero backend).

## Frontend

- **Cross-view navigation** _(new)_ — click a biocViews term → Explorer filtered; a grant → its
  packages; a package → its papers/citations/grants.
- **Download-trends view** _(new, unblocked)_ — distinct-IP time series with a methodology-era band
  (spec §6); the stats endpoints are back.
- **biocViews treemap / hierarchy** _(new)_ — the true hierarchical taxonomy, not the flat term list.
- **"Cite this impact" deep-links** _(new)_ — stable per-package/grant permalinks + copyable figures
  for grant narratives (the headline use case). Likely needs `react-router`.
- **Confidence-aware linkage UI** _(new)_ — filter to DOI/CITATION-only vs including title_search;
  surface `match_method` as a badge so grant reports show only defensible links.
- **Name-collision auditor** _(new)_ — a review view over mention candidates (accept/reject) that
  doubles as judge-training UI.

## Ops & infrastructure

- **Scheduled orchestration** _(partly built, spec §7)_ — the monthly refresh (extract → enrich →
  marts → commit → Deploy Pages) runs as a systemd `--user` timer on onclappc02, not GitHub Actions,
  whose runner couldn't reach the lake Postgres. Still open: an on-release trigger for dimensions
  and the judge on its own cadence.
- **Serve marts from R2** _(new)_ — decouple marts from git, enabling snapshots and larger data.
- **Integration tests** _(new)_ — against a small local-backend lake fixture; frontend e2e once a
  usable headless browser is available in CI.

## Upstream / data contract (cdsci-lake)

- **Versioned consumer views** _(new)_ — pin to `icite.v_rcr`, etc. as they land, instead of raw
  table columns.
- **Contribute the publink finding** _(new)_ — `reporter.publink.project_number` joins
  `reporter.projects.core_project_num` (not `project_num`); worth a versioned-view alias upstream.
