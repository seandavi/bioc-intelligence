"""DOI harvesting from free text (CITATION files, rendered pages, DESCRIPTION).

One regex + normalisation shared by every extractor, so all of them emit the lake's
bare-lowercase form (``lake.openalex.works.doi``). Handled: ``doi:`` / ``doi.org``
prefixes (the match starts at ``10.``), trailing ``.,;)/`` and backticks, Markdown
``[…](…)`` wrapping, a break right after the registrant slash (BRAIN:
``10.1007/\\ns13361-…``), publisher-URL tails (``/full``, ``/abstract``, OUP's
``10.1093/<journal>/<id>/<article-no>/….pdf``) and bioRxiv version/URL suffixes
(``…v1``, ``.full``). Not handled: a break *inside* the suffix, percent-encoded
DOIs in URLs. A suffix with no digit is dropped: it is a placeholder
(``10.1101/todo``) or a DOI cut at a space (``10.1126/science. 1232542``), and the
latter resolves to the *journal's* OpenAlex record.
"""

from __future__ import annotations

import re

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>,{}\[\]`\\]+")
# Bioconductor mints a self-DOI for every package landing page; it is not a
# describing manuscript, so it never becomes a linkage.
BIOC_SELF_DOI_PREFIX = "10.18129/"
_SPLIT_RE = re.compile(r"(10\.\d{4,9}/)\s+(?=\S)")
_BIORXIV_SUFFIX_RE = re.compile(r"(v\d+)?(\.full(\.pdf)?|\.abstract)?$")
_URL_TAIL_RE = re.compile(r"/(full|abstract|e?pdf)$")


def normalize(doi: str) -> str:
    doi = _URL_TAIL_RE.sub("", doi.rstrip(".,;)/`").lower())
    # ponytail: OUP journal DOIs are <journal>/<id>; only 813 of 1.63M 10.1093 DOIs in
    # openalex.works have more segments (reference works, not papers packages cite).
    if doi.startswith("10.1093/"):
        doi = "/".join(doi.split("/")[:3])
    if doi.startswith("10.1101/"):
        doi = _BIORXIV_SUFFIX_RE.sub("", doi)
    return doi


def find_dois(text: str | None) -> list[str]:
    """Distinct normalised DOIs in ``text``, first appearance first, self-DOIs dropped."""
    if not text:
        return []
    out: list[str] = []
    for m in DOI_RE.finditer(_SPLIT_RE.sub(r"\1", text)):
        doi = normalize(m.group(0))
        suffix = doi.split("/", 1)[1]
        if (
            not doi.startswith(BIOC_SELF_DOI_PREFIX)
            and any(ch.isdigit() for ch in suffix)
            and doi not in out
        ):
            out.append(doi)
    return out
