"""Past-release CITATION union (#45) and the immutable-page cache (no network)."""

import httpx
import pytest

from biocintel import db, http
from biocintel.config import ReleaseConfig
from biocintel.pipeline import extract_citation_files as ecf

# edgeR's rendered citation pages (trimmed from bioconductor.org): 3.10 lists two
# DOIs, 3.16 adds the F1000Research workflow; the devel CITATION has only the 2025 paper.
EDGER_3_10 = """\
<p>Robinson MD, McCarthy DJ, Smyth GK (2010). <em>Bioinformatics</em>, <b>26</b>(1), 139-140.
doi: <a href="https://doi.org/10.1093/bioinformatics/btp616">10.1093/bioinformatics/btp616</a>.
</p>
<p>McCarthy DJ, Chen Y, Smyth GK (2012). <em>Nucleic Acids Research</em>, <b>40</b>(10).
doi: <a href="https://doi.org/10.1093/nar/gks042">10.1093/nar/gks042</a>.
</p>
"""
EDGER_3_16 = EDGER_3_10 + """\
<p>Chen Y, Lun AAT, Smyth GK (2016). <em>F1000Research</em>, <b>5</b>, 1438.
doi: <a href="https://doi.org/10.12688/f1000research.8987.2">10.12688/f1000research.8987.2</a>.
</p>
"""
EDGER_DEVEL = 'bibentry("Article", doi = "10.1093/nar/gkaf018")'


@pytest.fixture
def pages(monkeypatch):
    """Serve fixture pages by URL; anything else is a 404. Records force_cache per URL."""
    served = {
        ecf.source_url("edgeR", "inst/CITATION"): EDGER_DEVEL,
        ecf.citation_url("edgeR", "bioc", "3.10"): EDGER_3_10,
        ecf.citation_url("edgeR", "bioc", "3.16"): EDGER_3_16,
    }
    calls: dict[str, bool] = {}

    def fake_get_text(url, *, force_cache=False):
        calls[url] = force_cache
        if url not in served:
            raise http.HttpError(url, 404)
        return served[url]

    monkeypatch.setattr(ecf, "get_text", fake_get_text)
    return calls


def test_union_dedupes_and_keeps_newest_release(pages):
    source, found = ecf._citation_dois("edgeR", "bioc", ["3.16", "3.13", "3.10"])
    assert source == "inst"
    assert found == [
        ("10.1093/nar/gkaf018", "devel"),
        ("10.1093/bioinformatics/btp616", "3.16"),
        ("10.1093/nar/gks042", "3.16"),
        ("10.12688/f1000research.8987.2", "3.16"),
    ]
    # past pages are force-cached; the 3.13 page 404s and is skipped
    assert pages[ecf.citation_url("edgeR", "bioc", "3.13")] is True
    assert pages[ecf.source_url("edgeR", "inst/CITATION")] is False


def test_rows_carry_source_release_and_confidence(pages):
    result = ecf._citation_dois("edgeR", "bioc", ["3.16", "3.10"])
    description = "See <doi:10.1093/nar/gks042> and <doi:10.1186/gb-2010-11-3-r25>."
    rows = ecf.build_rows([("edgeR", "bioc", description)], [result])
    by_doi = {r[2]: r for r in rows}
    assert len(rows) == 5
    assert by_doi["10.1093/bioinformatics/btp616"] == [
        "edgeR", "bioc", "10.1093/bioinformatics/btp616", "primary", "citation_file", 0.9,
        "3.16",
    ]
    assert by_doi["10.1093/nar/gkaf018"][6] == "devel"
    # a Description DOI already found on a past page stays a citation_file row
    assert by_doi["10.1093/nar/gks042"][4:] == ["citation_file", 0.9, "3.16"]
    assert by_doi["10.1186/gb-2010-11-3-r25"][4:] == ["description_doi", 0.8, None]


def test_citation_url_uses_views_path():
    assert ecf.citation_url("ALL", "data-experiment", "3.16").endswith(
        "/packages/3.16/data/experiment/citations/ALL/citation.html"
    )


def test_past_releases_from_config(monkeypatch):
    cfg = ReleaseConfig(
        "3.23", "3.24", {"2.14": "x", "3.0": "x", "3.10": "x", "3.22": "x", "3.23": "x"}, {}
    )
    monkeypatch.setattr(ecf, "fetch_release_config", lambda: cfg)
    assert ecf.past_releases() == ["3.22", "3.10", "3.0"]


def test_force_cache_caches_200_and_404_under_no_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(http, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("BIOCINTEL_NO_CACHE", "1")
    hits: list[str] = []
    status = {"https://x/ok": 200, "https://x/gone": 404, "https://x/busy": 429}

    def fake_get(url, **_kw):
        hits.append(url)
        return httpx.Response(status[url], text="page", request=httpx.Request("GET", url))

    monkeypatch.setattr(http.httpx, "get", fake_get)
    for _ in range(2):
        assert http.get_text("https://x/ok", force_cache=True) == "page"
        with pytest.raises(http.HttpError):
            http.get_text("https://x/gone", force_cache=True)
        with pytest.raises(http.HttpError):
            http.get_text("https://x/busy", force_cache=True)
    # 200 and 404 fetched once; a 429 is never cached
    assert hits.count("https://x/ok") == 1
    assert hits.count("https://x/gone") == 1
    assert hits.count("https://x/busy") == 2
    # without force_cache, BIOCINTEL_NO_CACHE=1 still bypasses the cache
    http.get_text("https://x/ok")
    assert hits.count("https://x/ok") == 2


def test_init_schema_adds_source_release_to_existing_store():
    con = db.connect(":memory:")
    con.execute(
        "CREATE TABLE bridge_package_pub (package_name VARCHAR NOT NULL, repo VARCHAR NOT NULL, "
        "work_id VARCHAR NOT NULL, role VARCHAR, match_method VARCHAR, confidence DOUBLE)"
    )
    db.init_schema(con)
    db.init_schema(con)  # idempotent
    cols = [r[0] for r in con.execute("DESCRIBE bridge_package_pub").fetchall()]
    assert cols[-1] == "source_release"
