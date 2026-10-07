"""API-backed ``lake`` catalog: the enrichment SQL's tables, filled from public APIs.

``link_works`` and ``enrich_from_lake`` read ``lake.<schema>.<table>``. Instead of
attaching cdsci-lake, :func:`connect_with_sources` attaches an in-memory ``lake`` and
fills only the tables and columns that SQL reads, for our working set (the works
linked to packages), from OpenAlex, iCite and NIH RePORTER. The SQL is unchanged.

Not covered — lake-only (``--source lake``): ``reliance.patent_citations`` (patent
counts) and ``pmc.passages`` (mention mining).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import duckdb

from ..lake import LAKE_ALIAS, LOCAL_ALIAS, ensure_local_store
from . import icite, openalex, reporter

_DDL = (
    openalex.WORKS_DDL, openalex.AUTHORSHIPS_DDL, openalex.INSTITUTIONS_DDL,
    openalex.REFERENCES_DDL, icite.METADATA_DDL, reporter.PUBLINK_DDL, reporter.PROJECTS_DDL,
)

# link_works' DOI join key, computed with the same expression its SQL uses.
_PACKAGE_DOIS_SQL = """
SELECT DISTINCT lower(regexp_replace(source_doi, '^(https?://(dx\\.)?doi\\.org/|doi:)', '', 'i'))
FROM bi.dim_package WHERE source_doi IS NOT NULL
"""

# Packages the title fallback may try: no bridge row that link_works keeps (a superset
# of the still-unlinked set, which is only known after the DOI pass).
_UNLINKED_TITLES_SQL = """
SELECT DISTINCT p.title FROM bi.dim_package p
WHERE p.title IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM bi.bridge_package_pub b
    WHERE b.package_name = p.package_name AND b.repo = p.repo
      AND b.match_method NOT IN ('doi', 'title_search'))
"""

# The works enrich_from_lake's `linked` table will hold (same join as its _LINKED_SQL).
_LINKED_KEYS_SQL = """
SELECT DISTINCT w.id, w.pmid FROM lake.openalex.works w
JOIN bi.bridge_package_pub b ON b.work_id = CAST(w.pmid AS VARCHAR) OR b.work_id = w.doi
"""


def connect_with_sources(
    *, link: bool = False, title_fallback: bool = False, steps: Iterable[str] = (),
    biocintel_path: Path | str | None = None,
) -> duckdb.DuckDBPyConnection:
    """Open a connection with the local store (``bi``) and an API-filled ``lake``.

    ``link`` fills what ``link_works`` reads; ``steps`` what those
    ``enrich_from_lake`` steps read. Every lake table exists, empty if not needed.
    """
    path = ensure_local_store(biocintel_path)
    con = duckdb.connect()
    con.execute(f"ATTACH '{path}' AS {LOCAL_ALIAS}")
    con.execute(f"ATTACH ':memory:' AS {LAKE_ALIAS}")
    for schema in ("openalex", "icite", "reporter"):
        con.execute(f"CREATE SCHEMA {LAKE_ALIAS}.{schema}")
    for ddl in _DDL:
        con.execute(ddl)
    if link:
        _fill_for_link(con, title_fallback)
    steps = tuple(steps)
    if steps:
        _fill_for_enrich(con, steps)
    return con


def _column(con: duckdb.DuckDBPyConnection, sql: str) -> list:
    return [r[0] for r in con.execute(sql).fetchall()]


def _insert(con: duckdb.DuckDBPyConnection, table: str, rows: list[tuple]) -> None:
    # ponytail: executemany is row-at-a-time; fine at our size (the citations step's
    # ~10^5–10^6 rows take a minute or two). Bulk-load via a temp file if that grows.
    if rows:
        marks = ", ".join("?" * len(rows[0]))
        con.executemany(f"INSERT INTO lake.{table} VALUES ({marks})", rows)


def _load_works(con: duckdb.DuckDBPyConnection, records: Iterable[dict]) -> None:
    """Insert works (deduplicated by id, skipping ids already loaded) + authorships."""
    have = set(_column(con, "SELECT id FROM lake.openalex.works"))
    works: dict[str, dict] = {}
    for r in records:
        oa_id = openalex.bare_id(r["id"])
        if oa_id not in have:
            works.setdefault(oa_id, r)
    _insert(con, "openalex.works", [openalex.work_row(r) for r in works.values()])
    _insert(
        con, "openalex.works_authorships",
        [row for r in works.values() for row in openalex.authorship_rows(r)],
    )


def _fill_for_link(con: duckdb.DuckDBPyConnection, title_fallback: bool) -> None:
    dois = _column(con, _PACKAGE_DOIS_SQL)
    _load_works(con, openalex.fetch_by("works", "doi", dois, openalex.WORK_FIELDS))
    if title_fallback:
        titles = _column(con, _UNLINKED_TITLES_SQL)
        print(f"  openalex: title search for {len(titles)} package titles…")
        _load_works(con, (r for t in titles for r in openalex.title_search(t)))
    print(f"  openalex: {_count(con, 'openalex.works')} works")


def _fill_for_enrich(con: duckdb.DuckDBPyConnection, steps: tuple[str, ...]) -> None:
    bridge_ids = _column(con, "SELECT DISTINCT work_id FROM bi.bridge_package_pub")
    bridge_pmids = [i for i in bridge_ids if i.isdigit()]
    bridge_dois = [i for i in bridge_ids if not i.isdigit()]
    _load_works(con, openalex.fetch_by("works", "pmid", bridge_pmids, openalex.WORK_FIELDS))
    _load_works(con, openalex.fetch_by("works", "doi", bridge_dois, openalex.WORK_FIELDS))
    if "institutions" in steps:
        # The step reads every dim_work row, not just this run's linked works.
        _load_works(con, openalex.fetch_by(
            "works", "openalex_id",
            _column(con, "SELECT DISTINCT openalex_id FROM bi.dim_work "
                         "WHERE openalex_id IS NOT NULL "
                         "AND openalex_id NOT IN (SELECT id FROM lake.openalex.works)"),
            openalex.WORK_FIELDS,
        ))
    linked = con.execute(_LINKED_KEYS_SQL).fetchall()
    print(f"  openalex: {_count(con, 'openalex.works')} works, {len(linked)} linked")

    pmids = {pmid for _, pmid in linked if pmid is not None} | {int(i) for i in bridge_pmids}
    _insert(con, "icite.metadata", [icite.metadata_row(r) for r in icite.pubs(pmids)])
    print(f"  icite: {_count(con, 'icite.metadata')} pubs")

    if "institutions" in steps:
        inst_ids = _column(
            con, "SELECT DISTINCT institution_id FROM lake.openalex.works_authorships "
                 "WHERE institution_ror IS NOT NULL",
        )
        try:
            _insert(con, "openalex.institutions", [
                openalex.institution_row(r) for r in openalex.fetch_by(
                    "institutions", "openalex_id", inst_ids, openalex.INSTITUTION_FIELDS)
            ])
            print(f"  openalex: {_count(con, 'openalex.institutions')} institutions")
        except RuntimeError as exc:
            # Best-effort (spec §3), as under the lake: with the table gone the
            # institutions step fails inside its transaction, rolls back and is skipped,
            # leaving last run's dim_institution intact.
            con.execute("DROP TABLE lake.openalex.institutions")
            print(f"  openalex: institutions unavailable ({exc})")

    if "grants" in steps:
        links = reporter.publinks(pmids)
        _insert(con, "reporter.publink", links)
        _insert(con, "reporter.projects", [
            reporter.project_row(r) for r in reporter.projects(p for _, p in links)
        ])
        print(f"  reporter: {len(links)} publinks, "
              f"{_count(con, 'reporter.projects')} project-years")

    if "citations" in steps:
        cited = sorted({oa_id for oa_id, _ in linked})
        print(f"  openalex: paging the citing works of {len(cited)} linked works…")
        refs: list[tuple] = []
        citing: list[dict] = []
        for oa_id in cited:
            for r in openalex.cited_by(oa_id):
                refs.append((openalex.bare_id(r["id"]), oa_id))
                citing.append(r)
        _insert(con, "openalex.work_references", refs)
        _load_works(con, citing)
        print(f"  openalex: {len(refs)} citation edges")


def _count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return con.execute(f"SELECT count(*) FROM lake.{table}").fetchone()[0]
