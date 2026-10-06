"""enrich_from_lake — fill dim_work, fact_citation_edge, dim_grant/bridge_work_grant.

All cross-catalog SQL against the read-only lake (spec §4/§7). Driven by the set
of *primary works* already linked in ``bridge_package_pub`` (run ``link_works``
first). Steps:

- **works**  — linked OpenAlex works + iCite RCR → ``dim_work`` (cheap; scans the
  114M ``works`` once to materialize a small ``linked`` temp table).
- **grants** — ``reporter.publink``→``reporter.projects`` for those works'
  PMIDs → ``dim_grant`` + ``bridge_work_grant``.
- **institutions** — author affiliations of every ``dim_work`` row with an
  OpenAlex id, from ``openalex.works_authorships`` + ``openalex.institutions`` →
  ``dim_institution`` + ``bridge_work_institution``. Best-effort (spec §3): a
  failure is logged and the run continues.
- **citations** — cited-by edges from ``openalex.work_references`` →
  ``fact_citation_edge``. **Heavy**: scans the 1.29B-row references table plus a
  second ``works`` pass for citing-side metadata, so it is **opt-in** (not in the
  default step set) to respect R2 egress. Run it deliberately for a full refresh.

Idempotent per step (scoped deletes / INSERT OR REPLACE), keyed to the linked works.
"""

from __future__ import annotations

import argparse

import duckdb

from ..lake import connect_with_lake

DEFAULT_STEPS = ("works", "institutions", "grants")
ALL_STEPS = ("works", "institutions", "grants", "citations")

# Small driver table: the OpenAlex works linked to packages, with spine work_id.
_LINKED_SQL = """
CREATE OR REPLACE TEMP TABLE linked AS
SELECT DISTINCT
    w.id AS oa_id, w.pmid, w.doi,
    COALESCE(CAST(w.pmid AS VARCHAR), w.doi) AS work_id,
    w.title, w.publication_year AS year, w.source_name AS journal, w.cited_by_count
FROM lake.openalex.works w
-- A bridge work_id is PMID-or-DOI; match EITHER side (a citation link stores the
-- DOI even when the work also has a PMID, so a single COALESCE key would miss it).
JOIN bi.bridge_package_pub b
  ON b.work_id = CAST(w.pmid AS VARCHAR) OR b.work_id = w.doi;
"""

# iCite fallback (#24): bridge DOIs absent from openalex.works.doi but present in
# icite.metadata (it carries a DOI + PMID). These get a dim_work row built from iCite
# alone: oa_id is NULL, so the citations step (keyed on OpenAlex ids) skips them,
# while grants still resolve through the PMID. citation_count is iCite's count here
# (OpenAlex's for the main branch) — the only count available for these works.
# One scan of the ~40M-row iCite table via IN-subqueries (semi-joins), not
# `JOIN … ON a OR b`, which degrades to a nested loop.
_LINKED_ICITE_SQL = """
INSERT INTO linked
SELECT DISTINCT
    NULL AS oa_id, ic.pmid, ic.doi,
    COALESCE(CAST(ic.pmid AS VARCHAR), ic.doi) AS work_id,
    ic.title, ic.year, ic.journal, ic.citation_count
FROM lake.icite.metadata ic
WHERE (ic.doi IN (SELECT work_id FROM bi.bridge_package_pub)
       OR CAST(ic.pmid AS VARCHAR) IN (SELECT work_id FROM bi.bridge_package_pub))
  AND NOT EXISTS (SELECT 1 FROM linked l WHERE l.pmid = ic.pmid)
  AND NOT EXISTS (SELECT 1 FROM linked l WHERE l.doi = ic.doi);
"""

_WORKS_SQL = """
INSERT OR REPLACE INTO bi.dim_work
SELECT l.work_id, CAST(l.pmid AS VARCHAR), l.doi, l.oa_id,
       l.title, l.year, l.journal, ic.rcr, l.cited_by_count, current_date
FROM linked l
LEFT JOIN lake.icite.metadata ic ON ic.pmid = l.pmid;
"""

# NOTE (contract): reporter.publink.project_number is a *core* project number —
# it joins reporter.projects.core_project_num, NOT project_num. Verified against
# the lake; worth a versioned-view alias upstream.
_GRANT_DIM_SQL = """
INSERT OR REPLACE INTO bi.dim_grant (grant_id, agency, project_num, fy, title)
SELECT grant_id, agency, project_num, fy, title FROM (
    SELECT pr.core_project_num AS grant_id, pr.admin_ic AS agency,
           pr.project_num AS project_num, pr.fiscal_year AS fy, pr.project_title AS title,
           row_number() OVER (PARTITION BY pr.core_project_num ORDER BY pr.fiscal_year DESC) rn
    FROM linked l
    JOIN lake.reporter.publink pl ON pl.pmid = l.pmid
    JOIN lake.reporter.projects pr ON pr.core_project_num = pl.project_number
    WHERE pr.core_project_num IS NOT NULL
) WHERE rn = 1;
"""

_GRANT_BRIDGE_SQL = """
INSERT INTO bi.bridge_work_grant (work_id, grant_id, source)
SELECT DISTINCT l.work_id, pl.project_number, 'reporter'
FROM linked l
JOIN lake.reporter.publink pl ON pl.pmid = l.pmid
WHERE pl.project_number IS NOT NULL;
"""

_CITATION_SQL = """
INSERT INTO bi.fact_citation_edge (cited_work_id, citing_work_id, source, mention_type, _snapshot)
SELECT l.work_id AS cited_work_id,
       COALESCE(CAST(citing.pmid AS VARCHAR), citing.doi) AS citing_work_id,
       'openalex', 'formal', current_date
FROM linked l
JOIN lake.openalex.work_references wr ON wr.referenced_work_id = l.oa_id
JOIN lake.openalex.works citing ON citing.id = wr.work_id;
"""


# Affiliations of every enriched work (not just this run's `linked`), rebuilt whole.
# The ~200s scan is the authorships join; institutions is small and keyed by the
# authorship's institution_id. Duplicate author rows (two middle authors at one
# institution) collapse under DISTINCT.
_WORK_INSTITUTION_SQL = """
CREATE OR REPLACE TEMP TABLE work_institution AS
SELECT DISTINCT w.work_id, wa.institution_id, wa.institution_ror AS ror,
       wa.institution_country, wa.author_position, wa.is_corresponding
FROM bi.dim_work w
JOIN lake.openalex.works_authorships wa ON wa.work_id = w.openalex_id
WHERE wa.institution_ror IS NOT NULL;
"""

_INSTITUTION_DIM_SQL = """
INSERT INTO bi.dim_institution
SELECT ror, openalex_id, name, country_code, country, type, city, region, latitude, longitude
FROM (
    SELECT wi.ror, wi.institution_id AS openalex_id, i.display_name AS name,
           COALESCE(i.country_code, wi.institution_country) AS country_code,
           i.country, i.type, i.city, i.region, i.latitude, i.longitude
    FROM work_institution wi
    LEFT JOIN lake.openalex.institutions i ON i.id = wi.institution_id
)
QUALIFY row_number() OVER (PARTITION BY ror ORDER BY name NULLS LAST, openalex_id) = 1;
"""

_INSTITUTION_BRIDGE_SQL = """
INSERT INTO bi.bridge_work_institution
SELECT DISTINCT work_id, ror, author_position, is_corresponding, 'openalex'
FROM work_institution;
"""


def _enrich_works(con: duckdb.DuckDBPyConnection) -> int:
    con.execute(_WORKS_SQL)
    return con.execute("SELECT count(*) FROM bi.dim_work").fetchone()[0]


def _enrich_grants(con: duckdb.DuckDBPyConnection) -> int:
    con.execute(
        "DELETE FROM bi.bridge_work_grant WHERE source = 'reporter' "
        "AND work_id IN (SELECT work_id FROM linked)"
    )
    con.execute(_GRANT_DIM_SQL)
    con.execute(_GRANT_BRIDGE_SQL)
    return con.execute(
        "SELECT count(*) FROM bi.bridge_work_grant WHERE source='reporter'"
    ).fetchone()[0]


def _enrich_institutions(con: duckdb.DuckDBPyConnection) -> int:
    con.execute(_WORK_INSTITUTION_SQL)
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM bi.bridge_work_institution")
        con.execute("DELETE FROM bi.dim_institution")
        con.execute(_INSTITUTION_DIM_SQL)
        con.execute(_INSTITUTION_BRIDGE_SQL)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return con.execute("SELECT count(*) FROM bi.dim_institution").fetchone()[0]


def _enrich_citations(con: duckdb.DuckDBPyConnection) -> int:
    con.execute(
        "DELETE FROM bi.fact_citation_edge WHERE source='openalex' AND mention_type='formal' "
        "AND cited_work_id IN (SELECT work_id FROM linked)"
    )
    con.execute(_CITATION_SQL)
    return con.execute(
        "SELECT count(*) FROM bi.fact_citation_edge WHERE source='openalex'"
    ).fetchone()[0]


def run(steps: tuple[str, ...] = DEFAULT_STEPS) -> dict[str, int]:
    con = connect_with_lake()
    counts: dict[str, int] = {}
    try:
        con.execute(_LINKED_SQL)
        n_oa = con.execute("SELECT count(*) FROM linked").fetchone()[0]
        con.execute(_LINKED_ICITE_SQL)
        n_linked = con.execute("SELECT count(*) FROM linked").fetchone()[0]
        print(f"  linked primary works: {n_linked} ({n_linked - n_oa} via iCite fallback)")
        if "works" in steps:
            counts["dim_work"] = _enrich_works(con)
            print(f"  dim_work: {counts['dim_work']}")
        if "institutions" in steps:
            # Best-effort (spec §3): never fail the refresh on affiliations.
            try:
                counts["dim_institution"] = _enrich_institutions(con)
                print(f"  dim_institution: {counts['dim_institution']}")
            except duckdb.Error as exc:
                print(f"  institutions: skipped ({exc})")
        if "grants" in steps:
            counts["bridge_work_grant"] = _enrich_grants(con)
            print(f"  bridge_work_grant (reporter): {counts['bridge_work_grant']}")
        if "citations" in steps:
            print("  citations: scanning work_references (1.29B rows) — this is the heavy step…")
            counts["fact_citation_edge"] = _enrich_citations(con)
            print(f"  fact_citation_edge (openalex): {counts['fact_citation_edge']}")
    finally:
        con.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Enrich works/grants/citations from the lake.")
    ap.add_argument(
        "--steps", default=",".join(DEFAULT_STEPS),
        help=f"comma-separated subset of {ALL_STEPS} (default: {','.join(DEFAULT_STEPS)}; "
             "'citations' is the heavy 1.29B-row scan, opt-in)",
    )
    args = ap.parse_args(argv)
    steps = tuple(s.strip() for s in args.steps.split(",") if s.strip())
    bad = set(steps) - set(ALL_STEPS)
    if bad:
        ap.error(f"unknown steps: {sorted(bad)}; valid: {ALL_STEPS}")
    print("enrich_from_lake:")
    run(steps)


if __name__ == "__main__":
    main()
