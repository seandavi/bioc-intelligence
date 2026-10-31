"""build_marts — derive mart_* tables with DuckDB SQL and export to Parquet.

Parquet is the publishable artifact the zero-backend frontend reads (spec §2/§8).
Reads the local store only (no lake), so it runs anywhere. Columns sourced from
Phase-2 enrichment (pubs, RCR, grants) are 0/NULL until that enrichment has run;
the mart *shape* is stable regardless, so the frontend can build against it now.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import duckdb

from .. import db, regions
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
    SELECT DISTINCT b.package_name, b.repo,
           COALESCE(w.work_id, b.work_id) AS work_id, b.role
    FROM bridge_package_pub b
    LEFT JOIN dim_work w
      ON b.work_id = w.work_id OR b.work_id = w.doi OR b.work_id = w.pmid
      OR list_contains(w.alias_dois, b.work_id)
),
pubs AS (
    SELECT package_name, repo, COUNT(DISTINCT work_id) AS n_primary_pubs
    FROM pw WHERE role = 'primary' GROUP BY package_name, repo
),
impact_work AS (  -- one row per (package, work): the sums and medians below must weigh each
               -- work once, however many bridge rows or roles point at it.
    SELECT DISTINCT package_name, repo, work_id FROM pw
),
wm AS (  -- RCR is a normalized *rate* → median, not sum. Citations are counts → sum.
    SELECT pk.package_name, pk.repo,
           median(w.icite_rcr)     AS median_rcr,
           SUM(w.citation_count)   AS total_citations
    FROM impact_work pk JOIN dim_work w USING (work_id) GROUP BY pk.package_name, pk.repo
),
citing AS (
    SELECT pk.package_name, pk.repo, COUNT(DISTINCT e.citing_work_id) AS n_citing_works
    FROM impact_work pk JOIN fact_citation_edge e ON e.cited_work_id = pk.work_id
    GROUP BY pk.package_name, pk.repo
),
grants AS (
    SELECT pk.package_name, pk.repo, COUNT(DISTINCT g.grant_id) AS n_distinct_grants_citing
    FROM impact_work pk JOIN bridge_work_grant g USING (work_id)
    GROUP BY pk.package_name, pk.repo
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
-- sum_package_distinct_ips is a SUM over packages (one address installing 50 packages
-- counts 50 times): a volume measure, never a count of users. The project-level count
-- is the installer proxy below (#80).
SELECT year, repo, methodology_era,
       SUM(distinct_ips) AS sum_package_distinct_ips,
       SUM(downloads)    AS downloads,
       COUNT(DISTINCT package_name) FILTER (WHERE downloads > 0) AS n_packages_with_downloads
FROM fd
GROUP BY year, repo, methodology_era
ORDER BY repo, year, methodology_era;

-- Project-level installs: distinct IPs of the installer package, the convention Bioconductor
-- uses for "how many machines installed Bioconductor". BiocInstaller carried it 2011-2018,
-- BiocVersion (installed by the CRAN package BiocManager) since 2018; in overlap months the
-- larger of the two is taken. One row per month across both eras.
CREATE OR REPLACE TABLE mart_installer_downloads_monthly AS
WITH fd AS (
    SELECT * FROM fact_download
    WHERE repo = 'bioc' AND package_name IN ('BiocInstaller', 'BiocVersion')
    QUALIFY _snapshot = MAX(_snapshot) OVER (PARTITION BY repo)
)
SELECT year, month, methodology_era,
       arg_max(package_name, distinct_ips) AS installer_package,
       MAX(distinct_ips) AS installer_distinct_ips,
       MAX(downloads)    AS installer_downloads
FROM fd
GROUP BY year, month, methodology_era
ORDER BY year, month;

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

-- Release-over-release diffs from each release's VIEWS (dim_package_version, 1.8+), per
-- repo and for all repos together (repo '*', where a package is one name across repos).
-- Releases sort numerically (3.9 < 3.10). The earliest loaded release has no predecessor,
-- so its new/removed are NULL rather than "everything is new"; a repo's first release
-- after that (workflows) counts all its packages as new. Removed = in the repo's previous
-- loaded release, absent from this one.
CREATE OR REPLACE TEMP TABLE _release_diff AS
WITH pv AS (
    SELECT DISTINCT package_name, repo, bioc_release,
           string_split(bioc_release, '.')::INT[] AS rk
    FROM dim_package_version WHERE NOT in_devel
    UNION
    SELECT DISTINCT package_name, '*', bioc_release, string_split(bioc_release, '.')::INT[]
    FROM dim_package_version WHERE NOT in_devel
),
first_seen AS (
    SELECT package_name, repo, min(rk) AS first_rk FROM pv GROUP BY package_name, repo
),
rel AS (
    SELECT repo, bioc_release, rk, lag(rk) OVER (PARTITION BY repo ORDER BY rk) AS prev_rk
    FROM (SELECT DISTINCT repo, bioc_release, rk FROM pv)
),
cur AS (
    SELECT r.repo, r.bioc_release, r.rk, r.prev_rk,
           count(*)                                  AS n_packages,
           count(*) FILTER (WHERE f.first_rk = r.rk) AS n_new
    FROM rel r
    JOIN pv USING (repo, bioc_release)
    JOIN first_seen f USING (package_name, repo)
    GROUP BY r.repo, r.bioc_release, r.rk, r.prev_rk
),
removed AS (
    SELECT r.repo, r.bioc_release, count(*) AS n_removed
    FROM rel r
    JOIN pv prev ON prev.repo = r.repo AND prev.rk = r.prev_rk
    ANTI JOIN pv c ON c.repo = r.repo AND c.rk = r.rk AND c.package_name = prev.package_name
    GROUP BY r.repo, r.bioc_release
)
SELECT c.bioc_release, c.repo, c.rk, c.n_packages,
       CASE WHEN c.rk > min(c.rk) OVER () THEN c.n_new END                    AS n_new,
       CASE WHEN c.rk > min(c.rk) OVER () THEN COALESCE(x.n_removed, 0) END   AS n_removed
FROM cur c LEFT JOIN removed x USING (repo, bioc_release);

CREATE OR REPLACE TABLE mart_release_history AS
SELECT d.bioc_release, r.release_date, d.repo, d.n_packages, d.n_new, d.n_removed
FROM _release_diff d
LEFT JOIN dim_release r USING (bioc_release)
WHERE d.repo <> '*'
ORDER BY d.rk, d.repo;

-- One row per announced release (1.0 onwards) plus any loaded release not announced.
-- Releases before VIEWS (1.0-1.7) carry only n_software_announced (bioc repo only).
CREATE OR REPLACE TABLE mart_release_growth AS
SELECT bioc_release, r.release_date, r.n_software_announced,
       d.n_packages, d.n_new AS n_new_packages, d.n_removed,
       CAST(NULL AS BIGINT) AS net_downloads  -- needs release-windowed downloads
FROM dim_release r
FULL JOIN (SELECT * FROM _release_diff WHERE repo = '*') d USING (bioc_release)
ORDER BY string_split(bioc_release, '.')::INT[];

-- Grant-attribution narrative (the grant-submission use case, spec §8).
CREATE OR REPLACE TABLE mart_grant_attribution AS
WITH pkg_work AS (  -- canonicalize package→work ids (same DOI/PMID reconciliation)
    SELECT b.package_name, COALESCE(w.work_id, b.work_id) AS work_id
    FROM bridge_package_pub b
    LEFT JOIN dim_work w
      ON b.work_id = w.work_id OR b.work_id = w.doi OR b.work_id = w.pmid
      OR list_contains(w.alias_dois, b.work_id)
),
gp AS (
    SELECT g.grant_id, pk.package_name, g.work_id
    FROM bridge_work_grant g
    JOIN pkg_work pk USING (work_id)
)
SELECT gp.grant_id,
       d.agency,
       d.ic_name,
       d.title,
       d.fy_first,
       d.fy_last,
       d.org_name,
       COUNT(DISTINCT gp.package_name)    AS n_packages_supported,
       COUNT(DISTINCT e.citing_work_id)   AS n_citing_works,
       LIST(DISTINCT gp.package_name)     AS package_names
FROM gp
LEFT JOIN dim_grant d USING (grant_id)
LEFT JOIN fact_citation_edge e ON e.cited_work_id = gp.work_id
GROUP BY gp.grant_id, d.agency, d.ic_name, d.title, d.fy_first, d.fy_last, d.org_name
ORDER BY n_packages_supported DESC, gp.grant_id;

-- Linked works (one row per describing/companion publication) — powers
-- ecosystem-level citation stats and the citations-by-year plot.
CREATE OR REPLACE TABLE mart_work AS
SELECT work_id, pmid, doi, title, year, journal, icite_rcr, citation_count,
       nih_percentile, apt, is_clinical, citations_per_year,
       journal ILIKE '%rxiv%' AS is_preprint, is_retracted, n_patent_citations, alias_dois
FROM dim_work;

-- Package → linked works (one row per package × work), for the explorer's papers list.
-- Same DOI/PMID reconciliation as `pw`; a pair reached by several match methods keeps
-- its highest-confidence edge. Works not yet in dim_work keep a row with NULL metadata.
CREATE OR REPLACE TABLE mart_package_work AS
SELECT b.package_name, b.repo,
       COALESCE(w.work_id, b.work_id)                          AS work_id,
       COALESCE(w.doi, CASE WHEN b.work_id LIKE '10.%' THEN b.work_id END) AS doi,
       w.pmid, w.title, w.year, w.journal, w.citation_count, w.icite_rcr,
       w.nih_percentile, w.apt, w.is_clinical, w.citations_per_year,
       w.journal ILIKE '%rxiv%' AS is_preprint, w.is_retracted, w.n_patent_citations,
       b.match_method, b.confidence, b.role
FROM bridge_package_pub b
LEFT JOIN dim_work w
  ON b.work_id = w.work_id OR b.work_id = w.doi OR b.work_id = w.pmid
      OR list_contains(w.alias_dois, b.work_id)
QUALIFY row_number() OVER (
    PARTITION BY b.package_name, b.repo, COALESCE(w.work_id, b.work_id)
    ORDER BY b.confidence DESC NULLS LAST, b.match_method
) = 1
ORDER BY b.package_name, b.repo, b.confidence DESC, w.year DESC NULLS LAST;

-- Flat package directory for the explorer view (frontend reads this directly).
CREATE OR REPLACE TABLE mart_package_directory AS
SELECT package_name, repo, latest_release, maintainer,  -- no maintainer_email (#33)
       title, description, biocviews, url, bug_reports, source_doi,
       len(depends_on_me) + len(imports_me) + len(links_to_me) AS n_reverse_deps,
       dependency_count AS n_deps, git_last_commit_date, package_status, has_news,
       n_vignettes, license,
       'https://bioconductor.org/packages/' || package_name || '/' AS bioc_url,
       in_elixir_rsec, biotools_id,
       'https://bio.tools/' || biotools_id AS biotools_url
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

-- Funders (and awards) OpenAlex lists on each linked work (#85). grant_id is set for NIH
-- awards: the core project number inside funder_award_id (5T32CA009337-33 -> T32CA009337)
-- matched to dim_grant, which carries the RePORTER detail.
CREATE OR REPLACE TABLE mart_work_funder AS
SELECT bw.work_id, bw.funder_id, f.name AS funder_name, f.ror, f.crossref_id, f.country_code,
       bw.award_id, bw.funder_award_id, g.grant_id
FROM bridge_work_funder bw
JOIN dim_funder f USING (funder_id)
LEFT JOIN dim_grant g ON g.grant_id = regexp_extract(
    upper(bw.funder_award_id), '([A-Z][A-Z0-9][0-9][A-Z]{2}[0-9]{6})', 1)
ORDER BY bw.work_id, f.name, bw.funder_award_id;

-- Award detail per award credited on a linked work (#90): one row per award; join
-- mart_work_funder on award_id for the works. NIH detail stays in RePORTER (grant_id there).
-- Filtered to the bridge: after an /awards outage dim_award is last run's (#104).
CREATE OR REPLACE TABLE mart_award AS
SELECT a.award_id, a.funder_id, f.name AS funder_name, a.funder_award_id, a.title, a.scheme,
       a.start_date, a.end_date, a.amount, a.currency, a.amount_usd, a.award_doi,
       a.provenance, a.is_stub
FROM dim_award a
LEFT JOIN dim_funder f USING (funder_id)
WHERE a.award_id IN (SELECT award_id FROM bridge_work_funder)
ORDER BY f.name, a.funder_award_id, a.award_id;

-- Institutions per linked work (one row per work × institution × author position);
-- filter author_position = 'last' for senior-author countries.
CREATE OR REPLACE TABLE mart_work_institution AS
SELECT bw.work_id, bw.ror, i.name, i.country_code, i.country,
       bw.author_position, bw.is_corresponding, i.latitude, i.longitude
FROM bridge_work_institution bw
JOIN dim_institution i USING (ror)
ORDER BY bw.work_id, bw.author_position, i.name;

-- Forward dependency edges (declared Depends/Imports/Suggests/LinkingTo; R excluded).
CREATE OR REPLACE TABLE mart_package_dependency AS
SELECT package_name, repo, dep, kind
FROM (
    SELECT package_name, repo, unnest(depends) AS dep, 'depends' AS kind FROM dim_package
    UNION ALL
    SELECT package_name, repo, unnest(imports), 'imports' FROM dim_package
    UNION ALL
    SELECT package_name, repo, unnest(suggests), 'suggests' FROM dim_package
    UNION ALL
    SELECT package_name, repo, unnest(linking_to), 'linking_to' FROM dim_package
)
ORDER BY package_name, repo, kind, dep;

-- Country → region grouping (#91), for filtering country-coded marts. One country, many groupings.
CREATE OR REPLACE TABLE mart_region_group AS
SELECT country_code, grouping, grouping_label, grouping_kind, as_of
FROM dim_region_group
ORDER BY grouping, country_code;

-- Funder → region grouping: the curated groupings for supranational funders, else the
-- groupings of the funder's OpenAlex country. Funders with neither get no rows.
CREATE OR REPLACE TABLE mart_funder_region AS
SELECT * FROM (
    SELECT fr.funder_id, fr.grouping, 'curated' AS basis
    FROM dim_funder_region fr
    WHERE fr.funder_id IN (SELECT funder_id FROM dim_funder)
    UNION ALL
    SELECT f.funder_id, r.grouping, 'country' AS basis
    FROM dim_funder f
    JOIN dim_region_group r ON r.country_code = f.country_code
    WHERE f.funder_id NOT IN (SELECT funder_id FROM dim_funder_region)
)
ORDER BY funder_id, grouping;

-- Citing-work reach per package (#92), latest snapshot. One row per package x dimension x key;
-- the total row's n_citing is the denominator. Join key to mart_region_group.country_code
-- (country rows) or mart_funder_region.funder_id (funder rows) to filter, never to sum.
CREATE OR REPLACE TABLE mart_package_reach AS
WITH r AS (
    SELECT * FROM fact_package_reach
    QUALIFY _snapshot = MAX(_snapshot) OVER ()
)
SELECT r.package_name, r.repo, r.dimension, r.key, r.key_name, r.n_citing,
       t.n_citing                         AS n_citing_total,
       r.n_citing / NULLIF(t.n_citing, 0) AS share_of_citing,
       r.n_works,
       r._snapshot
FROM r
JOIN r t ON t.package_name = r.package_name AND t.repo = r.repo AND t.dimension = 'total'
ORDER BY r.package_name, r.repo, r.dimension, r.n_citing DESC, r.key NULLS LAST;
"""

_MARTS = [
    "mart_package_impact",
    "mart_release_growth",
    "mart_release_history",
    "mart_grant_attribution",
    "mart_package_directory",
    "mart_work",
    "mart_package_work",
    "mart_package_person",
    "mart_person",
    "mart_package_funder",
    "mart_package_dependency",
    "mart_ecosystem_downloads_yearly",
    "mart_installer_downloads_monthly",
    "mart_package_downloads_monthly",
    "mart_work_institution",
    "mart_work_funder",
    "mart_award",
    "mart_region_group",
    "mart_funder_region",
    "mart_package_reach",
]

# Small row groups let DuckDB-WASM range-read one package from the sorted monthly mart.
_ROW_GROUP_SIZE = {"mart_package_downloads_monthly": 2048, "mart_package_reach": 2048}


def run() -> dict[str, int]:
    MART_DIR.mkdir(parents=True, exist_ok=True)
    con = db.connect()
    db.init_schema(con)
    counts: dict[str, int] = {}
    try:
        counts.update(regions.load_regions(con))
        con.execute(_MART_SQL)
        for mart in _MARTS:
            out = MART_DIR / f"{mart}.parquet"
            opts = f", ROW_GROUP_SIZE {_ROW_GROUP_SIZE[mart]}" if mart in _ROW_GROUP_SIZE else ""
            con.execute(f"COPY {mart} TO '{out}' (FORMAT parquet{opts})")
            n = con.execute(f"SELECT count(*) FROM {mart}").fetchone()[0]
            counts[mart] = n
            print(f"  {mart}: {n} rows -> {out}")
        unmapped = con.execute(
            "SELECT f.name, count(DISTINCT b.work_id) AS n FROM bridge_work_funder b "
            "JOIN dim_funder f USING (funder_id) "
            "WHERE f.funder_id NOT IN (SELECT funder_id FROM mart_funder_region) "
            "GROUP BY f.name ORDER BY n DESC, f.name LIMIT 5"
        ).fetchall()
        if unmapped:
            print("  regions: funders on linked works with no grouping "
                  f"(add to regions.yaml if supranational): {unmapped}")
    finally:
        con.close()
    return counts


# --- Published views file + data dictionary (#51) -------------------------------------
# The one place mart/column definitions live: written as COMMENT ON into the views file
# and exported as datapackage.json, which the Data page renders.
_PKG = {"package_name": "Bioconductor package name.",
        "repo": "Repository: bioc (software), data-experiment, data-annotation or workflows."}
_WORK = {
    "work_id": "Work identifier: PMID when known, else DOI (OpenAlex ID is an enrichment handle).",
    "pmid": "PubMed ID.",
    "doi": "DOI, bare and lower-case (no https://doi.org/ prefix).",
    "title": "Publication title.",
    "year": "Publication year.",
    "journal": "Journal or venue.",
    "icite_rcr": "Relative Citation Ratio (NIH iCite): field- and time-normalized citation rate; "
                 "1.0 = NIH-wide average.",
    "citation_count": "OpenAlex citation count.",
    "nih_percentile": "NIH iCite percentile of the RCR among NIH-funded papers (0-100); "
                      "90 = top decile.",
    "apt": "NIH iCite Approximate Potential to Translate: predicted probability (0-1) that "
           "the paper is later cited by a clinical article.",
    "is_clinical": "NIH iCite flag: the paper is itself a clinical article.",
    "citations_per_year": "NIH iCite citations per year since publication.",
    "is_preprint": "Venue looks like a preprint server (journal name contains 'rxiv').",
    "is_retracted": "OpenAlex retraction flag.",
    "n_patent_citations": "Distinct patents citing the work (Reliance on Science); 0 = none "
                          "found, empty = no OpenAlex id or not yet enriched.",
}
_DL = {
    "methodology_era": "Download-stats collection era: 'pre_2015_10' or 'modern'. Bioconductor "
                       "changed its methodology in Oct 2015; do not add counts across eras.",
    "distinct_ips": "Distinct downloading IP addresses, the usage proxy (less gameable than "
                    "downloads). Summed over months: an IP active in several months counts once "
                    "per month.",
    "downloads": "Raw download count (kept for reference; prefer distinct_ips).",
}
_GROUPING = ("Grouping id: eu27, horizon_associated, horizon_associated_pillar2, "
             "europe_geographic, or un_<UN M49 region or sub-region>, e.g. un_western_europe.")

DEFINITIONS: dict[str, dict] = {
    "mart_package_impact": {
        "description": "One row per package: downloads, linked publications, citations, RCR "
                       "and grants.",
        "columns": {
            **_PKG,
            "total_downloads": "All-time raw downloads (spans both methodology eras).",
            "total_distinct_ips": "All-time sum of monthly distinct IPs (spans both eras).",
            "downloads_trailing_12mo": "Raw downloads in the latest 12 months of stats.",
            "distinct_ips_trailing_12mo": "Sum of monthly distinct IPs in the latest 12 months "
                                          "of stats: the headline usage number.",
            "distinct_ips_prior_12mo": "Sum of monthly distinct IPs in the 12 months before "
                                       "the trailing window (for year-over-year change).",
            "usage_rank_in_repo": "Rank within repo by distinct_ips_trailing_12mo (1 = most used).",
            "n_primary_pubs": "Linked papers the package asks users to cite.",
            "total_citations": "Sum of OpenAlex citation counts across linked papers.",
            "n_citing_works": "Distinct works citing a linked paper (0 until the cited-by "
                              "enrichment has run).",
            "median_rcr": "Median iCite Relative Citation Ratio across linked papers (RCR is a "
                          "rate, so the median, never the sum).",
            "n_distinct_grants_citing": "Distinct NIH grants acknowledged by a linked paper "
                                        "(NIH RePORTER publication links).",
        },
    },
    "mart_release_growth": {
        "description": "One row per Bioconductor release since 1.0; VIEWS-derived counts from 1.8.",
        "columns": {
            "bioc_release": "Bioconductor release, e.g. 3.23.",
            "release_date": "Release date from the release-announcements page.",
            "n_software_announced": "Software package count as announced for the release.",
            "n_packages": "Distinct packages in the release VIEWS (NULL for 1.0-1.7: no VIEWS).",
            "n_new_packages": "Packages first seen in this release (NULL for the first loaded).",
            "n_removed": "Packages in the previous release, absent here (NULL for first loaded).",
            "net_downloads": "Reserved: release-windowed downloads (NULL for now).",
        },
    },
    "mart_release_history": {
        "description": "Package counts per Bioconductor release and repository (historic VIEWS).",
        "columns": {
            "bioc_release": "Bioconductor release, e.g. 3.23.",
            "release_date": "Release date from the release-announcements page.",
            "repo": "Repository: bioc, data-experiment, data-annotation or workflows.",
            "n_packages": "Distinct packages in that repository's VIEWS for the release.",
            "n_new": "Packages first seen in this release for the repository.",
            "n_removed": "Packages in the previous release and absent here.",
        },
    },
    "mart_grant_attribution": {
        "description": "One row per NIH grant acknowledged by a paper linked to a package.",
        "columns": {
            "grant_id": "NIH core project number, e.g. U24CA289073.",
            "agency": "NIH Institute/Center code.",
            "ic_name": "NIH Institute/Center name, e.g. National Human Genome Research Institute.",
            "title": "Parent award title (NIH RePORTER); a sub-project title only if no parent.",
            "fy_first": "First fiscal year RePORTER lists for the core project.",
            "fy_last": "Last fiscal year RePORTER lists for the core project.",
            "org_name": "Awardee organization on the latest parent-award row.",
            "n_packages_supported": "Distinct packages whose linked paper acknowledges the grant.",
            "n_citing_works": "Distinct works citing those papers (0 until cited-by runs).",
            "package_names": "The supported packages.",
        },
    },
    "mart_package_directory": {
        "description": "One row per package: DESCRIPTION metadata from the repository VIEWS file.",
        "columns": {
            **_PKG,
            "latest_release": "Newest Bioconductor release carrying the package.",
            "maintainer": "Maintainer name (no email).",
            "title": "Package title.",
            "description": "Package description.",
            "biocviews": "biocViews terms (Bioconductor's controlled vocabulary).",
            "url": "URLs from the DESCRIPTION URL field.",
            "bug_reports": "DESCRIPTION BugReports URL.",
            "source_doi": "The package's own DOI, when it has one.",
            "n_reverse_deps": "Packages that depend on, import or link to this one.",
            "n_deps": "Declared dependency count (from VIEWS).",
            "git_last_commit_date": "Date of the last commit on the release branch.",
            "package_status": "Status from VIEWS, e.g. Deprecated.",
            "has_news": "Ships a NEWS file.",
            "n_vignettes": "Number of vignettes.",
            "license": "DESCRIPTION License.",
            "bioc_url": "Package landing page on bioconductor.org.",
            "in_elixir_rsec": "Listed in the ELIXIR Research Software Ecosystem's weekly "
                              "Bioconductor import (research-software-ecosystem/content, "
                              "imports/bioconductor). Matched by package name in any repo. The "
                              "import covers the software (bioc) repo, so other repos normally "
                              "read FALSE, but a stale row for a package that moved repos can "
                              "also read TRUE. FALSE means not in that import, not absent from "
                              "bio.tools. NULL means the package has not yet been checked "
                              "against the listing (new package, or the fetch was skipped). "
                              "Values carry over from the last successful fetch.",
            "biotools_id": "bio.tools identifier: the RSEc data/<id>/ folder holding both this "
                           "package's Bioconductor record and a bio.tools record. When bio.tools "
                           "has two entries, the curated id without the bioconductor- prefix "
                           "wins. Matched by package name in any repo, and set independently "
                           "of in_elixir_rsec (it can be non-NULL when in_elixir_rsec is "
                           "FALSE). NULL when there is none, or when the package has not yet "
                           "been checked against the listing (new package, or the fetch was "
                           "skipped). Values carry over from the last successful fetch.",
            "biotools_url": "The package's bio.tools page (https://bio.tools/<biotools_id>).",
        },
    },
    "mart_work": {
        "description": "One row per linked publication, with iCite metrics, citations "
                       "and patent citations.",
        "columns": {
            **_WORK,
            "alias_dois": "Other DOIs OpenAlex lists for this work, e.g. the bioRxiv preprint a "
                          "package's CITATION cites after OpenAlex merged it into the journal "
                          "version. NULL when OpenAlex lists none, and always NULL for works "
                          "enriched under --source lake (the lake drops locations) or from "
                          "iCite alone, so NULL does not mean the work has no preprint. A DOI "
                          "that is another loaded OpenAlex work's own DOI is never listed; a "
                          "preprint OpenAlex still keeps as its own work can be listed if this "
                          "run did not load it. doi is the version the metrics describe.",
        },
    },
    "mart_package_work": {
        "description": "One row per package x linked publication, with the link's provenance.",
        "columns": {
            **_PKG, **_WORK,
            "doi": "The work's DOI, bare and lower-case (no https://doi.org/ prefix). It may "
                   "differ from the DOI the package cites: a preprint DOI OpenAlex merged into "
                   "its journal version shows the journal DOI (see mart_work.alias_dois).",
            "match_method": "How the link was made: doi (the package's own DOI), doi_alias (the "
                            "package's DOI is another version of the paper, usually the preprint, "
                            "that OpenAlex merged into this work; doi shows the version "
                            "OpenAlex keeps), citation_file (CITATION / CITATION.cff), "
                            "description_doi (a DOI in Description, sometimes a dependency's "
                            "paper), title_search, manual.",
            "confidence": "Link confidence, 0-1 (doi and doi_alias 1.0, citation_file 0.9, "
                          "description_doi 0.8).",
            "role": "Role of the paper for the package, e.g. primary.",
        },
    },
    "mart_package_person": {
        "description": "One row per package x person, from Authors@R (no emails).",
        "columns": {
            **_PKG,
            "person_id": "Person identifier (ORCID when declared, else a name key).",
            "name": "Person name.",
            "orcid": "ORCID iD, when declared.",
            "roles": "Authors@R roles: cre (maintainer), aut, ctb, fnd, ...",
            "is_maintainer": "Has the cre role.",
            "source": "Where the person came from (Authors@R or Maintainer).",
        },
    },
    "mart_person": {
        "description": "One row per person: packages authored and maintained.",
        "columns": {
            "person_id": "Person identifier (ORCID when declared, else a name key).",
            "name": "Person name.",
            "orcid": "ORCID iD, when declared.",
            "n_packages": "Packages the person appears on.",
            "n_maintained": "Packages where the person has the cre role.",
            "n_authored": "Packages where the person has the aut role.",
            "package_names": "The packages.",
        },
    },
    "mart_package_funder": {
        "description": "One row per package x declared funder (the Authors@R fnd role).",
        "columns": {
            **_PKG,
            "funder_id": "Normalized funder identifier.",
            "funder_name": "Normalized funder name.",
            "curated": "Funder name matched the curated alias list.",
            "declared_name": "Funder name as written in Authors@R.",
            "grant_number": "Grant number as declared, when present.",
            "grant_id": "NIH core project number when the declared grant matches RePORTER.",
        },
    },
    "mart_work_funder": {
        "description": "One row per linked publication x funder x award, from OpenAlex.",
        "columns": {
            "work_id": _WORK["work_id"],
            "funder_id": "OpenAlex funder id (F...); the same id as mart_package_funder for "
                         "funders in the curated alias list.",
            "funder_name": "Funder name.",
            "ror": "ROR identifier of the funder, when known.",
            "crossref_id": "Crossref Funder Registry id (10.13039/<id>), when known.",
            "country_code": "ISO country code of the funder.",
            "award_id": "OpenAlex award id (G...); null when no award is listed.",
            "funder_award_id": "The funder's own award number as OpenAlex records it.",
            "grant_id": "NIH core project number when the award matches RePORTER (dim_grant).",
        },
    },
    "mart_award": {
        "description": "One row per OpenAlex award credited by a linked publication; join "
                       "mart_work_funder on award_id for the publications. An award here means "
                       "the paper credits that grant in its funding acknowledgement, not that "
                       "the grant's money funded the software: never sum amount or amount_usd, "
                       "within or across funders. Most awards are stubs (is_stub): funder and "
                       "award number only. Detail completeness varies by funder, so counts of "
                       "detailed awards measure funder metadata quality, not funding. For NIH "
                       "awards RePORTER is authoritative: follow mart_work_funder.grant_id to "
                       "mart_grant_attribution. After an OpenAlex /awards outage the "
                       "detail is from the previous run, and awards credited since then are "
                       "missing here.",
        "columns": {
            "award_id": "OpenAlex award id (G...); joins mart_work_funder.award_id.",
            "funder_id": "OpenAlex funder id (F...); joins mart_work_funder and "
                         "mart_funder_region.",
            "funder_name": "Funder name.",
            "funder_award_id": "The funder's own award number as OpenAlex records it. Display "
                               "text, not a join key: it can hold several numbers or a "
                               "programme name ('251217 and 255847', 'HORIZON2020').",
            "title": "Award title from the funder's record; empty for stubs.",
            "scheme": "Funding scheme as the funder names it (OpenAlex funder_scheme), e.g. "
                      "'F31' or 'H2020 - RIA'. Not harmonized across funders.",
            "start_date": "Award start date, when the funder's record has one.",
            "end_date": "Award end date, when the funder's record has one.",
            "amount": "Award amount in currency as the source records it; its scope (whole "
                      "award, one year, one share) varies by source. What the grant was "
                      "worth, not what funded the software: never sum.",
            "currency": "ISO 4217 currency code of amount.",
            "amount_usd": "amount converted to US dollars by OpenAlex at an exchange rate it "
                          "picks for that award: usually the rate on the award's start date, "
                          "else a yearly average (the basis is not stored). Not "
                          "inflation-adjusted. For display only: never sum, or compare across "
                          "countries or years.",
            "award_doi": "Award DOI, bare and lower-case (e.g. 10.3030/777483 for CORDIS), "
                         "when the funder registers one.",
            "provenance": "OpenAlex source of the award record: a funder or grant database "
                          "(nih_exporter, cordis, gateway_to_research, ...) or a publication's "
                          "acknowledgement (crossref_work_funders, europepmc_work_funders, "
                          "...). NULL when OpenAlex no longer returns the award or its record "
                          "has no provenance.",
            "is_stub": "True when nothing is known beyond a publication's funding "
                       "acknowledgement: provenance crossref_work_funders, "
                       "europepmc_work_funders, datacite_work_funders or crossref_work.grants, "
                       "the award is missing from OpenAlex or its record has no provenance, or "
                       "the record carries no title, dates, amount or DOI. Treat stubs as "
                       "funder and award number only; any detail on them is unverified.",
        },
    },
    "mart_region_group": {
        "description": "One row per country x named region grouping, from the checked-in "
                       "regions.yaml. A country can be in several groupings. Groupings are "
                       "filters: join on country_code (e.g. mart_work_institution); never add "
                       "counts across groupings. Count DISTINCT work_id after joining: "
                       "mart_work_institution has several rows per work. No rows means the "
                       "country is unknown, not outside every grouping; for a share, use works "
                       "whose institution country is in some un_m49_region grouping as the "
                       "denominator. A work with both a known and an unknown location still "
                       "counts toward the denominator, so the share is a lower bound.",
        "columns": {
            "country_code": "ISO 3166-1 alpha-2 code as OpenAlex writes it (GR, GB), plus XK "
                            "(Kosovo), TW (Taiwan, which UN M49 does not list; placed in Eastern "
                            "Asia) and EU, OpenAlex's code for EU-level bodies (in eu27, "
                            "europe_geographic and un_europe only).",
            "grouping": _GROUPING,
            "grouping_label": "Human-readable grouping name.",
            "grouping_kind": "policy (EU or Horizon Europe membership), geographic, "
                             "un_m49_region or un_m49_subregion. Policy groupings are "
                             "membership on the as_of date, not membership when a paper or "
                             "grant was written: the UK is never in eu27.",
            "as_of": "Date the membership lists were last checked against their sources (the "
                     "EU's member-state list, the European Commission's list of countries "
                     "associated to Horizon Europe, UN M49); the same on every row. Policy "
                     "groupings change over time (the UK joined Horizon Europe in 2024), so a "
                     "horizon_associated filter reflects this date. Sources and list versions: "
                     "https://github.com/seandavi/bioc-intelligence/blob/main/src/biocintel/"
                     "regions.yaml",
        },
    },
    "mart_funder_region": {
        "description": "One row per funder x region grouping. A funder takes the groupings of "
                       "its OpenAlex country, except supranational funders OpenAlex gives no "
                       "country (European Commission, ERC, Horizon 2020, ...), which take the "
                       "curated groupings in regions.yaml. Funders with neither have no rows. "
                       "A grouping is where the funder is based, not where the funded "
                       "researchers are: EMBL (Germany) is in eu27, WHO (Switzerland) in "
                       "horizon_associated. Count DISTINCT work_id after joining: "
                       "mart_work_funder has several rows per work (awards, co-funders in the "
                       "same grouping). No rows means the location is unknown, not outside every "
                       "grouping; for a share, use works with at least one funder that has a "
                       "row here as the denominator. A work with both a known and an unknown "
                       "location still counts toward the denominator, so the share is a lower "
                       "bound. Grouping membership is as of mart_region_group.as_of.",
        "columns": {
            "funder_id": "OpenAlex funder id (F...); joins mart_work_funder.",
            "grouping": _GROUPING,
            "basis": "country (from the funder's OpenAlex country_code) or curated "
                     "(hand-mapped in regions.yaml).",
        },
    },
    "mart_package_reach": {
        "description": "One row per package x dimension (total, country, funder) x key: works "
                       "citing the package's confident primary papers (match_method doi, doi_alias "
                       "or citation_file) that OpenAlex resolves (n_works of them), counted by "
                       "OpenAlex at the latest snapshot. A confident paper with no live OpenAlex "
                       "id is left out, so a package's total can change between snapshots because "
                       "n_works did, not only because more works cite it. n_citing counts "
                       "distinct citing works across all of those papers (one OR'd query), so a "
                       "work citing two of them counts once. Values are not additive: not across "
                       "packages (a work citing two packages counts for each) and not across keys "
                       "(a work counts once for every author affiliation country and every "
                       "funder), so adding countries into a region over-counts. Join key to "
                       "mart_region_group or mart_funder_region to filter rows, and read each key "
                       "on its own. Funder rows are the 200 largest only (the unknown, NULL-key "
                       "row among them), so they do not add up to the total even before overlap. "
                       "A funder with no row may still fund citing works below the top 200; a "
                       "package with fewer than 200 funder rows has its full list. Not the same "
                       "as mart_package_impact.n_citing_works, which counts stored citation edges "
                       "over all linked papers (including description_doi).",
        "columns": {
            **_PKG,
            "dimension": "total (one row: all distinct citing works), country (a country of any "
                         "author affiliation on the citing work, OpenAlex authorships.countries) "
                         "or funder (a funder OpenAlex lists on the citing work; the 200 largest "
                         "only).",
            "key": "ISO 3166-1 alpha-2 country code (joins mart_region_group.country_code) or "
                   "OpenAlex funder id F... (joins mart_funder_region.funder_id). NULL on the "
                   "total row, and on the row counting citing works with no known affiliation "
                   "country or no listed funder: NULL means unknown, not elsewhere.",
            "key_name": "Country or funder name as OpenAlex displays it; NULL when key is NULL.",
            "n_citing": "Distinct citing works with this key, across the package's n_works "
                        "confident primary papers (total row: all citing works). Not additive "
                        "across packages or keys.",
            "n_citing_total": "The package's total: distinct citing works, the denominator of "
                              "share_of_citing.",
            "share_of_citing": "n_citing / n_citing_total, 0-1; NULL when nothing cites the "
                               "package. Shares across keys add up to more than 1.",
            "n_works": "Confident primary papers OpenAlex resolves to a live work at this "
                       "snapshot: the papers every count on the package's rows covers (the same "
                       "value on each of its rows). A confident paper OpenAlex does not resolve "
                       "is not counted, so a change in n_works between snapshots moves the counts "
                       "for reasons other than new citing works. Counted as distinct OpenAlex "
                       "works, so two confident ids that OpenAlex merges into one work count "
                       "once. NULL on snapshots fetched before n_works was recorded.",
            "_snapshot": "Date the counts were fetched from OpenAlex.",
        },
    },
    "mart_package_dependency": {
        "description": "Forward dependency edges (Depends/Imports/Suggests/LinkingTo; R excluded).",
        "columns": {
            **_PKG,
            "dep": "The package depended on.",
            "kind": "depends, imports, suggests or linking_to.",
        },
    },
    "mart_ecosystem_downloads_yearly": {
        "description": "Downloads per year x repo x methodology era (2015 has a row per era).",
        "columns": {
            "year": "Calendar year.", "repo": _PKG["repo"],
            "methodology_era": _DL["methodology_era"],
            "sum_package_distinct_ips": "SUM of per-package monthly distinct IPs: a volume "
            "measure (one address x 50 packages counts 50 times), never a count of users. "
            "For project-level installs use mart_installer_downloads_monthly.",
            "downloads": _DL["downloads"],
            "n_packages_with_downloads": "Packages with at least one download that year.",
        },
    },
    "mart_installer_downloads_monthly": {
        "description": "Project-level installs per month: distinct IPs of the installer package "
        "(BiocInstaller 2011-2018, then BiocVersion, which BiocManager installs). The "
        "Bioconductor convention for 'machines that installed Bioconductor'.",
        "columns": {
            "year": "Calendar year.", "month": "Month 1-12.",
            "methodology_era": _DL["methodology_era"],
            "installer_package": "Which installer package the row comes from.",
            "installer_distinct_ips": "Distinct IPs that downloaded the installer package "
            "that month: the project-level usage proxy.",
            "installer_downloads": "Raw downloads of the installer package that month.",
        },
    },
    "mart_package_downloads_monthly": {
        "description": "Downloads per package x month.",
        "columns": {**_PKG, "year": "Calendar year.", "month": "Month, 1-12.", **_DL,
                    "distinct_ips": "Distinct downloading IP addresses that month."},
    },
    "mart_work_institution": {
        "description": "One row per linked publication x author institution x author position.",
        "columns": {
            "work_id": _WORK["work_id"],
            "ror": "ROR identifier of the institution.",
            "name": "Institution name.",
            "country_code": "ISO country code.",
            "country": "Country name.",
            "author_position": "first, middle or last.",
            "is_corresponding": "Corresponding-author affiliation.",
            "latitude": "Institution latitude.",
            "longitude": "Institution longitude.",
        },
    },
}

# Honest-default views: name -> (source mart, description, SQL with {src}). Every view
# inlines read_parquet(url): DuckDB 1.0 clients can't resolve a sibling view or macro
# when the file is attached under their own alias.
HONEST_VIEWS = {
    "package_pubs_confident": (
        "mart_package_work",
        "Package-paper links made by DOI (own or merged-preprint alias) or CITATION file only "
        "(drops description_doi and title_search). Use for grant reporting.",
        "SELECT * FROM {src} WHERE match_method IN ('doi', 'doi_alias', 'citation_file')",
    ),
    "downloads_modern_era": (
        "mart_ecosystem_downloads_yearly",
        "Yearly downloads per repo, modern collection methodology only (Oct 2015 on).",
        "SELECT * FROM {src} WHERE methodology_era = 'modern'",
    ),
    "ecosystem_yearly": (
        "mart_ecosystem_downloads_yearly",
        "Download VOLUME per year summed across repos and packages, one row per methodology "
        "era (never mix eras). sum_package_distinct_ips is not a count of users; see "
        "installs_yearly for that.",
        "SELECT year, methodology_era, "
        "SUM(sum_package_distinct_ips) AS sum_package_distinct_ips, "
        "SUM(downloads) AS downloads, SUM(n_packages_with_downloads) AS n_packages_with_downloads "
        "FROM {src} GROUP BY year, methodology_era ORDER BY year, methodology_era",
    ),
    "installs_yearly": (
        "mart_installer_downloads_monthly",
        "Machines installing Bioconductor per year: distinct IPs of the installer package "
        "(BiocInstaller to 2018, BiocVersion since), summed over months. The Bioconductor "
        "convention for project-level usage; one row per methodology era.",
        "SELECT year, methodology_era, SUM(installer_distinct_ips) AS installer_distinct_ips "
        "FROM {src} GROUP BY year, methodology_era ORDER BY year, methodology_era",
    ),
    "package_impact_ranked": (
        "mart_package_impact",
        "package_impact ordered by rank within repo on trailing-12-month distinct IPs.",
        "SELECT * FROM {src} ORDER BY repo, usage_rank_in_repo",
    ),
}

_FRICTIONLESS_TYPES = {"VARCHAR": "string", "DOUBLE": "number", "BOOLEAN": "boolean",
                       "DATE": "date"}


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def write_views_db(
    out: Path, public_base: str, marts_dir: Path = MART_DIR, snapshot: str | None = None
) -> list[str]:
    """Write a views-only DuckDB file over the marts at ``public_base`` + datapackage.json.

    One view per mart in ``marts_dir`` (``mart_x`` -> ``x``) plus HONEST_VIEWS, all reading
    ``<public_base>/mart_x.parquet``. CREATE VIEW binds, so the URLs must be readable now;
    DuckDB 1.0 clients error if the published types later differ from bind time.
    """
    snapshot = snapshot or dt.datetime.now(dt.UTC).date().isoformat()
    base = public_base.rstrip("/")
    marts = sorted(p.stem for p in marts_dir.glob("mart_*.parquet"))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    con = duckdb.connect()
    # STORAGE_VERSION v1.0.0 so DuckDB >= 1.0 clients (incl. the R package) can open it.
    con.execute(f"ATTACH {_q(str(out))} AS pub (STORAGE_VERSION 'v1.0.0')")
    con.execute("USE pub")
    src: dict[str, str] = {}  # mart -> read_parquet(<public url>)
    views: dict[str, tuple[str, str]] = {}  # view -> (source mart, description)
    for m in marts:
        read = f"read_parquet({_q(f'{base}/{m}.parquet')})"
        try:
            con.execute(f"CREATE VIEW {m.removeprefix('mart_')} AS SELECT * FROM {read}")
        except duckdb.Error as e:  # a new mart is not published yet; next refresh picks it up
            print(f"  WARNING: skipping {m}: {str(e).splitlines()[0]}")
            continue
        src[m] = read
        views[m.removeprefix("mart_")] = (m, DEFINITIONS[m]["description"])
    for name, (m, desc, sql) in HONEST_VIEWS.items():
        if m in src:
            views[name] = (m, desc)
            con.execute(f"CREATE VIEW {name} AS {sql.format(src=src[m])}")
    if {"mart_package_directory", "mart_package_impact"} <= src.keys():
        con.execute(
            "CREATE MACRO package(pkg) AS TABLE "
            "SELECT d.*, i.* EXCLUDE (package_name, repo) "
            f"FROM {src['mart_package_directory']} d "
            f"LEFT JOIN {src['mart_package_impact']} i USING (package_name, repo) "
            "WHERE d.package_name = pkg"
        )
    if {"mart_grant_attribution", "mart_package_impact"} <= src.keys():
        con.execute(
            "CREATE MACRO grant_report(gid) AS TABLE "
            "SELECT g.grant_id, g.agency, g.title AS grant_title, i.* FROM ("
            "SELECT grant_id, agency, title, unnest(package_names) AS package_name "
            f"FROM {src['mart_grant_attribution']} WHERE grant_id = gid) g "
            f"JOIN {src['mart_package_impact']} i USING (package_name) "
            "ORDER BY i.distinct_ips_trailing_12mo DESC"
        )

    resources = []
    for view, (m, desc) in views.items():
        con.execute(f"COMMENT ON VIEW {view} IS {_q(f'{desc} Snapshot {snapshot}.')}")
        cols = con.execute(
            "SELECT column_name, data_type FROM duckdb_columns() "
            "WHERE database_name = 'pub' AND table_name = ? ORDER BY column_index",
            [view],
        ).fetchall()
        for col, _ in cols:  # KeyError = a new mart column without a definition
            con.execute(f"COMMENT ON COLUMN {view}.{col} IS {_q(DEFINITIONS[m]['columns'][col])}")
        if view != m.removeprefix("mart_"):
            continue
        local = con.execute(
            f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM "
            f"read_parquet({_q(str(marts_dir / f'{m}.parquet'))}))"
        ).fetchall()
        if local != cols:
            print(f"  WARNING: {view} bound against a different schema at {base} than "
                  f"{marts_dir}; regenerate the views file once the new marts are published")
        resources.append({
            "name": m,
            "path": f"{base}/{m}.parquet",
            "format": "parquet",
            "mediatype": "application/vnd.apache.parquet",
            "bytes": (marts_dir / f"{m}.parquet").stat().st_size,
            "description": desc,
            "schema": {"fields": [
                {"name": c,
                 "type": "array" if t.endswith("[]") else
                 _FRICTIONLESS_TYPES.get(t, "integer" if "INT" in t else "any"),
                 "description": DEFINITIONS[m]["columns"][c]}
                for c, t in cols
            ]},
        })
    con.execute("USE memory")
    con.execute("DETACH pub")  # checkpoints: no .wal beside the published file
    con.close()

    package = {
        "name": "bioc-intelligence",
        "title": "Bioconductor Intelligence marts",
        "description": "Usage, publication, citation and grant metrics for Bioconductor packages. "
                       f"Query in DuckDB: ATTACH '{base}/{out.name}' AS bi (READ_ONLY).",
        "homepage": "https://github.com/seandavi/bioc-intelligence",
        "version": snapshot,
        "created": f"{snapshot}T00:00:00Z",
        "sources": [{"title": t, "path": p} for t, p in [
            ("Bioconductor", "https://bioconductor.org"),
            ("OpenAlex", "https://openalex.org"),
            ("NIH iCite", "https://icite.od.nih.gov"),
            ("NIH RePORTER", "https://reporter.nih.gov"),
        ]],
        "resources": resources,
        # Not Frictionless: the honest-default views in the DuckDB file, for the Data page.
        "views": [{"name": n, "source": m, "description": d, "sql": s.format(src=m)}
                  for n, (m, d, s) in HONEST_VIEWS.items() if m in src],
    }
    (out.parent / "datapackage.json").write_text(json.dumps(package, indent=2) + "\n")
    print(f"  views file: {len(views)} views over {base} -> {out}")
    return list(views)


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--views-db", type=Path,
                    help="also write a views-only DuckDB file (+ datapackage.json beside it)")
    ap.add_argument("--public-base", default="https://impact.bioconductor.org/data",
                    help="URL the views read the marts from")
    ap.add_argument("--marts-dir", type=Path,
                    help="write only the views file, over these existing marts (no store)")
    ap.add_argument("--snapshot", help="snapshot date for the comments (default: today, UTC)")


def run_from_args(args: argparse.Namespace) -> None:
    if args.marts_dir is None:
        run()
    if args.views_db is not None:
        write_views_db(args.views_db, args.public_base, args.marts_dir or MART_DIR, args.snapshot)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build mart_* tables and export Parquet.")
    add_arguments(ap)
    args = ap.parse_args(argv)
    print("build_marts:")
    run_from_args(args)


if __name__ == "__main__":
    main()
