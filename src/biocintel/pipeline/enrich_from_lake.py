"""enrich_from_lake — fill dim_work, fact_citation_edge, dim_grant/bridge_work_grant.

All cross-catalog SQL against the read-only lake (spec §4/§7). Driven by the set
of *primary works* already linked in ``bridge_package_pub`` (run ``link_works``
first). Steps:

- **works**  — linked OpenAlex works + iCite RCR → ``dim_work`` (cheap; scans the
  114M ``works`` once to materialize a small ``linked`` temp table).
- **grants** — ``reporter.publink``→``reporter.projects`` for those works'
  PMIDs → ``dim_grant`` + ``bridge_work_grant``.
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

DEFAULT_STEPS = ("works", "grants")
ALL_STEPS = ("works", "grants", "citations")

# Small driver table: the OpenAlex works linked to packages, with spine work_id.
_LINKED_SQL = """
CREATE OR REPLACE TEMP TABLE linked AS
SELECT DISTINCT
    w.id AS oa_id, w.pmid, w.doi,
    COALESCE(CAST(w.pmid AS VARCHAR), w.doi) AS work_id,
    w.title, w.publication_year AS year, w.source_name AS journal, w.cited_by_count
FROM lake.openalex.works w
JOIN bi.bridge_package_pub b
  ON b.work_id = COALESCE(CAST(w.pmid AS VARCHAR), w.doi);
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
        n_linked = con.execute("SELECT count(*) FROM linked").fetchone()[0]
        print(f"  linked primary works: {n_linked}")
        if "works" in steps:
            counts["dim_work"] = _enrich_works(con)
            print(f"  dim_work: {counts['dim_work']}")
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
