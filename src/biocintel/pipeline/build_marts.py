"""build_marts — derive mart_* tables with DuckDB SQL and export to Parquet.

Parquet is the publishable artifact the zero-backend frontend reads (spec §2/§8).
Reads the local store only (no lake), so it runs anywhere. Columns sourced from
Phase-2 enrichment (pubs, RCR, grants) are 0/NULL until that enrichment has run;
the mart *shape* is stable regardless, so the frontend can build against it now.
"""

from __future__ import annotations

import argparse

from .. import db
from ..config import MART_DIR

# Downloads are usage-proxied by DISTINCT IPS (spec §6); raw downloads kept too.
_MART_SQL = """
CREATE OR REPLACE TABLE mart_package_impact AS
WITH fd AS (  -- fact_download is append-only per snapshot: read each repo's latest
    SELECT * FROM fact_download
    QUALIFY _snapshot = MAX(_snapshot) OVER (PARTITION BY repo)
),
dl AS (
    SELECT package_name, repo,
           SUM(downloads)     AS total_downloads,
           SUM(distinct_ips)  AS total_distinct_ips
    FROM fd
    GROUP BY package_name, repo
),
recent AS (  -- trailing 12 months relative to the latest (year, month) present,
             -- plus the 12 months before that (for year-over-year change)
    SELECT package_name, repo,
           SUM(downloads)    FILTER (WHERE ym > max_ym - 12)  AS downloads_trailing_12mo,
           SUM(distinct_ips) FILTER (WHERE ym > max_ym - 12)  AS distinct_ips_trailing_12mo,
           SUM(distinct_ips) FILTER (WHERE ym <= max_ym - 12) AS distinct_ips_prior_12mo
    FROM (
        SELECT *, (year * 12 + month) AS ym,
               MAX(year * 12 + month) OVER () AS max_ym
        FROM fd
    )
    WHERE ym > max_ym - 24
    GROUP BY package_name, repo
),
pw AS (  -- package → its linked works, canonicalized to dim_work's work_id so a
         -- DOI-keyed bridge row lines up with the PMID-keyed enriched work.
    SELECT b.package_name, b.repo,
           COALESCE(w.work_id, b.work_id) AS work_id, b.role
    FROM bridge_package_pub b
    LEFT JOIN dim_work w
      ON b.work_id = w.work_id OR b.work_id = w.doi OR b.work_id = w.pmid
),
pubs AS (
    SELECT package_name, repo, COUNT(DISTINCT work_id) AS n_primary_pubs
    FROM pw WHERE role = 'primary' GROUP BY package_name, repo
),
wm AS (  -- RCR is a normalized *rate* → median, not sum. Citations are counts → sum.
    SELECT pw.package_name, pw.repo,
           median(w.icite_rcr)     AS median_rcr,
           SUM(w.citation_count)   AS total_citations
    FROM pw JOIN dim_work w USING (work_id) GROUP BY pw.package_name, pw.repo
),
citing AS (
    SELECT pw.package_name, pw.repo, COUNT(DISTINCT e.citing_work_id) AS n_citing_works
    FROM pw JOIN fact_citation_edge e ON e.cited_work_id = pw.work_id
    GROUP BY pw.package_name, pw.repo
),
grants AS (
    SELECT pw.package_name, pw.repo, COUNT(DISTINCT g.grant_id) AS n_distinct_grants_citing
    FROM pw JOIN bridge_work_grant g USING (work_id)
    GROUP BY pw.package_name, pw.repo
)
SELECT p.package_name, p.repo,
       COALESCE(dl.total_downloads, 0)            AS total_downloads,
       COALESCE(dl.total_distinct_ips, 0)         AS total_distinct_ips,
       COALESCE(r.downloads_trailing_12mo, 0)     AS downloads_trailing_12mo,
       COALESCE(r.distinct_ips_trailing_12mo, 0)  AS distinct_ips_trailing_12mo,
       COALESCE(r.distinct_ips_prior_12mo, 0)     AS distinct_ips_prior_12mo,
       rank() OVER (PARTITION BY p.repo
                    ORDER BY COALESCE(r.distinct_ips_trailing_12mo, 0) DESC)
                                                  AS usage_rank_in_repo,
       COALESCE(pubs.n_primary_pubs, 0)           AS n_primary_pubs,
       COALESCE(wm.total_citations, 0)            AS total_citations,
       COALESCE(citing.n_citing_works, 0)         AS n_citing_works,
       wm.median_rcr                              AS median_rcr,
       COALESCE(grants.n_distinct_grants_citing, 0) AS n_distinct_grants_citing
FROM dim_package p
LEFT JOIN dl     USING (package_name, repo)
LEFT JOIN recent r USING (package_name, repo)
LEFT JOIN pubs   USING (package_name, repo)
LEFT JOIN wm     USING (package_name, repo)
LEFT JOIN citing USING (package_name, repo)
LEFT JOIN grants USING (package_name, repo);

-- Ecosystem download series per year. Eras are separate rows (never silently concatenated);
-- the methodology boundary falls inside 2015, so that year has one row per era.
CREATE OR REPLACE TABLE mart_ecosystem_downloads_yearly AS
WITH fd AS (
    SELECT * FROM fact_download
    QUALIFY _snapshot = MAX(_snapshot) OVER (PARTITION BY repo)
)
SELECT year, repo, methodology_era,
       SUM(distinct_ips) AS distinct_ips,
       SUM(downloads)    AS downloads,
       COUNT(DISTINCT package_name) FILTER (WHERE downloads > 0) AS n_packages_with_downloads
FROM fd
GROUP BY year, repo, methodology_era
ORDER BY repo, year, methodology_era;

-- Per-package monthly series. Sorted so each package sits in a few row groups
-- (exported with a small ROW_GROUP_SIZE) and the browser can range-read one package.
CREATE OR REPLACE TABLE mart_package_downloads_monthly AS
WITH fd AS (
    SELECT * FROM fact_download
    QUALIFY _snapshot = MAX(_snapshot) OVER (PARTITION BY repo)
)
SELECT package_name, repo, year, month, distinct_ips, downloads, methodology_era
FROM fd
ORDER BY package_name, repo, year, month;

CREATE OR REPLACE TABLE mart_release_growth AS
SELECT bioc_release,
       COUNT(DISTINCT package_name) AS n_packages,
       COUNT(DISTINCT package_name) FILTER (WHERE first_seen = bioc_release)
                                    AS n_new_packages,  -- 0 until version history lands
       CAST(NULL AS BIGINT) AS net_downloads  -- needs release-windowed downloads
FROM (
    SELECT v.package_name, v.bioc_release, p.first_seen_release AS first_seen
    FROM dim_package_version v
    LEFT JOIN dim_package p USING (package_name, repo)
    WHERE NOT v.in_devel
)
GROUP BY bioc_release
ORDER BY bioc_release;

-- Grant-attribution narrative (the grant-submission use case, spec §8).
CREATE OR REPLACE TABLE mart_grant_attribution AS
WITH pkg_work AS (  -- canonicalize package→work ids (same DOI/PMID reconciliation)
    SELECT b.package_name, COALESCE(w.work_id, b.work_id) AS work_id
    FROM bridge_package_pub b
    LEFT JOIN dim_work w
      ON b.work_id = w.work_id OR b.work_id = w.doi OR b.work_id = w.pmid
),
gp AS (
    SELECT g.grant_id, pk.package_name, g.work_id
    FROM bridge_work_grant g
    JOIN pkg_work pk USING (work_id)
)
SELECT gp.grant_id,
       d.agency,
       d.title,
       COUNT(DISTINCT gp.package_name)    AS n_packages_supported,
       COUNT(DISTINCT e.citing_work_id)   AS n_citing_works,
       LIST(DISTINCT gp.package_name)     AS package_names
FROM gp
LEFT JOIN dim_grant d USING (grant_id)
LEFT JOIN fact_citation_edge e ON e.cited_work_id = gp.work_id
GROUP BY gp.grant_id, d.agency, d.title
ORDER BY n_packages_supported DESC, gp.grant_id;

-- Linked works (one row per describing/companion publication) — powers
-- ecosystem-level citation stats and the citations-by-year plot.
CREATE OR REPLACE TABLE mart_work AS
SELECT work_id, pmid, doi, title, year, journal, icite_rcr, citation_count
FROM dim_work;

-- Package → linked works (one row per package × work), for the explorer's papers list.
-- Same DOI/PMID reconciliation as `pw`; a pair reached by several match methods keeps
-- its highest-confidence edge. Works not yet in dim_work keep a row with NULL metadata.
CREATE OR REPLACE TABLE mart_package_work AS
SELECT b.package_name, b.repo,
       COALESCE(w.work_id, b.work_id)                          AS work_id,
       COALESCE(w.doi, CASE WHEN b.work_id LIKE '10.%' THEN b.work_id END) AS doi,
       w.pmid, w.title, w.year, w.journal, w.citation_count, w.icite_rcr,
       b.match_method, b.confidence, b.role
FROM bridge_package_pub b
LEFT JOIN dim_work w
  ON b.work_id = w.work_id OR b.work_id = w.doi OR b.work_id = w.pmid
QUALIFY row_number() OVER (
    PARTITION BY b.package_name, b.repo, COALESCE(w.work_id, b.work_id)
    ORDER BY b.confidence DESC NULLS LAST, b.match_method
) = 1
ORDER BY b.package_name, b.repo, b.confidence DESC, w.year DESC NULLS LAST;

-- Flat package directory for the explorer view (frontend reads this directly).
CREATE OR REPLACE TABLE mart_package_directory AS
SELECT package_name, repo, latest_release, maintainer,  -- no maintainer_email (#33)
       title, description, biocviews, url, bug_reports, source_doi
FROM dim_package
ORDER BY package_name, repo;

-- People per package (roles as declared in Authors@R; no emails are stored upstream).
CREATE OR REPLACE TABLE mart_package_person AS
SELECT bp.package_name, bp.repo, bp.person_id, p.name, p.orcid, bp.roles,
       list_contains(bp.roles, 'cre') AS is_maintainer,
       bp.source
FROM bridge_package_person bp
JOIN dim_person p USING (person_id)
ORDER BY bp.package_name, bp.repo, is_maintainer DESC, p.name;

-- Packages per person: maintainer / author counts for "developers with more than N packages".
CREATE OR REPLACE TABLE mart_person AS
SELECT p.person_id, p.name, p.orcid,
       COUNT(*)                                              AS n_packages,
       COUNT(*) FILTER (WHERE list_contains(bp.roles, 'cre')) AS n_maintained,
       COUNT(*) FILTER (WHERE list_contains(bp.roles, 'aut')) AS n_authored,
       LIST(bp.package_name ORDER BY bp.package_name)        AS package_names
FROM bridge_package_person bp
JOIN dim_person p USING (person_id)
GROUP BY p.person_id, p.name, p.orcid
ORDER BY n_packages DESC, p.name;

-- Declared funders per package (the `fnd` role). grant_id is set when the declared NIH
-- grant number matches a RePORTER core project already in dim_grant.
CREATE OR REPLACE TABLE mart_package_funder AS
SELECT bf.package_name, bf.repo, bf.funder_id, f.name AS funder_name, f.curated,
       bf.declared_name, bf.grant_number, g.grant_id
FROM bridge_package_funder bf
JOIN dim_funder f USING (funder_id)
LEFT JOIN dim_grant g ON g.grant_id = bf.grant_number
ORDER BY bf.package_name, bf.repo, f.name;
"""

_MARTS = [
    "mart_package_impact",
    "mart_release_growth",
    "mart_grant_attribution",
    "mart_package_directory",
    "mart_work",
    "mart_package_work",
    "mart_package_person",
    "mart_person",
    "mart_package_funder",
    "mart_ecosystem_downloads_yearly",
    "mart_package_downloads_monthly",
]

# Small row groups let DuckDB-WASM range-read one package from the sorted monthly mart.
_ROW_GROUP_SIZE = {"mart_package_downloads_monthly": 2048}


def run() -> dict[str, int]:
    MART_DIR.mkdir(parents=True, exist_ok=True)
    con = db.connect()
    db.init_schema(con)
    counts: dict[str, int] = {}
    try:
        con.execute(_MART_SQL)
        for mart in _MARTS:
            out = MART_DIR / f"{mart}.parquet"
            opts = f", ROW_GROUP_SIZE {_ROW_GROUP_SIZE[mart]}" if mart in _ROW_GROUP_SIZE else ""
            con.execute(f"COPY {mart} TO '{out}' (FORMAT parquet{opts})")
            n = con.execute(f"SELECT count(*) FROM {mart}").fetchone()[0]
            counts[mart] = n
            print(f"  {mart}: {n} rows -> {out}")
    finally:
        con.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description="Build mart_* tables and export Parquet.").parse_args(argv)
    print("build_marts:")
    run()


if __name__ == "__main__":
    main()
