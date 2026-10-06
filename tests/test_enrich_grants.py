"""Offline test of the enrich_from_lake `grants` step against a fake lake."""

import duckdb

from biocintel import db
from biocintel.pipeline import enrich_from_lake


def _fake_lake() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS lake")
    con.execute("ATTACH ':memory:' AS bi")
    con.execute("CREATE SCHEMA lake.reporter")
    con.execute("CREATE TABLE lake.reporter.publink (pmid BIGINT, project_number VARCHAR)")
    con.execute(
        "CREATE TABLE lake.reporter.projects (core_project_num VARCHAR, project_num VARCHAR, "
        "fiscal_year INTEGER, admin_ic VARCHAR, ic_name VARCHAR, project_title VARCHAR, "
        "subproject_id VARCHAR, org_name VARCHAR, org_country VARCHAR, pi_names VARCHAR)"
    )
    con.execute("USE bi")
    db.init_schema(con)
    con.execute("CREATE TEMP TABLE linked (work_id VARCHAR, pmid BIGINT)")
    con.execute("INSERT INTO linked VALUES ('W1', 1), ('W2', 2)")
    con.execute(
        "INSERT INTO lake.reporter.publink VALUES "
        "(1, 'U41HG004059'), (1, 'R01GM000001'), (2, 'U24CA000009'), (9, 'R01XX000000')"
    )
    con.execute(
        "INSERT INTO lake.reporter.projects VALUES "
        # U41HG004059: parent rows FY2009/2010 plus a later sub-project row
        "('U41HG004059', '5U41HG004059-02', 2010, 'HG', 'NHGRI', 'Bioconductor', NULL, "
        "'Fred Hutch', 'UNITED STATES', 'Carey, V'), "
        "('U41HG004059', '5U41HG004059-01', 2009, 'HG', 'NHGRI', 'Old parent', NULL, "
        "'Old Org', 'UNITED STATES', 'Old PI'), "
        "('U41HG004059', '5U41HG004059-03-001', 2011, 'HG', 'NHGRI', 'Project-002', 'P2', "
        "'Sub Org', 'UNITED STATES', 'Sub PI'), "
        # R01GM000001: only sub-project rows, so the fallback applies
        "('R01GM000001', '5R01GM000001-01', 2015, 'GM', 'NIGMS', 'Sub only', 'S1', "
        "'Org', 'CANADA', 'PI')"
    )
    # a bridged grant from another source that the lake has no row for
    con.execute(
        "INSERT INTO bi.bridge_work_grant (work_id, grant_id, source) "
        "VALUES ('W3', 'BADID-1', 'x')"
    )
    return con


def test_grants_prefer_parent_award_and_stub_missing():
    con = _fake_lake()
    assert enrich_from_lake._enrich_grants(con) == 3

    rows = {
        r[0]: r[1:]
        for r in con.execute(
            "SELECT grant_id, agency, title, ic_name, fy_first, fy_last, org_name, "
            "org_country, pi_names, fy FROM bi.dim_grant"
        ).fetchall()
    }
    # parent title/org/PI from the latest parent row; span covers every fiscal year
    assert rows["U41HG004059"] == (
        "HG", "Bioconductor", "NHGRI", 2009, 2011, "Fred Hutch", "UNITED STATES", "Carey, V", 2010
    )
    # no parent row: fall back to the sub-project row
    assert rows["R01GM000001"][1] == "Sub only"
    # bridged but absent from the lake: stub with agency from the id letters, no title
    assert rows["U24CA000009"] == ("CA", None, None, None, None, None, None, None, None)
    assert rows["BADID-1"][0] is None  # unparseable id (not an NIH core number) -> no agency
    assert "R01XX000000" not in rows  # publink for a work that is not linked


def test_init_schema_adds_grant_columns_to_old_store():
    con = duckdb.connect()
    con.execute("CREATE TABLE dim_grant (grant_id VARCHAR PRIMARY KEY, agency VARCHAR, "
                "project_num VARCHAR, fy INTEGER, title VARCHAR)")
    db.init_schema(con)
    cols = {r[0] for r in con.execute("DESCRIBE dim_grant").fetchall()}
    assert {"ic_name", "fy_first", "fy_last", "org_name", "org_country", "pi_names"} <= cols
