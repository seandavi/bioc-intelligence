"""Offline tests of the API-backed ``lake`` (biocintel.sources).

Fixtures under ``fixtures/api`` are real responses recorded 2026-10-07 and trimmed:
limma (W2146512944 / PMID 25605792) and sesame's paper (W4392168904 / PMID 38407446).
``openalex_reach_countries.json`` and ``openalex_reach_funders.json`` (recorded 2026-10-23, #92)
are the ``group_by`` responses for the works citing sesame's paper, trimmed to ``meta.count``,
``meta.groups_count`` and ``group_by``.
``openalex_awards.json`` was recorded 2026-10-23, with two ids relabelled to the works
fixture's ``G111``/``G222``.
``openalex_works_merged.json`` (HiLDA's PeerJ paper, W2970457274, which carries the merged
bioRxiv preprint 10.1101/577452 in its locations) was recorded 2026-10-23.
"""

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from biocintel import http, lake
from biocintel.pipeline import enrich_from_lake, link_works
from biocintel.sources import icite, openalex, reporter

FIXTURES = Path(__file__).parent / "fixtures" / "api"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_openalex_work_row_matches_lake_formats():
    rows = [openalex.work_row(r) for r in _fixture("openalex_works.json")["results"]]
    assert rows == [
        ("W2146512944", "10.1093/nar/gkv007", 25605792,
         "limma powers differential expression analyses for RNA-sequencing and microarray "
         "studies", 2015, "Nucleic Acids Research", 44804, False),
        ("W4392168904", "10.1093/nar/gkae127", 38407446,
         "Low-input and single-cell methods for Infinium DNA methylation BeadChips", 2024,
         "Nucleic Acids Research", 26, False),
    ]


def test_openalex_alt_doi_rows_lists_other_location_dois():
    merged = _fixture("openalex_works_merged.json")["results"][0]
    assert openalex.alt_doi_rows(merged) == [("W2970457274", "10.1101/577452")]
    assert all(openalex.alt_doi_rows(r) == [] for r in _fixture("openalex_works.json")["results"])


def test_openalex_authorship_rows_one_per_institution_dropping_missing_ids():
    limma = _fixture("openalex_works.json")["results"][0]
    limma["authorships"] += [
        {"author_position": "last", "is_corresponding": True,
         "author": {"id": None, "display_name": "No id"},
         "institutions": [{"id": "https://openalex.org/I1", "ror": None}]},
        {"author_position": "last", "is_corresponding": True,
         "author": {"id": "https://openalex.org/A9", "display_name": "No affiliation"},
         "institutions": []},
    ]
    assert openalex.authorship_rows(limma) == [
        ("W2146512944", "A5015434839", "Matthew E. Ritchie", "first", False, "I165779595",
         "https://ror.org/01ej9dk98", "AU"),
        ("W2146512944", "A5015434839", "Matthew E. Ritchie", "first", False, "I196021976",
         "https://ror.org/01b6kha49", "AU"),
        ("W2146512944", "A5027183726", "Belinda Phipson", "middle", False, "I1321649718",
         "https://ror.org/02rktxt32", "AU"),
        ("W2146512944", "A5027183726", "Belinda Phipson", "middle", False, "I4210150290",
         "https://ror.org/048fyec77", "AU"),
    ]


def test_openalex_institution_row_flattens_geo():
    upenn = _fixture("openalex_institutions.json")["results"][0]
    assert openalex.institution_row(upenn) == (
        "I79576946", "https://ror.org/00b30xv10", "University of Pennsylvania", "US",
        "education", "Philadelphia", "Pennsylvania", "United States", 39.95238, -75.16362,
    )


def test_openalex_fetch_by_batches_pages_and_skips_separators(monkeypatch, capsys):
    calls = []

    def fake_get(entity, params):
        calls.append(dict(params))
        n = len(params["filter"].split("|"))
        # first batch: a full page, then a short one; later batches fit in one page
        full = params["cursor"] == "*" and len(calls) == 1
        return {"meta": {"next_cursor": "c2" if full else "c3"},
                "results": [{"id": f"W{i}"} for i in range(200 if full else n)]}

    monkeypatch.setattr(openalex, "_get", fake_get)
    values = [f"10.1/{i:03d}" for i in range(120)] + ["10.1/a,b", "10.1/a|b"]
    got = list(openalex.fetch_by("works", "doi", values, "id"))
    assert "skipping 2 doi value(s)" in capsys.readouterr().out
    # 120 values -> batches of 50/50/20; the first batch paged once more on its cursor
    assert [len(c["filter"].split("|")) for c in calls] == [50, 50, 50, 20]
    assert [c["cursor"] for c in calls] == ["*", "c2", "*", "*"]
    assert all(c["per-page"] == 200 and c["select"] == "id" for c in calls)
    assert len(got) == 200 + 50 + 50 + 20


def test_openalex_award_row_normalizes_doi_and_dates():
    wellcome, full, stub = (
        openalex.award_row(r) for r in _fixture("openalex_awards.json")["results"])
    assert wellcome == (
        "G7004411822",
        "Understanding the genetic basis of common human diseases: core funding for the "
        "Wellcome Trust Centre for Human Genetics.", "Cellular and Molecular Neuroscience",
        date(2011, 4, 1), date(2016, 11, 30), 11000000.0, "GBP", 17646171.3, "10.35802/090532",
        "crossref_work")
    assert full[:2] == ("G111", "Advancing Epigenetic Sequencing Through Solid-Phase Enzymatic "
                                "Approaches")
    assert stub == ("G222", None, None, None, None, None, None, None, None,
                    "crossref_work_funders")
    assert openalex._date("2023") is None and openalex._date(None) is None


def test_openalex_awards_filter_needs_full_urls(monkeypatch):
    calls = []

    def fake_get(entity, params):
        calls.append((entity, params))
        return {"meta": {"next_cursor": None}, "results": []}

    monkeypatch.setattr(openalex, "_get", fake_get)
    assert list(openalex.awards(["G2", "G1"])) == []
    [(entity, params)] = calls
    assert entity == "awards"
    assert params["filter"] == "id:https://openalex.org/G1|https://openalex.org/G2"
    assert params["select"] == openalex.AWARD_FIELDS


def test_openalex_api_key_is_sent_but_never_in_errors(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "sekrit")
    seen = []

    def fake_get_text(url, **_kw):
        seen.append(url)
        raise http.HttpError(url, 429)

    monkeypatch.setattr(openalex, "get_text", fake_get_text)
    with pytest.raises(RuntimeError) as exc:
        openalex.cited_by("W1").__next__()
    assert "api_key=sekrit" in seen[0]
    assert "sekrit" not in str(exc.value) and "HTTP 429" in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_openalex_citing_groups_parses_keys_and_unknown(monkeypatch):
    urls = []
    bodies = iter(["openalex_reach_countries.json", "openalex_reach_funders.json"])

    def fake_get_text(url, **_kw):
        urls.append(url)
        return (FIXTURES / next(bodies)).read_text()

    monkeypatch.setattr(openalex, "get_text", fake_get_text)
    n, countries = openalex.citing_groups(["W1", "W2"], "authorships.countries")
    q = parse_qs(urlparse(urls[0]).query)
    assert q["filter"] == ["cites:W1|W2"] and q["per-page"] == ["200"]
    assert q["group_by"] == ["authorships.countries:include_unknown"]
    assert n == 24 and len(countries) == 17
    assert countries[0] == ("US", "United States", 13)
    assert (None, None, 2) in countries

    n, funders = openalex.citing_groups(["W1"], "funders.id")
    assert n == 24 and len(funders) == 31
    assert ("F4320332161", "National Institutes of Health", 7) in funders
    assert funders[0] == (None, None, 8)
    assert not any("openalex.org" in (k or "") for k, _, _ in funders)


def test_icite_metadata_row_renames_rcr_and_lowercases_doi():
    r = dict(_fixture("icite_pubs.json")["data"][1], doi="10.1093/NAR/gkae127")
    assert icite.metadata_row(r) == (
        38407446, "10.1093/nar/gkae127",
        "Low-input and single-cell methods for Infinium DNA methylation BeadChips.", 2024,
        "Nucleic Acids Res", 2.7796244681886857, 82.2, 21, 10.5, False, 0.25,
    )


def test_reporter_project_row_matches_exporter_formats():
    row = reporter.project_row(_fixture("reporter_projects.json")["results"][0])
    assert row == (
        "F31HG012892", "5F31HG012892-02", 2024, "HG",
        "NATIONAL HUMAN GENOME RESEARCH INSTITUTE",
        "Advancing Epigenetic Sequencing Through Solid-Phase Enzymatic Approaches", None,
        "UNIVERSITY OF PENNSYLVANIA", "UNITED STATES", "LOO, CHRISTIAN ETHAN (contact)",
    )
    # multi-PI, as ExPORTER renders it in the lake (empty middle name -> double space)
    assert reporter.pi_names([
        {"last_name": "Morgan", "first_name": "Martin", "middle_name": "T",
         "is_contact_pi": False},
        {"last_name": "Waldron", "first_name": "Levi", "middle_name": None,
         "is_contact_pi": True},
    ]) == "MORGAN, MARTIN T;WALDRON, LEVI  (contact)"
    assert reporter.project_row({"subproject_id": 6128})[6] == "6128"


def test_reporter_search_pages_by_offset_and_publinks_dedupe(monkeypatch):
    monkeypatch.setattr(reporter, "_PAUSE", 0)
    bodies = []

    def fake_post(url, body):
        bodies.append(body)
        assert url.endswith("/publications/search")
        page = [{"coreproject": "R01X", "pmid": 1, "applid": i} for i in range(2)]
        if body["offset"]:
            page = [{"coreproject": "U24Y", "pmid": 2, "applid": 9},
                    {"coreproject": None, "pmid": 3, "applid": 8}]
        return {"meta": {"total": 503}, "results": page}

    monkeypatch.setattr(reporter, "post_json", fake_post)
    assert reporter.publinks([2, 1, 2]) == [(1, "R01X"), (2, "U24Y")]
    assert [b["offset"] for b in bodies] == [0, 500]
    assert bodies[0]["criteria"] == {"pmids": [1, 2]} and bodies[0]["limit"] == 500


def test_reporter_projects_split_a_batch_past_the_offset_ceiling(monkeypatch):
    monkeypatch.setattr(reporter, "_PAUSE", 0)
    sizes = {"P30A": 9_000, "P30B": 9_000, "R01C": 3}
    asked = []

    def fake_post(_url, body):
        cores = body["criteria"]["project_nums"]
        asked.append(cores)
        total = sum(sizes[c] for c in cores)
        return {"meta": {"total": total},
                "results": [{"core_project_num": c} for c in cores][: body["limit"]]}

    monkeypatch.setattr(reporter, "post_json", fake_post)
    monkeypatch.setattr(reporter, "PAGE", 10_000)  # one page per search
    got = [r["core_project_num"] for r in reporter.projects(["R01C", "P30A", "P30B"])]
    # 18,003 > 15,000: split into [P30A] and [P30B, R01C]; nothing duplicated
    assert asked == [["P30A", "P30B", "R01C"], ["P30A"], ["P30B", "R01C"]]
    assert got == ["P30A", "P30B", "R01C"]


@pytest.fixture
def api_store(monkeypatch, tmp_path):
    """A local store plus every API client served from the recorded fixtures."""
    from biocintel import db

    path = tmp_path / "bi.duckdb"
    monkeypatch.setattr(lake, "DB_PATH", path)
    monkeypatch.setattr(reporter, "_PAUSE", 0)
    calls: list[str] = []

    def fake_openalex(url, **_kw):
        q = urlparse(url)
        filt = parse_qs(q.query)["filter"][0]
        calls.append(filt)
        if group_by := parse_qs(q.query).get("group_by"):
            name = "countries" if group_by[0].startswith("authorships.countries") else "funders"
            return (FIXTURES / f"openalex_reach_{name}.json").read_text()
        if q.path == "/institutions":
            return (FIXTURES / "openalex_institutions.json").read_text()
        if q.path == "/funders":
            return (FIXTURES / "openalex_funders.json").read_text()
        if q.path == "/awards":
            return (FIXTURES / "openalex_awards.json").read_text()
        if filt.startswith("cites:"):
            if filt == "cites:W4392168904":
                return (FIXTURES / "openalex_cites.json").read_text()
            return json.dumps({"meta": {"next_cursor": None}, "results": []})
        return (FIXTURES / "openalex_works.json").read_text()  # any doi/pmid/id batch

    def fake_post(url, _body):
        name = "reporter_projects" if url.endswith("/projects/search") else "reporter_publications"
        return _fixture(f"{name}.json")

    monkeypatch.setattr(openalex, "get_text", fake_openalex)
    monkeypatch.setattr(icite, "get_text", lambda url, **_: (FIXTURES / "icite_pubs.json")
                        .read_text())
    monkeypatch.setattr(reporter, "post_json", fake_post)

    con = db.connect(path)
    db.init_schema(con)
    yield con, calls
    con.close()


def test_link_works_from_api(api_store):
    con, calls = api_store
    con.execute(
        "INSERT INTO dim_package (package_name, repo, title, source_doi) VALUES "
        "('limma', 'bioc', 'Linear Models for Microarray Data', 'https://doi.org/10.1093/NAR/gkv007'),"
        "('nodoi', 'bioc', 'No DOI, at all', NULL),"
        "('sesame', 'bioc', 'Low-input and single-cell methods for Infinium DNA methylation "
        "BeadChips', NULL)"
    )
    con.close()
    assert link_works.run(source="api") == {"doi": 1}
    assert calls == ["doi:10.1093/nar/gkv007"]
    calls.clear()
    assert link_works.run(title_fallback=True, source="api") == {"doi": 1, "title_search": 1}
    # ',' is the filter separator, so it is blanked out of the search text
    assert "title.search:No DOI  at all" in calls
    con = lake.db.connect(lake.DB_PATH)
    assert sorted(con.execute(
        "SELECT package_name, work_id, match_method, confidence FROM bridge_package_pub"
    ).fetchall()) == [
        ("limma", "25605792", "doi", 1.0), ("sesame", "38407446", "title_search", 0.4),
    ]


def test_enrich_all_steps_from_api(api_store, capsys):
    con, calls = api_store
    con.execute(
        "INSERT INTO bridge_package_pub (package_name, repo, work_id, role, match_method, "
        "confidence) VALUES ('limma', 'bioc', '10.1093/nar/gkv007', 'primary', "
        "'citation_file', 0.9), ('sesame', 'bioc', '38407446', 'primary', 'doi', 1.0)"
    )
    # an enriched work from an earlier run that is no longer linked: the works step prunes it
    con.execute("INSERT INTO dim_work (work_id, openalex_id) VALUES ('old', 'W999')")
    con.close()

    counts = enrich_from_lake.run(enrich_from_lake.ALL_STEPS, source="api")
    assert counts == {"dim_work": 2, "dim_institution": 6, "bridge_work_funder": 3,
                      "dim_award": 2, "bridge_work_grant": 2, "fact_citation_edge": 3}
    assert "1 of 1 stored work ids no longer resolve" in capsys.readouterr().out
    assert "openalex_id:W999" in calls
    assert "id:https://openalex.org/G111|https://openalex.org/G222" in calls
    assert {"cites:W2146512944", "cites:W4392168904"} <= set(calls)

    con = lake.db.connect(lake.DB_PATH)
    works = {r[0]: r[1:] for r in con.execute(
        "SELECT work_id, doi, openalex_id, journal, icite_rcr, citation_count, nih_percentile, "
        "n_patent_citations FROM dim_work").fetchall()}
    assert works["25605792"] == ("10.1093/nar/gkv007", "W2146512944", "Nucleic Acids Research",
                                 1116.534080823251, 44804, 100.0, None)
    assert works["38407446"][1:5] == ("W4392168904", "Nucleic Acids Research",
                                      2.7796244681886857, 26)
    grants = {r[0]: r[1:] for r in con.execute(
        "SELECT grant_id, agency, fy_first, fy_last, ic_name, pi_names FROM dim_grant"
    ).fetchall()}
    assert grants["F31HG012892"] == (
        "HG", 2023, 2024, "NATIONAL HUMAN GENOME RESEARCH INSTITUTE",
        "LOO, CHRISTIAN ETHAN (contact)",
    )
    assert grants["R35GM146978"] == ("GM", None, None, None, None)  # publink, no project row
    # funders/awards (#85): the funder-only CZI row has no award; NHGRI carries two award ids
    assert sorted(con.execute(
        "SELECT work_id, funder_id, award_id, funder_award_id, source FROM bridge_work_funder"
    ).fetchall(), key=str) == [
        ("38407446", "F4320315474", None, None, "openalex"),
        ("38407446", "F4320337348", "G111", "5F31HG012892-02", "openalex"),
        ("38407446", "F4320337348", "G222", "F31HG012892", "openalex"),
    ]
    assert con.execute(
        "SELECT name, ror, crossref_id, country_code, curated FROM dim_funder "
        "WHERE funder_id = 'F4320337348'"
    ).fetchall() == [("National Human Genome Research Institute", "https://ror.org/00baak391",
                      "100000051", "US", False)]
    # award detail (#90): G7004411822 is on no linked work, so it never reaches dim_award
    assert con.execute(
        "SELECT award_id, funder_id, funder_award_id, title IS NULL, scheme, start_date, "
        "amount, provenance, is_stub FROM dim_award ORDER BY award_id"
    ).fetchall() == [
        ("G111", "F4320337348", "5F31HG012892-02", False, "F31", date(2023, 2, 1), 47694.0,
         "nih_exporter", False),
        ("G222", "F4320337348", "F31HG012892", True, None, None, None,
         "crossref_work_funders", True),
    ]
    assert sorted(con.execute(
        "SELECT cited_work_id, citing_work_id FROM fact_citation_edge").fetchall()) == [
        ("38407446", "38365920"), ("38407446", "38798987"), ("38407446", "40966651"),
    ]
    assert con.execute(
        "SELECT count(*) FROM bridge_work_institution WHERE work_id = '38407446'"
    ).fetchone()[0] == 2


def _serve_merged_preprint(monkeypatch):
    """OpenAlex serves HiLDA's journal work for its preprint DOI or PMID, nothing else."""
    merged = (FIXTURES / "openalex_works_merged.json").read_text()

    def fake_openalex(url, **_kw):
        filt = parse_qs(urlparse(url).query)["filter"][0]
        if "10.1101/577452" in filt or "31523512" in filt:
            return merged
        return json.dumps({"meta": {"next_cursor": None}, "results": []})

    monkeypatch.setattr(openalex, "get_text", fake_openalex)


def test_link_works_links_preprint_doi_merged_into_journal_work(api_store, monkeypatch):
    con, _ = api_store
    con.execute(
        "INSERT INTO dim_package (package_name, repo, source_doi) "
        "VALUES ('HiLDA', 'bioc', 'https://doi.org/10.1101/577452')"
    )
    con.close()
    _serve_merged_preprint(monkeypatch)
    assert link_works.run(source="api") == {"doi": 1}
    con = lake.db.connect(lake.DB_PATH)
    assert con.execute(
        "SELECT package_name, work_id, match_method, confidence FROM bridge_package_pub"
    ).fetchall() == [("HiLDA", "31523512", "doi", 1.0)]


def test_enrich_relinks_preprint_doi_merged_into_journal_work(api_store, monkeypatch, capsys):
    con, _ = api_store
    con.execute(
        "INSERT INTO bridge_package_pub (package_name, repo, work_id, role, match_method, "
        "confidence) VALUES ('HiLDA', 'bioc', '10.1101/577452', 'primary', 'citation_file', 0.9)"
    )
    con.execute(
        "INSERT INTO dim_work (work_id, doi, openalex_id) "
        "VALUES ('10.1101/577452', '10.1101/577452', 'W2921099115')"
    )
    con.execute(
        "INSERT INTO fact_citation_edge (cited_work_id, citing_work_id, source, mention_type) "
        "VALUES ('10.1101/577452', '99', 'openalex', 'formal')"
    )
    con.execute(
        "INSERT INTO bridge_work_grant (work_id, grant_id, source) "
        "VALUES ('10.1101/577452', 'X01', 'reporter')"
    )
    con.close()
    _serve_merged_preprint(monkeypatch)

    enrich_from_lake.run(("works", "grants"), source="api")

    out = capsys.readouterr().out
    assert "1 of 1 stored work ids no longer resolve" in out and "W2921099115" in out
    con = lake.db.connect(lake.DB_PATH)
    assert con.execute(
        "SELECT work_id, pmid, doi, openalex_id, journal, alias_dois FROM dim_work"
    ).fetchall() == [("31523512", "31523512", "10.7717/peerj.7557", "W2970457274", "PeerJ",
                      ["10.1101/577452"])]
    assert con.execute("SELECT cited_work_id FROM fact_citation_edge").fetchall() == [
        ("31523512",)]
    assert con.execute(
        "SELECT count(*) FROM bridge_work_grant WHERE work_id = '10.1101/577452'"
    ).fetchone() == (0,)


def _seed_bridge(con):
    con.execute(
        "INSERT INTO bridge_package_pub (package_name, repo, work_id, role, match_method, "
        "confidence) VALUES ('limma', 'bioc', '10.1093/nar/gkv007', 'primary', "
        "'citation_file', 0.9), ('sesame', 'bioc', '38407446', 'primary', 'doi', 1.0)"
    )


def test_api_failure_aborts_before_touching_the_store(api_store, monkeypatch):
    """A failed fetch must fail the run, never leave a partial working set that the works
    step's pruning would then use to delete good rows."""
    con, _ = api_store
    _seed_bridge(con)
    con.execute("INSERT INTO dim_work (work_id, title) VALUES ('25605792', 'kept')")
    con.close()

    def boom(url, **_kw):
        raise http.HttpError(url, 500)

    monkeypatch.setattr(openalex, "get_text", boom)
    with pytest.raises(RuntimeError, match="OpenAlex request failed"):
        enrich_from_lake.run(("works",), source="api")
    con = lake.db.connect(lake.DB_PATH)
    assert con.execute("SELECT work_id, title FROM dim_work").fetchall() == [("25605792", "kept")]


def test_institutions_outage_skips_only_that_step(api_store, monkeypatch):
    """Institutions stay best-effort under the API: an /institutions failure keeps last
    run's dim_institution and the other steps still land."""
    con, _ = api_store
    _seed_bridge(con)
    con.execute("INSERT INTO dim_institution (ror, name) VALUES ('https://ror.org/x', 'kept')")
    con.close()

    real = openalex.get_text

    def flaky(url, **kw):
        if urlparse(url).path == "/institutions":
            raise http.HttpError(url, 500)
        return real(url, **kw)

    monkeypatch.setattr(openalex, "get_text", flaky)
    counts = enrich_from_lake.run(("works", "institutions", "grants"), source="api")
    assert "dim_institution" not in counts and counts["dim_work"] == 2
    con = lake.db.connect(lake.DB_PATH)
    assert con.execute("SELECT ror, name FROM dim_institution").fetchall() == [
        ("https://ror.org/x", "kept")]


def test_funders_outage_skips_only_that_step(api_store, monkeypatch):
    """Funders are best-effort, like institutions: a /funders failure keeps last run's
    dim_funder and the other steps still land."""
    con, _ = api_store
    _seed_bridge(con)
    con.close()
    real = openalex.get_text

    def flaky(url, **kw):
        if urlparse(url).path == "/funders":
            raise http.HttpError(url, 500)
        return real(url, **kw)

    monkeypatch.setattr(openalex, "get_text", flaky)
    counts = enrich_from_lake.run(("works", "funders"), source="api")
    assert "bridge_work_funder" not in counts and counts["dim_work"] == 2


def _seed_reach_bridge(con):
    con.execute(
        "INSERT INTO bridge_package_pub (package_name, repo, work_id, role, match_method, "
        "confidence) VALUES "
        "('limma', 'bioc', '10.1093/nar/gkv007', 'primary', 'citation_file', 0.9),"
        "('sesame', 'bioc', '38407446', 'primary', 'doi', 1.0),"
        "('pair', 'bioc', '10.1093/nar/gkv007', 'primary', 'doi', 1.0),"
        "('pair', 'bioc', '38407446', 'primary', 'doi', 1.0),"
        "('sesame2', 'bioc', '38407446', 'primary', 'citation_file', 0.9),"
        "('notconf', 'bioc', '38407446', 'primary', 'description_doi', 0.6)"
    )
    # a stale stored id: reach must use this run's live ids, never this one
    con.execute("INSERT INTO dim_work (work_id, openalex_id) VALUES ('38407446', 'Wstale')")
    con.execute(
        "INSERT INTO dim_funder VALUES ('F4320337348', 'NHGRI (declared)', true, NULL, NULL, NULL)"
    )
    con.execute(
        "INSERT INTO fact_package_reach VALUES "
        "('old', 'bioc', 'total', NULL, NULL, 5, '2026-09-01')"
    )


def test_enrich_reach_from_api(api_store, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "k")
    con, calls = api_store
    _seed_reach_bridge(con)
    con.close()

    counts = enrich_from_lake.run(("reach",), source="api")
    assert counts["fact_package_reach"] == 4 * 49
    assert "cites:W2146512944|W4392168904" in calls
    # the #95 stale-id check may fetch Wstale; reach queries must not
    assert not any(c.startswith("cites:") and "Wstale" in c for c in calls)
    assert calls.count("cites:W4392168904") == 2  # sesame + sesame2 share one pair of calls

    con = lake.db.connect(lake.DB_PATH)
    per_package = con.execute(
        "SELECT package_name, count(*) FILTER (dimension = 'total' AND key IS NULL "
        "AND n_citing = 24), count(*) FILTER (dimension = 'country'), "
        "count(*) FILTER (dimension = 'funder'), count(*) FILTER (_snapshot = current_date) "
        "FROM fact_package_reach WHERE _snapshot > '2026-09-01' GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert per_package == [
        ("limma", 1, 17, 31, 49), ("pair", 1, 17, 31, 49),
        ("sesame", 1, 17, 31, 49), ("sesame2", 1, 17, 31, 49),
    ]
    assert con.execute(
        "SELECT name, curated, country_code FROM dim_funder WHERE funder_id = 'F4320320300'"
    ).fetchall() == [("European Commission", False, None)]
    assert con.execute(
        "SELECT name, curated, country_code, ror FROM dim_funder WHERE funder_id = 'F4320337348'"
    ).fetchall() == [("NHGRI (declared)", True, "US", "https://ror.org/00baak391")]
    con.close()

    # same-day rerun is idempotent; the older snapshot survives both runs
    enrich_from_lake.run(("reach",), source="api")
    con = lake.db.connect(lake.DB_PATH)
    assert con.execute("SELECT count(*) FROM fact_package_reach").fetchone()[0] == 4 * 49 + 1
    assert con.execute(
        "SELECT count(*) FROM fact_package_reach WHERE _snapshot = '2026-09-01'"
    ).fetchone()[0] == 1


def test_reach_skips_without_api_key(api_store, monkeypatch, capsys):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    con, calls = api_store
    _seed_reach_bridge(con)
    con.close()
    counts = enrich_from_lake.run(("reach",), source="api")
    assert "fact_package_reach" not in counts
    assert "set OPENALEX_API_KEY" in capsys.readouterr().out
    assert not any(c.startswith("cites:") for c in calls)


def test_reach_outage_keeps_last_snapshot(api_store, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "k")
    con, _ = api_store
    _seed_reach_bridge(con)
    con.close()
    real = openalex.get_text

    def flaky(url, **kw):
        if "group_by" in url:
            raise http.HttpError(url, 500)
        return real(url, **kw)

    monkeypatch.setattr(openalex, "get_text", flaky)
    counts = enrich_from_lake.run(("works", "reach"), source="api")
    assert "fact_package_reach" not in counts and counts["dim_work"] == 2
    con = lake.db.connect(lake.DB_PATH)
    assert con.execute("SELECT package_name FROM fact_package_reach").fetchall() == [("old",)]
    assert con.execute("SELECT funder_id FROM dim_funder").fetchall() == [("F4320337348",)]


def test_awards_missing_from_openalex_are_stub_rows(api_store, monkeypatch):
    con, _ = api_store
    _seed_bridge(con)
    con.close()
    real = openalex.get_text

    def no_awards(url, **kw):
        if urlparse(url).path == "/awards":
            return json.dumps({"meta": {"next_cursor": None}, "results": []})
        return real(url, **kw)

    monkeypatch.setattr(openalex, "get_text", no_awards)
    assert enrich_from_lake.run(("works", "funders"), source="api")["dim_award"] == 2
    con = lake.db.connect(lake.DB_PATH)
    assert con.execute(
        "SELECT award_id, funder_id, funder_award_id, provenance, is_stub FROM dim_award "
        "ORDER BY award_id"
    ).fetchall() == [
        ("G111", "F4320337348", "5F31HG012892-02", None, True),
        ("G222", "F4320337348", "F31HG012892", None, True),
    ]


def test_awards_outage_skips_only_that_step(api_store, monkeypatch):
    """/awards is best-effort on its own: an outage keeps last run's dim_award while the
    funders bridge still lands."""
    con, _ = api_store
    _seed_bridge(con)
    con.execute("INSERT INTO dim_award (award_id, funder_id, is_stub) VALUES ('Gold', 'F1', true)")
    con.close()
    real = openalex.get_text

    def flaky(url, **kw):
        if urlparse(url).path == "/awards":
            raise http.HttpError(url, 500)
        return real(url, **kw)

    monkeypatch.setattr(openalex, "get_text", flaky)
    counts = enrich_from_lake.run(("works", "funders"), source="api")
    assert "bridge_work_funder" in counts and "dim_award" not in counts
    con = lake.db.connect(lake.DB_PATH)
    assert con.execute("SELECT award_id FROM dim_award").fetchall() == [("Gold",)]


