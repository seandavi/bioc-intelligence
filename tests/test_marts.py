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
        "SELECT n_primary_pubs, median_rcr, total_citations, n_distinct_grants_citing, "
        "n_citing_works FROM mart_package_impact WHERE package_name='limma'"
    ).fetchone()
    assert row == (1, 5.0, 99, 1, 0)  # median of one RCR=5.0; citations summed; edges 0


def test_mart_work_exports_linked_works():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute(_MART_SQL)
    row = con.execute(
        "SELECT work_id, icite_rcr, citation_count FROM mart_work WHERE work_id='W1'"
    ).fetchone()
    assert row == ("W1", 5.0, 99)


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


def test_package_impact_reads_only_latest_download_snapshot():
    # fact_download is append-only per monthly snapshot; summing every snapshot
    # would double totals on the second refresh.
    con = db.connect(":memory:")
    _fixture(con)
    con.execute(
        "INSERT INTO fact_download VALUES "
        "('limma','bioc',2026,8,100,200,'modern','2026-09-01'),"
        "('limma','bioc',2026,8,100,200,'modern','2026-10-01'),"
        "('limma','bioc',2026,9,50,80,'modern','2026-10-01')"
    )
    con.execute(_MART_SQL)
    row = con.execute(
        "SELECT total_distinct_ips, total_downloads, distinct_ips_trailing_12mo "
        "FROM mart_package_impact WHERE package_name='limma'"
    ).fetchone()
    assert row == (150, 280, 150)


def test_person_and_funder_marts():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute(
        "INSERT INTO dim_person VALUES "
        "('orcid:0000-0001-0000-0001','Jane Doe','0000-0001-0000-0001',NULL)"
    )
    con.execute("INSERT INTO dim_person VALUES ('name:bob','Bob',NULL,NULL)")
    rows = [
        ("limma", "bioc", "orcid:0000-0001-0000-0001", ["aut", "cre"]),
        ("edgeR", "bioc", "orcid:0000-0001-0000-0001", ["aut"]),
        ("edgeR", "bioc", "name:bob", ["cre"]),
    ]
    for pkg, repo, pid, roles in rows:
        con.execute(
            "INSERT INTO bridge_package_person VALUES (?, ?, ?, ?, 'authors_r')",
            [pkg, repo, pid, roles],
        )
    con.execute("INSERT INTO dim_funder VALUES ('nih-nci','NIH NCI',true)")
    con.execute(
        "INSERT INTO bridge_package_funder VALUES "
        "('limma','bioc','nih-nci','NIH NCI U24CA1','U24CA1','authors_r'), "
        "('limma','bioc','nih-nci','NCI','U24CA9','authors_r')"
    )
    con.execute(_MART_SQL)

    jane = con.execute(
        "SELECT n_packages, n_maintained, n_authored, package_names FROM mart_person "
        "WHERE name='Jane Doe'"
    ).fetchone()
    assert jane == (2, 1, 2, ["edgeR", "limma"])
    assert con.execute(
        "SELECT person_id FROM mart_package_person WHERE package_name='edgeR' AND is_maintainer"
    ).fetchall() == [("name:bob",)]

    # grant_id is set only where the declared grant is a known dim_grant core project
    funders = con.execute(
        "SELECT grant_number, grant_id FROM mart_package_funder ORDER BY grant_number"
    ).fetchall()
    assert funders == [("U24CA1", "U24CA1"), ("U24CA9", None)]
