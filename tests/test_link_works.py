from biocintel.pipeline.link_works import normalize_doi


def test_normalize_strips_prefixes_and_lowercases():
    assert normalize_doi("https://doi.org/10.3389/Fmolb.2016.00026") == "10.3389/fmolb.2016.00026"
    assert normalize_doi("http://dx.doi.org/10.1093/BIOMET/asp023") == "10.1093/biomet/asp023"
    assert normalize_doi("doi:10.1016/J.SNB.2017.06.180") == "10.1016/j.snb.2017.06.180"
    assert normalize_doi("10.1136/heartjnl-2017-311295") == "10.1136/heartjnl-2017-311295"


def test_normalize_handles_empty():
    assert normalize_doi(None) is None
    assert normalize_doi("") is None
    assert normalize_doi("   ") is None
