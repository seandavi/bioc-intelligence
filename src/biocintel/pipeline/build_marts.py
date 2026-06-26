"""build_marts — derive mart_* tables with DuckDB SQL and export to Parquet.

Parquet is the publishable artifact the zero-backend frontend reads (spec §2/§8).
Pub/grant columns stay 0/NULL until Phase-2 lake enrichment lands; the marts are
structurally complete now so the frontend can build against a stable shape.
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
)
SELECT p.package_name, p.repo,
       COALESCE(dl.total_downloads, 0)            AS total_downloads,
       COALESCE(dl.total_distinct_ips, 0)         AS total_distinct_ips,
       COALESCE(r.downloads_trailing_12mo, 0)     AS downloads_trailing_12mo,
       COALESCE(r.distinct_ips_trailing_12mo, 0)  AS distinct_ips_trailing_12mo,
       0  AS n_primary_pubs,           -- Phase 2 (bridge_package_pub)
       0  AS n_citing_works,           -- Phase 2 (fact_citation_edge)
       CAST(NULL AS DOUBLE) AS sum_rcr,            -- Phase 2 (dim_work.icite_rcr)
       0  AS n_distinct_grants_citing  -- Phase 3 (bridge_work_grant)
FROM dim_package p
LEFT JOIN dl     USING (package_name, repo)
LEFT JOIN recent r USING (package_name, repo);

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
"""

_MARTS = ["mart_package_impact", "mart_release_growth"]


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
