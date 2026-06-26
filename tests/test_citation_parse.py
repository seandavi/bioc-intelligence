"""Offline tests for the CITATION-page DOI/PMID parser (no network, no lake)."""

from biocintel.pipeline.extract_citation_files import parse_citation_html

# A real snippet from limma's rendered citation.html (bioconductor.org).
LIMMA_HTML = """\
<p>Ritchie ME, Phipson B, Wu D, Hu Y, Law CW, Shi W, Smyth GK (2015).
&ldquo;limma powers differential expression analyses for RNA-sequencing and
microarray studies.&rdquo;
<em>Nucleic Acids Research</em>, <b>43</b>(7), e47.
<a href="https://doi.org/10.1093/nar/gkv007">doi:10.1093/nar/gkv007</a>.
</p>
"""

# Synthetic two-citation page with a self-DOI and a PMID, to exercise edge cases.
MULTI_HTML = """\
<p>Foo A (2020). <a href="https://doi.org/10.1186/s13059-014-0550-8">doi:10.1186/s13059-014-0550-8</a>.
PMID: 25516281.</p>
<p>Bar B (2021). <a href="https://doi.org/10.1093/nar/gkaf018">doi:10.1093/nar/gkaf018</a>.</p>
<p>Landing page: <a href="https://doi.org/10.18129/B9.bioc.limma">doi:10.18129/B9.bioc.limma</a>.</p>
"""


def test_parses_single_doi():
    recs = parse_citation_html(LIMMA_HTML)
    assert [r["doi"] for r in recs] == ["10.1093/nar/gkv007"]
    assert recs[0]["pmid"] is None


def test_dedupes_repeated_doi():
    # The DOI appears twice (href + visible text) but should collapse to one record.
    recs = parse_citation_html(LIMMA_HTML)
    assert len(recs) == 1


def test_excludes_bioc_self_doi():
    recs = parse_citation_html(MULTI_HTML)
    dois = [r["doi"] for r in recs]
    assert "10.18129/B9.bioc.limma" not in dois
    assert dois == ["10.1186/s13059-014-0550-8", "10.1093/nar/gkaf018"]


def test_best_effort_pmid():
    recs = parse_citation_html(MULTI_HTML)
    # PMID is best-effort and page-wide; both records pick it up.
    assert recs[0]["pmid"] == "25516281"


def test_empty_when_no_doi():
    assert parse_citation_html("<p>No citation here.</p>") == []
