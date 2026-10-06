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
       title, description, biocviews, url, bug_reports, source_doi,
       len(depends_on_me) + len(imports_me) + len(links_to_me) AS n_reverse_deps,
       dependency_count AS n_deps, git_last_commit_date, package_status, has_news,
       n_vignettes, license,
       'https://bioconductor.org/packages/' || package_name || '/' AS bioc_url
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
    "mart_package_dependency",
    "mart_ecosystem_downloads_yearly",
    "mart_package_downloads_monthly",
    "mart_work_institution",
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
}
_DL = {
    "methodology_era": "Download-stats collection era: 'pre_2015_10' or 'modern'. Bioconductor "
                       "changed its methodology in Oct 2015; do not add counts across eras.",
    "distinct_ips": "Distinct downloading IP addresses, the usage proxy (less gameable than "
                    "downloads). Summed over months: an IP active in several months counts once "
                    "per month.",
    "downloads": "Raw download count (kept for reference; prefer distinct_ips).",
}
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
        "description": "Package counts per Bioconductor release.",
        "columns": {
            "bioc_release": "Bioconductor release, e.g. 3.23.",
            "n_packages": "Packages in the release.",
            "n_new_packages": "Packages first seen in the release (0 until version history lands).",
            "net_downloads": "Reserved: release-windowed downloads (NULL for now).",
        },
    },
    "mart_grant_attribution": {
        "description": "One row per NIH grant acknowledged by a paper linked to a package.",
        "columns": {
            "grant_id": "NIH core project number, e.g. U24CA289073.",
            "agency": "NIH Institute/Center code.",
            "title": "Grant title (NIH RePORTER).",
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
        },
    },
    "mart_work": {
        "description": "One row per linked publication, with iCite RCR and citations.",
        "columns": _WORK,
    },
    "mart_package_work": {
        "description": "One row per package x linked publication, with the link's provenance.",
        "columns": {
            **_PKG, **_WORK,
            "match_method": "How the link was made: doi (the package's own DOI), citation_file "
                            "(CITATION / CITATION.cff), description_doi (a DOI in Description, "
                            "sometimes a dependency's paper), title_search, manual.",
            "confidence": "Link confidence, 0-1 (doi 1.0, citation_file 0.9, description_doi 0.8).",
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
            "year": "Calendar year.", "repo": _PKG["repo"], **_DL,
            "n_packages_with_downloads": "Packages with at least one download that year.",
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
        "Package-paper links made by DOI or CITATION file only (drops description_doi and "
        "title_search). Use for grant reporting.",
        "SELECT * FROM {src} WHERE match_method IN ('doi', 'citation_file')",
    ),
    "downloads_modern_era": (
        "mart_ecosystem_downloads_yearly",
        "Yearly downloads per repo, modern collection methodology only (Oct 2015 on).",
        "SELECT * FROM {src} WHERE methodology_era = 'modern'",
    ),
    "ecosystem_yearly": (
        "mart_ecosystem_downloads_yearly",
        "Downloads per year summed across repos, one row per methodology era (never mix eras).",
        "SELECT year, methodology_era, SUM(distinct_ips) AS distinct_ips, "
        "SUM(downloads) AS downloads, SUM(n_packages_with_downloads) AS n_packages_with_downloads "
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
    ap.add_argument("--public-base", default="https://seandavi.github.io/bioc-intelligence/data",
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
