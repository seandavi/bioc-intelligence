"""Offline guards for enrich_from_lake: import-safety + step validation.

Importing must not require the cdsci-lake client (it is lazy in lake.py), and the
CLI must reject unknown steps.
"""

import pytest

from biocintel.pipeline import enrich_from_lake


def test_imports_without_lake_client():
    assert callable(enrich_from_lake.run)
    assert enrich_from_lake.DEFAULT_STEPS == ("works", "institutions", "grants")
    assert "citations" in enrich_from_lake.ALL_STEPS


def test_cli_rejects_unknown_step():
    with pytest.raises(SystemExit):
        enrich_from_lake.main(["--steps", "works,bogus"])


def test_icite_fallback_resolves_dois_missing_from_openalex():
    """A bridge DOI absent from openalex.works but in iCite still gets a dim_work row;
    DOIs OpenAlex already resolved are not duplicated by the fallback."""
    import duckdb

    from biocintel import db

    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS lake")
    con.execute("ATTACH ':memory:' AS bi")
    con.execute("CREATE SCHEMA lake.openalex")
    con.execute("CREATE SCHEMA lake.icite")
    con.execute(
        "CREATE TABLE lake.openalex.works (id VARCHAR, pmid BIGINT, doi VARCHAR, title VARCHAR, "
        "publication_year INTEGER, source_name VARCHAR, cited_by_count BIGINT)"
    )
    con.execute(
        "CREATE TABLE lake.icite.metadata (pmid BIGINT, doi VARCHAR, title VARCHAR, year INTEGER, "
        "journal VARCHAR, rcr DOUBLE, citation_count BIGINT)"
    )
    con.execute("USE bi")
    db.init_schema(con)
    con.execute(
        "INSERT INTO lake.openalex.works VALUES "
        "('W1', 111, '10.1/in-openalex', 'OA title', 2020, 'J1', 50)"
    )
    con.execute(
        "INSERT INTO lake.icite.metadata VALUES "
        "(111, '10.1/in-openalex', 'iCite title', 2020, 'J1', 2.0, 40), "
        "(222, '10.1/icite-only', 'Only iCite', 2012, 'J2', 9.5, 3188)"
    )
    for pkg, doi in [("pkgA", "10.1/in-openalex"), ("pkgB", "10.1/icite-only"),
                     ("pkgC", "10.1/nowhere")]:
        con.execute(
            "INSERT INTO bi.bridge_package_pub "
            "(package_name, repo, work_id, role, match_method, confidence) "
            "VALUES (?, 'bioc', ?, 'primary', 'citation_file', 0.9)",
            [pkg, doi],
        )

    con.execute(enrich_from_lake._LINKED_SQL)
    con.execute(enrich_from_lake._LINKED_ICITE_SQL)
    enrich_from_lake._enrich_works(con)

    rows = {
        r[0]: r[1:]
        for r in con.execute(
            "SELECT work_id, pmid, doi, openalex_id, title, icite_rcr, citation_count "
            "FROM bi.dim_work"
        ).fetchall()
    }
    # OpenAlex wins where it resolves: its title/count, with iCite's RCR joined on pmid.
    assert rows["111"] == ("111", "10.1/in-openalex", "W1", "OA title", 2.0, 50)
    # iCite-only work: PMID-keyed, no OpenAlex id, iCite metadata and count.
    assert rows["222"] == ("222", "10.1/icite-only", None, "Only iCite", 9.5, 3188)
    # Unresolvable DOI stays out of dim_work; no duplicates.
    assert len(rows) == 2
