"""Offline test of the mart aggregation SQL against a tiny fixture store."""

from biocintel import db
from biocintel.pipeline.build_marts import _MART_SQL, DEFINITIONS, HONEST_VIEWS


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
    con.execute(
        "INSERT INTO dim_grant (grant_id, agency, title, ic_name, fy_first, fy_last, org_name) "
        "VALUES ('U24CA1','CA','Cancer x','National Cancer Institute',2020,2024,'Org A')"
    )
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


def test_mart_work_carries_icite_patents_and_preprint_flag():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute(
        "UPDATE dim_work SET journal='bioRxiv', nih_percentile=95.0, apt=0.75, "
        "is_clinical=false, citations_per_year=12.5, is_retracted=false, "
        "n_patent_citations=3 WHERE work_id='W1'"
    )
    con.execute("INSERT INTO dim_work (work_id, journal) VALUES ('W2', 'Nature')")
    con.execute(_MART_SQL)
    rows = con.execute(
        "SELECT work_id, nih_percentile, apt, is_clinical, citations_per_year, is_preprint, "
        "is_retracted, n_patent_citations FROM mart_work ORDER BY work_id"
    ).fetchall()
    assert rows == [
        ("W1", 95.0, 0.75, False, 12.5, True, False, 3),
        ("W2", None, None, None, None, False, None, None),
    ]


def test_grant_attribution_rolls_up_packages():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute(_MART_SQL)
    row = con.execute(
        "SELECT agency, n_packages_supported, package_names, ic_name, fy_first, fy_last, "
        "org_name FROM mart_grant_attribution WHERE grant_id='U24CA1'"
    ).fetchone()
    assert row[0] == "CA"
    assert row[1] == 1
    assert row[2] == ["limma"]
    assert row[3:] == ("National Cancer Institute", 2020, 2024, "Org A")


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
    con.execute(
        "INSERT INTO dim_funder (funder_id, name, curated) VALUES ('nih-nci','NIH NCI',true)"
    )
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


def test_work_funder_mart_matches_nih_awards_to_dim_grant_by_core_number():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute(
        "INSERT INTO dim_funder VALUES "
        "('F1','NCI',true,'https://ror.org/x','100000054','US'), "
        "('F2','Wellcome',false,NULL,NULL,'GB')"
    )
    con.execute(
        "INSERT INTO bridge_work_funder VALUES "
        "('111','F1','G1','5U24CA289073-02','openalex'), "  # type prefix + year suffix
        "('111','F1','G2','U24CA9','openalex'), "  # not in dim_grant
        "('111','F2',NULL,NULL,'openalex')"
    )
    con.execute("INSERT INTO dim_grant (grant_id) VALUES ('U24CA289073')")
    con.execute(_MART_SQL)
    assert con.execute(
        "SELECT funder_id, award_id, grant_id, ror, country_code FROM mart_work_funder "
        "ORDER BY funder_id, award_id NULLS LAST"
    ).fetchall() == [
        ("F1", "G1", "U24CA289073", "https://ror.org/x", "US"),
        ("F1", "G2", None, "https://ror.org/x", "US"),
        ("F2", None, None, None, "GB"),
    ]


def test_award_mart_one_row_per_award_with_funder_name():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute("INSERT INTO dim_funder (funder_id, name, curated) VALUES ('F1','NCI',true)")
    con.execute(
        "INSERT INTO dim_award VALUES "
        "('G1','F1','5F31CA1-02','A title','F31','2023-02-01','2026-01-31',47694.0,'USD',"
        "47694.0,NULL,'nih_exporter',false), "
        "('G2','F1','F31CA1',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'crossref_work_funders',true)"
    )
    con.execute(_MART_SQL)
    assert [r[0] for r in con.execute("DESCRIBE mart_award").fetchall()] == [
        "award_id", "funder_id", "funder_name", "funder_award_id", "title", "scheme",
        "start_date", "end_date", "amount", "currency", "amount_usd", "award_doi",
        "provenance", "is_stub",
    ]
    rows = con.execute("SELECT award_id, funder_name, title, amount, is_stub FROM mart_award "
                       "ORDER BY award_id").fetchall()
    assert rows == [("G1", "NCI", "A title", 47694.0, False), ("G2", "NCI", None, None, True)]


def test_package_work_keeps_highest_confidence_edge():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute("UPDATE dim_work SET doi='10.1/limma', title='limma paper' WHERE work_id='W1'")
    con.execute(
        "INSERT INTO bridge_package_pub "
        "(package_name, repo, work_id, role, match_method, confidence) VALUES "
        "('limma','bioc','10.1/limma','primary','citation_file',0.9), "  # same work via DOI
        "('limma','bioc','10.9/unenriched','primary','description_doi',0.8)"
    )
    con.execute(_MART_SQL)
    cols = [r[0] for r in con.execute("DESCRIBE mart_package_work").fetchall()]
    assert cols == [
        "package_name", "repo", "work_id", "doi", "pmid", "title", "year", "journal",
        "citation_count", "icite_rcr", "nih_percentile", "apt", "is_clinical",
        "citations_per_year", "is_preprint", "is_retracted", "n_patent_citations",
        "match_method", "confidence", "role",
    ]
    rows = con.execute(
        "SELECT work_id, doi, title, match_method, confidence FROM mart_package_work "
        "ORDER BY work_id"
    ).fetchall()
    assert rows == [
        ("10.9/unenriched", "10.9/unenriched", None, "description_doi", 0.8),
        ("W1", "10.1/limma", "limma paper", "doi", 1.0),
    ]


def test_package_work_reconciles_alias_doi():
    """A bridge row keyed on a preprint DOI that OpenAlex merged into the journal work lands
    on that work (#95), alongside the PMID-keyed row, as one work."""
    con = db.connect(":memory:")
    _fixture(con)
    con.execute("INSERT INTO dim_package (package_name, repo) VALUES ('HiLDA','bioc')")
    con.execute(
        "INSERT INTO dim_work (work_id, pmid, doi, title, alias_dois, citation_count, icite_rcr) "
        "VALUES ('31523512','31523512','10.7717/peerj.7557','HiLDA',['10.1101/577452'],10,2.0)"
    )
    con.execute(
        "INSERT INTO bridge_package_pub "
        "(package_name, repo, work_id, role, match_method, confidence) VALUES "
        "('HiLDA','bioc','10.1101/577452','primary','citation_file',0.9), "
        "('HiLDA','bioc','31523512','primary','doi',1.0)"
    )
    con.execute(_MART_SQL)
    assert con.execute(
        "SELECT work_id, doi, title, match_method FROM mart_package_work "
        "WHERE package_name='HiLDA'"
    ).fetchall() == [("31523512", "10.7717/peerj.7557", "HiLDA", "doi")]
    assert con.execute(
        "SELECT n_primary_pubs, total_citations, median_rcr FROM mart_package_impact "
        "WHERE package_name='HiLDA'"
    ).fetchone() == (1, 10, 2.0)  # two bridge rows, one work: counted once
    assert con.execute(
        "SELECT alias_dois FROM mart_work WHERE work_id='31523512'"
    ).fetchone() == (["10.1101/577452"],)
    cols = [r[0] for r in con.execute("DESCRIBE mart_work").fetchall()]
    assert cols[-3:] == ["is_retracted", "n_patent_citations", "alias_dois"]


def test_directory_mart_has_description_not_email():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute(_MART_SQL)
    cols = {r[0] for r in con.execute("DESCRIBE mart_package_directory").fetchall()}
    assert "description" in cols
    assert "maintainer_email" not in cols
    work_cols = {r[0] for r in con.execute("DESCRIBE mart_work").fetchall()}
    assert "title" in work_cols


def test_directory_mart_biotools_columns():
    con = db.connect(":memory:")
    _fixture(con)
    con.execute("UPDATE dim_package SET biotools_id='limma', in_elixir_rsec=TRUE")
    con.execute("INSERT INTO dim_package (package_name, repo) VALUES ('nobt','bioc')")
    con.execute(_MART_SQL)
    rows = con.execute(
        "SELECT package_name, in_elixir_rsec, biotools_id, biotools_url "
        "FROM mart_package_directory ORDER BY package_name"
    ).fetchall()
    assert rows == [
        ("limma", True, "limma", "https://bio.tools/limma"),
        ("nobt", None, None, None),
    ]


def _download_fixture(con):
    _fixture(con)
    con.execute("INSERT INTO dim_package (package_name, repo) VALUES ('edgeR','bioc')")
    # Inserted out of order; the 2026-09-01 snapshot is stale and must be ignored entirely.
    con.execute(
        "INSERT INTO fact_download VALUES "
        "('limma','bioc',2026,9,40,80,'modern','2026-10-01'),"
        "('edgeR','bioc',2026,9,100,200,'modern','2026-10-01'),"
        "('limma','bioc',2015,10,30,60,'modern','2026-10-01'),"
        "('limma','bioc',2015,9,10,20,'pre_2015_10','2026-10-01'),"
        "('edgeR','bioc',2015,10,0,0,'modern','2026-10-01'),"
        "('limma','bioc',2025,9,7,14,'modern','2026-10-01'),"
        "('limma','bioc',2026,9,999,999,'modern','2026-09-01'),"
        "('limma','bioc',2015,9,999,999,'pre_2015_10','2026-09-01')"
    )


def test_ecosystem_yearly_keeps_eras_separate():
    con = db.connect(":memory:")
    _download_fixture(con)
    con.execute(_MART_SQL)
    rows = con.execute(
        "SELECT year, methodology_era, sum_package_distinct_ips, downloads, "
        "n_packages_with_downloads "
        "FROM mart_ecosystem_downloads_yearly WHERE repo='bioc' ORDER BY year, methodology_era"
    ).fetchall()
    assert rows == [
        (2015, "modern", 30, 60, 1),  # edgeR's zero-download month is not counted
        (2015, "pre_2015_10", 10, 20, 1),
        (2025, "modern", 7, 14, 1),
        (2026, "modern", 140, 280, 2),
    ]


def test_package_downloads_monthly_is_sorted_and_latest_snapshot_only():
    con = db.connect(":memory:")
    _download_fixture(con)
    con.execute(_MART_SQL)
    rows = con.execute(
        "SELECT package_name, repo, year, month, distinct_ips FROM mart_package_downloads_monthly"
    ).fetchall()  # no ORDER BY: the stored order is what the Parquet file inherits
    assert rows == [
        ("edgeR", "bioc", 2015, 10, 0),
        ("edgeR", "bioc", 2026, 9, 100),
        ("limma", "bioc", 2015, 9, 10),
        ("limma", "bioc", 2015, 10, 30),
        ("limma", "bioc", 2025, 9, 7),
        ("limma", "bioc", 2026, 9, 40),
    ]


def test_package_impact_prior_12mo_and_usage_rank():
    con = db.connect(":memory:")
    _download_fixture(con)
    con.execute(_MART_SQL)
    rows = con.execute(
        "SELECT package_name, distinct_ips_trailing_12mo, distinct_ips_prior_12mo, "
        "usage_rank_in_repo FROM mart_package_impact ORDER BY package_name"
    ).fetchall()
    # trailing = 2025-10..2026-09; prior = 2024-10..2025-09 (2015 rows fall outside both)
    assert rows == [("edgeR", 100, 0, 1), ("limma", 40, 7, 2)]


def test_package_reach_mart_latest_snapshot_and_shares():
    con = db.connect(":memory:")
    db.init_schema(con)
    con.execute(
        "INSERT INTO fact_package_reach VALUES "
        "('limma','bioc','total',NULL,NULL,10,'2026-09-01'),"
        "('limma','bioc','country','US','United States',4,'2026-09-01'),"
        "('limma','bioc','total',NULL,NULL,20,'2026-10-01'),"
        "('limma','bioc','country','US','United States',5,'2026-10-01'),"
        "('limma','bioc','country',NULL,NULL,2,'2026-10-01'),"
        "('limma','bioc','funder','F1','Funder One',3,'2026-10-01'),"
        "('zero','bioc','total',NULL,NULL,0,'2026-10-01')"
    )
    con.execute(_MART_SQL)
    cols = [d[0] for d in con.execute("SELECT * FROM mart_package_reach").description]
    assert cols == ["package_name", "repo", "dimension", "key", "key_name", "n_citing",
                    "n_citing_total", "share_of_citing", "_snapshot"]
    rows = {
        (r[0], r[2], r[3]): r[5:8]
        for r in con.execute("SELECT * FROM mart_package_reach").fetchall()
    }
    assert {str(r[8]) for r in con.execute("SELECT * FROM mart_package_reach").fetchall()} == {
        "2026-10-01"}
    assert rows == {
        ("limma", "total", None): (20, 20, 1.0),
        ("limma", "country", "US"): (5, 20, 0.25),
        ("limma", "country", None): (2, 20, 0.1),
        ("limma", "funder", "F1"): (3, 20, 0.15),
        ("zero", "total", None): (0, 0, None),
    }


def test_definitions_explain_alias_dois_and_doi_alias():
    work = DEFINITIONS["mart_work"]["columns"]
    pkg_work = DEFINITIONS["mart_package_work"]["columns"]
    assert "NULL when OpenAlex lists none" in work["alias_dois"]
    assert "--source lake" in work["alias_dois"]
    assert "may differ from the DOI the package cites" in pkg_work["doi"]
    assert "doi_alias" in pkg_work["match_method"] and "doi_alias" in pkg_work["confidence"]
    assert "may differ" not in work["doi"]
    assert "doi_alias" in HONEST_VIEWS["package_pubs_confident"][2]
