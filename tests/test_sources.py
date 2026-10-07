"""Offline tests of the API-backed ``lake`` (biocintel.sources).

Fixtures under ``fixtures/api`` are real responses recorded 2026-10-07 and trimmed:
limma (W2146512944 / PMID 25605792) and sesame's paper (W4392168904 / PMID 38407446).
"""

import json
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
        if q.path == "/institutions":
            return (FIXTURES / "openalex_institutions.json").read_text()
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


def test_enrich_all_steps_from_api(api_store):
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
    assert counts == {"dim_work": 2, "dim_institution": 6, "bridge_work_grant": 2,
                      "fact_citation_edge": 3}
    assert "openalex_id:W999" in calls
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
    assert sorted(con.execute(
        "SELECT cited_work_id, citing_work_id FROM fact_citation_edge").fetchall()) == [
        ("38407446", "38365920"), ("38407446", "38798987"), ("38407446", "40966651"),
    ]
    assert con.execute(
        "SELECT count(*) FROM bridge_work_institution WHERE work_id = '38407446'"
    ).fetchone()[0] == 2
