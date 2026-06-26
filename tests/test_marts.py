"""Offline test of the mart aggregation SQL against a tiny fixture store."""

from biocintel import db
from biocintel.pipeline.build_marts import _MART_SQL


def _fixture(con):
    db.init_schema(con)
    con.execute(
        "INSERT INTO dim_package (package_name, repo, latest_release, title, biocviews, url) "
        "VALUES ('limma','bioc','3.23','LM for microarrays',['GeneExpression'],['http://x'])"
    )
    con.execute(
        "INSERT INTO dim_package_version (package_name, repo, version, bioc_release, in_devel) "
        "VALUES ('limma','bioc','3.60.0','3.23',false)"
    )
    con.execute(
        "INSERT INTO bridge_package_pub "
        "(package_name, repo, work_id, role, match_method, confidence) "
        "VALUES ('limma','bioc','W1','primary','doi',1.0)"
    )
    con.execute(
        "INSERT INTO dim_work (work_id, pmid, icite_rcr, citation_count) "
        "VALUES ('W1','123',5.0,99)"
    )
    con.execute("INSERT INTO dim_grant (grant_id, agency, title) VALUES ('U24CA1','CA','Cancer x')")
    con.execute(
        "INSERT INTO bridge_work_grant (work_id, grant_id, source) "
        "VALUES ('W1','U24CA1','reporter')"
    )


def test_package_impact_aggregates_enrichment():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute(_MART_SQL)
    row = con.execute(
        "SELECT n_primary_pubs, sum_rcr, n_distinct_grants_citing, n_citing_works "
        "FROM mart_package_impact WHERE package_name='limma'"
    ).fetchone()
    assert row == (1, 5.0, 1, 0)  # citations not loaded → 0


def test_grant_attribution_rolls_up_packages():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute(_MART_SQL)
    row = con.execute(
        "SELECT agency, n_packages_supported, package_names FROM mart_grant_attribution "
        "WHERE grant_id='U24CA1'"
    ).fetchone()
    assert row[0] == "CA"
    assert row[1] == 1
    assert row[2] == ["limma"]


def test_directory_mart_has_all_packages():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute(_MART_SQL)
    assert con.execute("SELECT count(*) FROM mart_package_directory").fetchone()[0] == 1
