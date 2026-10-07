"""NIH iCite API → rows shaped like the lake's ``icite.metadata``.

The API looks up by PMID only: ``dois=`` / ``doi=`` are silently ignored (verified
2026-10-07), so a DOI with no PMID in OpenAlex cannot reach iCite this way.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from urllib.parse import urlencode

from ..http import get_text

API = "https://icite.od.nih.gov/api/pubs"
BATCH = 200  # the documented 1000 is a GET URL too long for the server (HTTP 413)
FIELDS = (
    "pmid,doi,title,year,journal,relative_citation_ratio,nih_percentile,citation_count,"
    "citations_per_year,is_clinical,apt"
)

METADATA_DDL = """
CREATE TABLE lake.icite.metadata (
    pmid BIGINT, doi VARCHAR, title VARCHAR, year INTEGER, journal VARCHAR, rcr DOUBLE,
    nih_percentile DOUBLE, citation_count BIGINT, citations_per_year DOUBLE,
    is_clinical BOOLEAN, apt DOUBLE)
"""


def pubs(pmids: Iterable[int]) -> Iterator[dict]:
    pmids = sorted(set(pmids))
    for i in range(0, len(pmids), BATCH):
        query = urlencode(
            {"pmids": ",".join(map(str, pmids[i:i + BATCH])), "fl": FIELDS}, safe=","
        )
        yield from json.loads(get_text(f"{API}?{query}"))["data"]


def metadata_row(r: dict) -> tuple:
    """``icite.metadata`` row; the API's ``relative_citation_ratio`` is the lake's ``rcr``."""
    return (
        r["pmid"], (r.get("doi") or "").lower() or None, r.get("title"), r.get("year"),
        r.get("journal"), r.get("relative_citation_ratio"), r.get("nih_percentile"),
        r.get("citation_count"), r.get("citations_per_year"), r.get("is_clinical"),
        r.get("apt"),
    )
