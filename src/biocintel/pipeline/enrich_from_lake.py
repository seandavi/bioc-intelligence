"""enrich_from_lake — fill dim_work, dim_grant, fact_citation_edge, fact_package_reach.

All cross-catalog SQL against the read-only lake (spec §4/§7). Driven by the set
of *primary works* already linked in ``bridge_package_pub`` (run ``link_works``
first). Steps:

- **works**  — linked OpenAlex works + iCite RCR/percentile/APT → ``dim_work`` (cheap;
  scans the 114M ``works`` once to materialize a small ``linked`` temp table), then
  citing-patent counts from ``reliance.patent_citations`` (best-effort: a failure
  is logged and the run continues).
- **grants** — ``reporter.publink``→``reporter.projects`` for those works'
  PMIDs → ``dim_grant`` + ``bridge_work_grant``.
- **institutions** — author affiliations of every ``dim_work`` row with an
  OpenAlex id, from ``openalex.works_authorships`` + ``openalex.institutions`` →
  ``dim_institution`` + ``bridge_work_institution``. Best-effort (spec §3): a
  failure is logged and the run continues.
- **funders** — ``openalex.works_funders`` / ``works_awards`` (+ ``openalex.funders``) of
  every ``dim_work`` row with an OpenAlex id → ``bridge_work_funder`` and the OpenAlex
  funders merged into ``dim_funder`` (#85), plus award detail from ``openalex.awards``
  (``/awards``) → ``dim_award`` (#90), best-effort on its own. Best-effort, as institutions.
  The lake's ``works_funders``/``works_awards`` are empty or absent, so this is effectively
  ``api``-only.
- **citations** — cited-by edges from ``openalex.work_references`` →
  ``fact_citation_edge``. **Heavy**: scans the 1.29B-row references table plus a
  second ``works`` pass for citing-side metadata, so it is **opt-in** (not in the
  default step set) to respect R2 egress. Run it deliberately for a full refresh.
- **reach** (opt-in, api-only) — per package, the works citing its
  ``doi``/``doi_alias``/``citation_file`` primary papers (one OR'd ``cites:`` filter over this
  run's live OpenAlex ids), counted by author affiliation country and by funder via OpenAlex
  ``group_by`` → ``fact_package_reach`` (snapshot-stamped, with ``n_works``, the papers
  counted); citing-work funders are merged into ``dim_funder`` (#92). Needs
  ``OPENALEX_API_KEY`` (~2 calls per package). Best-effort.

Idempotent per step (scoped or whole-table deletes / INSERT OR REPLACE).

``--source api`` (default) fills ``lake`` from OpenAlex, iCite and RePORTER for just
the working set (``biocintel.sources``) — seconds instead of the scans above, except
``citations`` (~one OpenAlex call per 200 citing works; set ``OPENALEX_API_KEY``).
Patent counts are lake-only and skipped under ``api``. ``--source lake`` reads
cdsci-lake. The SQL is the same either way. A bridge DOI may match a work through its alias
DOIs (the preprint OpenAlex merged into it, #95): ``api`` only, since the lake drops ``locations``.
"""

from __future__ import annotations

import argparse
import os

import duckdb

from ..lake import connect_with_lake
from ..sources import connect_with_sources, openalex

SOURCES = ("api", "lake")

DEFAULT_STEPS = ("works", "institutions", "funders", "grants")
ALL_STEPS = ("works", "institutions", "funders", "grants", "citations", "reach")

# Small driver table: the OpenAlex works linked to packages, with spine work_id.
_LINKED_SQL = """
CREATE OR REPLACE TEMP TABLE linked AS
SELECT DISTINCT
    w.id AS oa_id, w.pmid, w.doi,
    COALESCE(CAST(w.pmid AS VARCHAR), w.doi) AS work_id,
    w.title, w.publication_year AS year, w.source_name AS journal, w.cited_by_count,
    w.is_retracted
FROM lake.openalex.works w
LEFT JOIN works_alt_dois a ON a.work_id = w.id
-- A bridge work_id is PMID-or-DOI; match EITHER side (a citation link stores the
-- DOI even when the work also has a PMID, so a single COALESCE key would miss it),
-- or a DOI OpenAlex merged into the work (alias, e.g. its bioRxiv preprint).
JOIN bi.bridge_package_pub b
  ON b.work_id = CAST(w.pmid AS VARCHAR) OR b.work_id = w.doi OR b.work_id = a.doi
-- One work per DOI: OpenAlex can hold a preprint and its PubMed record as two works
-- sharing a DOI (TSAR); keep the one with a PMID.
QUALIFY row_number() OVER (
    PARTITION BY COALESCE(w.doi, w.id) ORDER BY w.pmid NULLS LAST, w.id
) = 1;
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
    ic.title, ic.year, ic.journal, ic.citation_count, NULL AS is_retracted
FROM lake.icite.metadata ic
WHERE (ic.doi IN (SELECT work_id FROM bi.bridge_package_pub)
       OR CAST(ic.pmid AS VARCHAR) IN (SELECT work_id FROM bi.bridge_package_pub))
  AND NOT EXISTS (SELECT 1 FROM linked l WHERE l.pmid = ic.pmid)
  AND NOT EXISTS (SELECT 1 FROM linked l WHERE l.doi = ic.doi);
"""

_WORKS_SQL = """
INSERT OR REPLACE INTO bi.dim_work
    (work_id, pmid, doi, openalex_id, title, year, journal, icite_rcr, citation_count,
     _snapshot, nih_percentile, apt, is_clinical, citations_per_year, is_retracted, alias_dois)
SELECT l.work_id, CAST(l.pmid AS VARCHAR), l.doi, l.oa_id,
       l.title, l.year, l.journal, ic.rcr, l.cited_by_count, current_date,
       ic.nih_percentile, ic.apt, ic.is_clinical, ic.citations_per_year, l.is_retracted,
       (SELECT list(DISTINCT a.doi ORDER BY a.doi) FROM works_alt_dois a WHERE a.work_id = l.oa_id)
FROM linked l
LEFT JOIN lake.icite.metadata ic ON ic.pmid = l.pmid;
"""

# Distinct citing patents per linked OpenAlex work; reliance.patent_citations.work_id is
# the same OpenAlex id as dim_work.openalex_id. 0 = no patent cites it; NULL = no
# OpenAlex id (iCite-fallback works) or the step failed.
_WORK_PATENTS_SQL = """
UPDATE bi.dim_work d SET n_patent_citations = COALESCE(p.n, 0)
FROM linked l
LEFT JOIN (
    SELECT work_id, count(DISTINCT patent) AS n
    FROM lake.reliance.patent_citations
    WHERE work_id IN (SELECT oa_id FROM linked)
    GROUP BY work_id
) p ON p.work_id = l.oa_id
WHERE d.work_id = l.work_id AND l.oa_id IS NOT NULL;
"""

# NOTE (contract): reporter.publink.project_number is a *core* project number —
# it joins reporter.projects.core_project_num, NOT project_num. Verified against
# the lake; worth a versioned-view alias upstream.
_GRANT_DIM_SQL = """
INSERT OR REPLACE INTO bi.dim_grant
    (grant_id, agency, project_num, fy, title, ic_name, fy_first, fy_last,
     org_name, org_country, pi_names)
SELECT grant_id, agency, project_num, fy, title, ic_name, fy_first, fy_last,
       org_name, org_country, pi_names
FROM (
    SELECT pr.core_project_num AS grant_id, pr.admin_ic AS agency,
           pr.project_num AS project_num, pr.fiscal_year AS fy, pr.project_title AS title,
           pr.ic_name AS ic_name,
           min(pr.fiscal_year) OVER (PARTITION BY pr.core_project_num) AS fy_first,
           max(pr.fiscal_year) OVER (PARTITION BY pr.core_project_num) AS fy_last,
           pr.org_name AS org_name, pr.org_country AS org_country, pr.pi_names AS pi_names,
           -- parent award rows (no subproject_id) first; sub-project titles such as
           -- "Project-002" only when a core project has no parent row at all
           row_number() OVER (
               PARTITION BY pr.core_project_num
               ORDER BY (pr.subproject_id IS NULL) DESC, pr.fiscal_year DESC NULLS LAST
           ) rn
    FROM lake.reporter.projects pr
    WHERE pr.core_project_num IN (
        SELECT pl.project_number
        FROM linked l JOIN lake.reporter.publink pl ON pl.pmid = l.pmid
    )
) WHERE rn = 1;
"""

# Bridged grants the lake has no projects row for: keep a dim_grant row (agency from
# the core number's IC letters, e.g. U41HG004059 -> HG) so marts have no orphan grants.
_GRANT_STUB_SQL = """
INSERT INTO bi.dim_grant (grant_id, agency)
SELECT DISTINCT grant_id,
       NULLIF(regexp_extract(grant_id, '^[A-Z][0-9]{2}([A-Z]{2})[0-9]+', 1), '')
FROM bi.bridge_work_grant
WHERE grant_id NOT IN (SELECT grant_id FROM bi.dim_grant);
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
SELECT DISTINCT l.work_id AS cited_work_id,
       -- PMID, else DOI, else the OpenAlex id: ~some citing works carry neither,
       -- and a NULL here aborted the whole 1.29B-row scan (2026-10-06).
       COALESCE(CAST(citing.pmid AS VARCHAR), citing.doi, citing.id) AS citing_work_id,
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

# Funders/awards of every enriched work, rebuilt whole. A work's funders without an award
# row get a bridge row with a NULL award; an award names its own funder (which OpenAlex
# lists on the work too), so the funder-only branch skips funders already carried by an award.
_BRIDGE_FUNDER_SQL = """
INSERT INTO bi.bridge_work_funder
SELECT DISTINCT work_id, funder_id, award_id, funder_award_id, 'openalex' FROM (
    SELECT w.work_id, COALESCE(a.funder_id, f.funder_id) AS funder_id,
           a.award_id, a.funder_award_id
    FROM bi.dim_work w
    JOIN lake.openalex.works_awards a ON a.work_id = w.openalex_id
    LEFT JOIN lake.openalex.works_funders f
      ON f.work_id = a.work_id AND f.funder_id = a.funder_id
    UNION ALL
    SELECT w.work_id, f.funder_id, NULL, NULL
    FROM bi.dim_work w
    JOIN lake.openalex.works_funders f ON f.work_id = w.openalex_id
    WHERE NOT EXISTS (SELECT 1 FROM lake.openalex.works_awards a
                      WHERE a.work_id = f.work_id AND a.funder_id = f.funder_id)
) WHERE funder_id IS NOT NULL;
"""

# OpenAlex funders merge into dim_funder: Authors@R-declared funders (extract_people)
# already hold the id with their curated name, which stays; the registry ids are added.
_FUNDER_DIM_SQL = """
INSERT INTO bi.dim_funder (funder_id, name, curated, ror, crossref_id, country_code)
SELECT b.funder_id, COALESCE(any_value(f.display_name), b.funder_id), false,
       any_value(f.ror), any_value(f.crossref_id), any_value(f.country_code)
FROM (SELECT DISTINCT funder_id FROM bi.bridge_work_funder) b
LEFT JOIN lake.openalex.funders f ON f.id = b.funder_id
GROUP BY b.funder_id
ON CONFLICT (funder_id) DO UPDATE SET ror = excluded.ror, crossref_id = excluded.crossref_id,
                                      country_code = excluded.country_code;
"""

# Each package's confident primary works with a live OpenAlex id: this run's `linked`, never
# a stored dim_work.openalex_id, which can be stale, and a stale id's `cites:` filter
# returns 0, not an error (#95). Same set as the package_pubs_confident view. A bridge row
# keyed by a DOI OpenAlex merged into the work (a citation_file preprint DOI) matches
# through works_alt_dois, as in _LINKED_SQL (#117).
_REACH_WORKS_SQL = """
SELECT b.package_name, b.repo, list_sort(list(DISTINCT l.oa_id)) AS oa_ids
FROM bi.bridge_package_pub b
JOIN linked l ON b.work_id = CAST(l.pmid AS VARCHAR) OR b.work_id = l.doi
  OR b.work_id IN (SELECT a.doi FROM works_alt_dois a WHERE a.work_id = l.oa_id)
WHERE b.role = 'primary' AND b.match_method IN ('doi', 'doi_alias', 'citation_file')
  AND l.oa_id IS NOT NULL
GROUP BY b.package_name, b.repo
ORDER BY b.package_name, b.repo;
"""

# Citing-work funders join dim_funder so mart_funder_region can group them (#91). A curated
# or already-enriched row keeps its name/curated flag; registry fields fill in, never blank out.
_REACH_FUNDER_DIM_SQL = """
INSERT INTO bi.dim_funder (funder_id, name, curated, ror, crossref_id, country_code)
SELECT r.key, COALESCE(any_value(f.display_name), any_value(r.key_name), r.key), false,
       any_value(f.ror), any_value(f.crossref_id), any_value(f.country_code)
FROM (SELECT DISTINCT key, key_name FROM bi.fact_package_reach
      WHERE _snapshot = current_date AND dimension = 'funder' AND key IS NOT NULL) r
LEFT JOIN reach_funder f ON f.id = r.key
GROUP BY r.key
ON CONFLICT (funder_id) DO UPDATE SET
    ror = COALESCE(excluded.ror, ror),
    crossref_id = COALESCE(excluded.crossref_id, crossref_id),
    country_code = COALESCE(excluded.country_code, country_code);
"""

# Award detail (#90) for every award on bridge_work_funder, rebuilt whole. Funder and award
# number come from the bridge (they are the award entity's own); /awards adds the detail. A
# stub is an award known only from a publication's acknowledgement: an acknowledgement
# provenance, no /awards record at all (merged or withdrawn id) or one with no provenance, or
# a record with no title, dates, amount or DOI, so a provenance OpenAlex adds later still
# reads as a stub (#104).
_AWARD_DIM_SQL = """
INSERT INTO bi.dim_award
SELECT b.award_id, b.funder_id, b.funder_award_id, a.title, a.funder_scheme,
       a.start_date, a.end_date, a.amount, a.currency, a.amount_usd, a.doi, a.provenance,
       a.id IS NULL OR a.provenance IS NULL
           OR a.provenance IN ('crossref_work_funders', 'europepmc_work_funders',
                               'datacite_work_funders', 'crossref_work.grants')
           OR (a.title IS NULL AND a.start_date IS NULL AND a.end_date IS NULL
               AND a.amount IS NULL AND a.doi IS NULL) AS is_stub
FROM (SELECT award_id, min(funder_id) AS funder_id, min(funder_award_id) AS funder_award_id
      FROM bi.bridge_work_funder WHERE award_id IS NOT NULL GROUP BY award_id) b
LEFT JOIN lake.openalex.awards a ON a.id = b.award_id;
"""

# A work's spine id changes when a source learns or corrects its PMID (DOI -> PMID for
# 23 works, PMID -> PMID for one, when the API replaced the lake). Re-key its cited-by
# edges via the old row's OpenAlex id or DOI, then drop dim_work rows no longer linked:
# a stale twin would double-count in the marts, which also join bridge rows on doi. A merged
# preprint row is matched by its DOI appearing among the journal work's aliases. Only rows
# _PRUNE_WORKS_SQL deletes are re-keyed: a still-linked work keeps its edges (#102).
_REKEY_EDGES_SQL = """
UPDATE bi.fact_citation_edge e SET cited_work_id = l.work_id
FROM bi.dim_work old
JOIN linked l ON old.openalex_id = l.oa_id OR old.doi = l.doi
  OR old.doi IN (SELECT a.doi FROM works_alt_dois a WHERE a.work_id = l.oa_id)
WHERE e.cited_work_id = old.work_id AND old.work_id <> l.work_id
  AND old.work_id NOT IN (SELECT work_id FROM linked);
"""

_PRUNE_WORKS_SQL = "DELETE FROM bi.dim_work WHERE work_id NOT IN (SELECT work_id FROM linked);"


def _enrich_works(con: duckdb.DuckDBPyConnection, *, patents: bool = True) -> int:
    con.execute(_WORKS_SQL)
    con.execute(_REKEY_EDGES_SQL)
    con.execute(_PRUNE_WORKS_SQL)
    if not patents:
        print("  patents: skipped (reliance.patent_citations is lake-only; use --source lake)")
        return con.execute("SELECT count(*) FROM bi.dim_work").fetchone()[0]
    # Best-effort (spec §3): patent counts never fail the works step.
    try:
        con.execute(_WORK_PATENTS_SQL)
        n_cited = con.execute(
            "SELECT count(*) FROM bi.dim_work WHERE n_patent_citations > 0"
        ).fetchone()[0]
        print(f"  works cited by patents: {n_cited}")
    except duckdb.Error as exc:
        print(f"  patents: skipped ({exc})")
    return con.execute("SELECT count(*) FROM bi.dim_work").fetchone()[0]


def _enrich_grants(con: duckdb.DuckDBPyConnection) -> int:
    # `linked` covers every bridged work, so a whole rebuild equals the scoped one for live
    # works and drops rows keyed on a superseded spine id.
    con.execute("DELETE FROM bi.bridge_work_grant WHERE source = 'reporter'")
    con.execute(_GRANT_DIM_SQL)
    con.execute(_GRANT_BRIDGE_SQL)
    n_stub = con.execute(_GRANT_STUB_SQL).fetchone()[0]
    print(f"  dim_grant stubs (no RePORTER row): {n_stub}")
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


def _enrich_funders(con: duckdb.DuckDBPyConnection) -> int:
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM bi.bridge_work_funder WHERE source = 'openalex'")
        con.execute(_BRIDGE_FUNDER_SQL)
        con.execute(_FUNDER_DIM_SQL)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return con.execute("SELECT count(*) FROM bi.bridge_work_funder").fetchone()[0]


def _enrich_reach(con: duckdb.DuckDBPyConnection) -> int:
    """fact_package_reach rows for today's snapshot (+ citing-work funders into dim_funder)."""
    packages = con.execute(_REACH_WORKS_SQL).fetchall()
    sets = {tuple(ids) for _, _, ids in packages}
    print(f"  reach: {len(packages)} packages, {len(sets)} distinct work sets "
          f"(~{2 * len(sets)} OpenAlex calls)…")
    memo: dict[tuple[str, ...], dict[str, tuple[int, list[tuple]]]] = {}
    rows: list[tuple] = []
    for pkg, repo, ids in packages:
        ids = tuple(ids)
        if ids not in memo:
            memo[ids] = {
                dim: openalex.citing_groups(ids, field)
                for dim, field in openalex.REACH_GROUP_BY.items()
            }
        res = memo[ids]
        rows.append((pkg, repo, "total", None, None, res["country"][0], len(ids)))
        for dim, (_, groups) in res.items():
            rows += [(pkg, repo, dim, key, name, n, len(ids)) for key, name, n in groups]

    funder_ids = sorted({r[3] for r in rows if r[2] == "funder" and r[3] is not None})
    funders = [
        openalex.funder_row(r)
        for r in openalex.fetch_by("funders", "openalex_id", funder_ids, openalex.FUNDER_FIELDS)
    ]

    # All fetching is done; the temp table is outside the transaction (separate catalog).
    con.execute(
        "CREATE OR REPLACE TEMP TABLE reach_funder (id VARCHAR, display_name VARCHAR, "
        "ror VARCHAR, crossref_id VARCHAR, country_code VARCHAR)"
    )
    if funders:
        con.executemany("INSERT INTO reach_funder VALUES (?, ?, ?, ?, ?)", funders)
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM bi.fact_package_reach WHERE _snapshot = current_date")
        if rows:
            con.executemany(
                "INSERT INTO bi.fact_package_reach (package_name, repo, dimension, key, key_name, "
                "n_citing, n_works, _snapshot) VALUES (?, ?, ?, ?, ?, ?, ?, current_date)",
                rows,
            )
        con.execute(_REACH_FUNDER_DIM_SQL)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(rows)


def _enrich_awards(con: duckdb.DuckDBPyConnection) -> int:
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM bi.dim_award")
        con.execute(_AWARD_DIM_SQL)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    n, n_stub = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE is_stub) FROM bi.dim_award").fetchone()
    print(f"  dim_award: {n} ({n_stub} stubs)")
    return n


def run(steps: tuple[str, ...] = DEFAULT_STEPS, source: str = "api") -> dict[str, int]:
    con = connect_with_sources(steps=steps) if source == "api" else connect_with_lake()
    counts: dict[str, int] = {}
    try:
        con.execute(_LINKED_SQL)
        n_oa = con.execute("SELECT count(*) FROM linked").fetchone()[0]
        con.execute(_LINKED_ICITE_SQL)
        n_linked = con.execute("SELECT count(*) FROM linked").fetchone()[0]
        print(f"  linked primary works: {n_linked} ({n_linked - n_oa} via iCite fallback)")
        if "works" in steps:
            counts["dim_work"] = _enrich_works(con, patents=source == "lake")
            print(f"  dim_work: {counts['dim_work']}")
        if "institutions" in steps:
            # Best-effort (spec §3): never fail the refresh on affiliations.
            try:
                counts["dim_institution"] = _enrich_institutions(con)
                print(f"  dim_institution: {counts['dim_institution']}")
            except duckdb.Error as exc:
                print(f"  institutions: skipped ({exc})")
        if "funders" in steps:
            # Best-effort (spec §3), like institutions.
            try:
                counts["bridge_work_funder"] = _enrich_funders(con)
                print(f"  bridge_work_funder: {counts['bridge_work_funder']}")
            except duckdb.Error as exc:
                print(f"  funders: skipped ({exc})")
            # Best-effort on its own: no lake.openalex.awards (API outage, or --source lake)
            # keeps last run's dim_award.
            try:
                counts["dim_award"] = _enrich_awards(con)
            except duckdb.Error as exc:
                print(f"  awards: skipped ({exc})")
        if "grants" in steps:
            counts["bridge_work_grant"] = _enrich_grants(con)
            print(f"  bridge_work_grant (reporter): {counts['bridge_work_grant']}")
        if "reach" in steps:
            if source != "api":
                print("  reach: skipped (OpenAlex group_by is api-only; use --source api)")
            elif not os.getenv("OPENALEX_API_KEY"):
                print("  reach: skipped: set OPENALEX_API_KEY in the environment "
                      "(~2 OpenAlex calls per linked package, past the keyless daily budget)")
            else:
                # Best-effort (spec §3), like institutions: fetches finish before any write.
                try:
                    counts["fact_package_reach"] = _enrich_reach(con)
                    print(f"  fact_package_reach: {counts['fact_package_reach']} rows")
                except (RuntimeError, duckdb.Error) as exc:
                    print(f"  reach: skipped ({exc})")
        if "citations" in steps:
            if source == "lake":
                print("  citations: scanning work_references (1.29B rows) — the heavy step…")
            counts["fact_citation_edge"] = _enrich_citations(con)
            print(f"  fact_citation_edge (openalex): {counts['fact_citation_edge']}")
    finally:
        con.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Enrich works/grants/citations.")
    ap.add_argument(
        "--steps", default=",".join(DEFAULT_STEPS),
        help=f"comma-separated subset of {ALL_STEPS} (default: {','.join(DEFAULT_STEPS)}; "
             "'citations' is the heavy one, opt-in; 'reach' is opt-in and needs OPENALEX_API_KEY)",
    )
    ap.add_argument(
        "--source", choices=SOURCES, default="api",
        help="api: OpenAlex/iCite/RePORTER APIs for the working set (default); "
             "lake: cdsci-lake (adds patent counts)",
    )
    args = ap.parse_args(argv)
    steps = tuple(s.strip() for s in args.steps.split(",") if s.strip())
    bad = set(steps) - set(ALL_STEPS)
    if bad:
        ap.error(f"unknown steps: {sorted(bad)}; valid: {ALL_STEPS}")
    print(f"enrich_from_lake (source={args.source}):")
    run(steps, args.source)


if __name__ == "__main__":
    main()
