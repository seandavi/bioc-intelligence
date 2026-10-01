"""Offline tests for CITATION / CITATION.cff / free-text DOI harvesting (no network)."""

from biocintel.doi import find_dois
from biocintel.pipeline.extract_citation_files import parse_cff

# A real snippet from limma's rendered citation.html (bioconductor.org).
LIMMA_HTML = """\
<p>Ritchie ME, Phipson B, Wu D, Hu Y, Law CW, Shi W, Smyth GK (2015).
&ldquo;limma powers differential expression analyses for RNA-sequencing and
microarray studies.&rdquo;
<em>Nucleic Acids Research</em>, <b>43</b>(7), e47.
<a href="https://doi.org/10.1093/nar/gkv007">doi:10.1093/nar/gkv007</a>.
</p>
<p>Landing page: <a href="https://doi.org/10.18129/B9.bioc.limma">doi:10.18129/B9.bioc.limma</a>.</p>
"""

# ANCOMBC's inst/CITATION (trimmed): the DOI lives only in textVersion, which the
# rendered citation.html drops.
ANCOMBC_CITATION = """\
citEntry(
  entry    = "Article",
  title    = "Analysis of compositions of microbiomes with bias correction",
  journal  = "Nature Communications",
  url      = "https://www.nature.com/articles/s41467-020-17041-7",
  textVersion = paste(
    "Lin, H., & Peddada, S. D. (2020). Analysis of compositions of microbiomes with bias correction.
    Nature Communications, 11(1), 1-11, https://doi.org/10.1038/s41467-020-17041-7"
  )
)
"""

# BRAIN's inst/CITATION (trimmed): a DOI split across a line break after the slash,
# and a ``doi: `` prefix with a space.
BRAIN_CITATION = """\
textVersion = paste("... JASMS, 2012, doi:10.1007/
s13361-011-0326-2", sep=""))
textVersion = paste("... Anal Chem., 2013, doi: 10.1021/ac303439m", sep=""))
"""

# GEOquery's CITATION.cff (trimmed): the references are dependency DOIs.
GEOQUERY_CFF = """\
cff-version: 1.2.0
title: 'GEOquery: Get data from NCBI Gene Expression Omnibus (GEO)'
doi: 10.1093/bioinformatics/btm254
preferred-citation:
  type: article
  doi: 10.1093/bioinformatics/btm254
references:
- type: software
  title: 'R: A Language and Environment for Statistical Computing'
- type: software
  title: httr
  doi: 10.32614/CRAN.package.httr
"""


def test_rendered_page_doi_deduped_and_self_doi_excluded():
    assert find_dois(LIMMA_HTML) == ["10.1093/nar/gkv007"]


def test_doi_only_in_textversion():
    assert find_dois(ANCOMBC_CITATION) == ["10.1038/s41467-020-17041-7"]


def test_split_doi_and_spaced_prefix():
    assert find_dois(BRAIN_CITATION) == ["10.1007/s13361-011-0326-2", "10.1021/ac303439m"]


def test_bibentry_doi_field():
    assert find_dois('doi = "10.1093/bioinformatics/bty129"') == ["10.1093/bioinformatics/bty129"]


def test_trailing_junk_and_case():
    text = (
        "see `10.1186/S13059-014-0550-8`; and (doi:10.1093/NAR/gkaf018). "
        "doi={10.1093/bioinformatics/btz196} https://doi.org/10.1038/nmeth.3317/"
    )
    assert find_dois(text) == [
        "10.1186/s13059-014-0550-8", "10.1093/nar/gkaf018",
        "10.1093/bioinformatics/btz196", "10.1038/nmeth.3317",
    ]


def test_biorxiv_version_suffix():
    text = "https://www.biorxiv.org/content/10.1101/2020.06.01.127985v2.full"
    assert find_dois(text) == ["10.1101/2020.06.01.127985"]


def test_publisher_url_tails_and_markdown():
    text = (
        "https://academic.oup.com/nar/article/doi/10.1093/nar/gkac030/42342374/gkac030.pdf "
        "https://onlinelibrary.wiley.com/doi/10.1111/biom.12257/full "
        "[10.1038/nature25501](https://doi.org/10.1038/nature25501) <doi:10.1200/CCI.18.00102]>"
    )
    assert find_dois(text) == [
        "10.1093/nar/gkac030", "10.1111/biom.12257", "10.1038/nature25501",
        "10.1200/cci.18.00102",
    ]


def test_description_doi_markup():
    desc = "Implements the method of Smith et al. (2020) <doi:10.1093/biostatistics/kxz001>."
    assert find_dois(desc) == ["10.1093/biostatistics/kxz001"]


def test_digitless_suffix_dropped():
    # BasicSTARRseq's Description: a space inside the DOI would otherwise link the journal.
    text = "Science. 2013;339(6123):1074-7. doi: 10.1126/science. 1232542. and 10.1101/todo"
    assert find_dois(text) == []


def test_cff_ignores_references():
    assert parse_cff(GEOQUERY_CFF) == ["10.1093/bioinformatics/btm254"]


def test_cff_garbage_is_empty():
    assert parse_cff("just a string") == []
    assert parse_cff("key: [unclosed") == []


def test_empty_when_no_doi():
    assert find_dois("<p>No citation here.</p>") == []
    assert find_dois(None) == []
