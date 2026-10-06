"""Offline test of the enrich_from_lake `institutions` step against a fake lake."""

import duckdb

from biocintel import db
from biocintel.pipeline import enrich_from_lake


def _fake_lake() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS lake")
    con.execute("ATTACH ':memory:' AS bi")
    con.execute("CREATE SCHEMA lake.openalex")
    con.execute(
        "CREATE TABLE lake.openalex.works_authorships (work_id VARCHAR, author_id VARCHAR, "
        "author_name VARCHAR, author_position VARCHAR, is_corresponding BOOLEAN, "
        "institution_id VARCHAR, institution_ror VARCHAR, institution_country VARCHAR)"
    )
    con.execute(
        "CREATE TABLE lake.openalex.institutions (id VARCHAR, ror VARCHAR, display_name VARCHAR, "
        "country_code VARCHAR, type VARCHAR, city VARCHAR, region VARCHAR, country VARCHAR, "
        "latitude DOUBLE, longitude DOUBLE)"
    )
    con.execute("USE bi")
    db.init_schema(con)
    con.execute(
        "INSERT INTO bi.dim_work (work_id, openalex_id) VALUES "
        "('111', 'W1'), ('10.1/x', 'W2'), ('222', NULL)"
    )
    con.execute(
        "INSERT INTO lake.openalex.institutions VALUES "
        "('I1', 'https://ror.org/a', 'Inst A', 'US', 'education', 'Boston', 'MA', "
        "'United States', 42.3, -71.1), "
        "('I2', 'https://ror.org/b', 'Inst B', 'DE', 'facility', 'Heidelberg', NULL, "
        "'Germany', 49.4, 8.7)"
    )
    con.execute(
        "INSERT INTO lake.openalex.works_authorships VALUES "
        "('W1', 'A1', 'First', 'first', false, 'I2', 'https://ror.org/b', 'DE'), "
        "('W1', 'A2', 'Mid1', 'middle', false, 'I1', 'https://ror.org/a', 'US'), "
        "('W1', 'A3', 'Mid2', 'middle', false, 'I1', 'https://ror.org/a', 'US'), "
        "('W1', 'A4', 'Last', 'last', true, 'I1', 'https://ror.org/a', 'US'), "
        "('W2', 'A5', 'Solo', 'first', true, 'I9', 'https://ror.org/z', 'FR'), "
        "('W2', 'A6', 'NoRor', 'last', false, NULL, NULL, NULL), "
        "('W9', 'A7', 'Other', 'last', false, 'I1', 'https://ror.org/a', 'US')"
    )
    return con


def test_institutions_fill_dim_and_bridge():
    con = _fake_lake()
    # A stale row from a previous run is replaced, not kept.
    con.execute("INSERT INTO bi.dim_institution (ror, name) VALUES ('https://ror.org/old', 'Old')")

    assert enrich_from_lake._enrich_institutions(con) == 3

    dims = {
        r[0]: r[1:]
        for r in con.execute(
            "SELECT ror, openalex_id, name, country_code, country, latitude FROM bi.dim_institution"
        ).fetchall()
    }
    assert dims["https://ror.org/a"] == ("I1", "Inst A", "US", "United States", 42.3)
    assert dims["https://ror.org/b"] == ("I2", "Inst B", "DE", "Germany", 49.4)
    # Not in openalex.institutions: kept, country from the authorship.
    assert dims["https://ror.org/z"] == ("I9", None, "FR", None, None)

    bridge = sorted(
        con.execute(
            "SELECT work_id, ror, author_position, is_corresponding, source "
            "FROM bi.bridge_work_institution"
        ).fetchall()
    )
    # Two middle authors at one institution collapse; ROR-less and unlinked works drop.
    assert bridge == [
        ("10.1/x", "https://ror.org/z", "first", True, "openalex"),
        ("111", "https://ror.org/a", "last", True, "openalex"),
        ("111", "https://ror.org/a", "middle", False, "openalex"),
        ("111", "https://ror.org/b", "first", False, "openalex"),
    ]

    # Rerun is idempotent.
    assert enrich_from_lake._enrich_institutions(con) == 3
    assert con.execute("SELECT count(*) FROM bi.bridge_work_institution").fetchone()[0] == 4
