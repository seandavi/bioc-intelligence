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
WITH dl AS (
    SELECT package_name, repo,
           SUM(downloads)     AS total_downloads,
           SUM(distinct_ips)  AS total_distinct_ips
    FROM fact_download
    GROUP BY package_name, repo
),
recent AS (  -- trailing 12 months relative to the latest (year, month) present
    SELECT package_name, repo,
           SUM(downloads)    AS downloads_trailing_12mo,
           SUM(distinct_ips) AS distinct_ips_trailing_12mo
    FROM (
        SELECT *, (year * 12 + month) AS ym,
               MAX(year * 12 + month) OVER () AS max_ym
        FROM fact_download
    )
    WHERE ym > max_ym - 12
    GROUP BY package_name, repo
),
pw AS (  -- package → its linked works (the join spine for pubs/citations/grants)
    SELECT package_name, repo, work_id, role FROM bridge_package_pub
),
pubs AS (
    SELECT package_name, repo, COUNT(DISTINCT work_id) AS n_primary_pubs
    FROM pw WHERE role = 'primary' GROUP BY package_name, repo
),
rcr AS (
    SELECT pw.package_name, pw.repo, SUM(w.icite_rcr) AS sum_rcr
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
       COALESCE(pubs.n_primary_pubs, 0)           AS n_primary_pubs,
       COALESCE(citing.n_citing_works, 0)         AS n_citing_works,
       rcr.sum_rcr                                AS sum_rcr,
       COALESCE(grants.n_distinct_grants_citing, 0) AS n_distinct_grants_citing
FROM dim_package p
LEFT JOIN dl     USING (package_name, repo)
LEFT JOIN recent r USING (package_name, repo)
LEFT JOIN pubs   USING (package_name, repo)
LEFT JOIN rcr    USING (package_name, repo)
LEFT JOIN citing USING (package_name, repo)
LEFT JOIN grants USING (package_name, repo);

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
WITH gp AS (
    SELECT g.grant_id, b.package_name, b.work_id
    FROM bridge_work_grant g
    JOIN bridge_package_pub b USING (work_id)
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

-- Flat package directory for the explorer view (frontend reads this directly).
CREATE OR REPLACE TABLE mart_package_directory AS
SELECT package_name, repo, latest_release, maintainer, maintainer_email,
       title, biocviews, url, bug_reports, source_doi
FROM dim_package
ORDER BY package_name, repo;
"""

_MARTS = [
    "mart_package_impact",
    "mart_release_growth",
    "mart_grant_attribution",
    "mart_package_directory",
]


def run() -> dict[str, int]:
    MART_DIR.mkdir(parents=True, exist_ok=True)
    con = db.connect()
    db.init_schema(con)
    counts: dict[str, int] = {}
    try:
        con.execute(_MART_SQL)
        for mart in _MARTS:
            out = MART_DIR / f"{mart}.parquet"
            con.execute(f"COPY {mart} TO '{out}' (FORMAT parquet)")
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
