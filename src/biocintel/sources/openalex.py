"""OpenAlex API → rows shaped like the lake's ``openalex`` tables.

Values follow the lake's projection (cdsci-lake ``sources/openalex/ingest.py``):
bare ids (``W123`` / ``I123``), bare-lowercase DOI, PMID as an integer, ROR kept as
the full ``https://ror.org/…`` URL. Set ``OPENALEX_API_KEY`` (sent as ``api_key``)
for anything beyond the keyless daily allowance; ``OPENALEX_MAILTO`` is optional.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Iterator
from urllib.parse import urlencode

from ..http import HttpError, get_text

API = "https://api.openalex.org"
BATCH = 50  # OR-values per filter
PER_PAGE = 200  # the API maximum
WORK_FIELDS = (
    "id,doi,ids,title,publication_year,primary_location,cited_by_count,is_retracted,authorships"
)
CITING_FIELDS = "id,doi,ids"
INSTITUTION_FIELDS = "id,ror,display_name,country_code,type,geo"

WORKS_DDL = """
CREATE TABLE lake.openalex.works (
    id VARCHAR, doi VARCHAR, pmid BIGINT, title VARCHAR, publication_year BIGINT,
    source_name VARCHAR, cited_by_count BIGINT, is_retracted BOOLEAN)
"""
AUTHORSHIPS_DDL = """
CREATE TABLE lake.openalex.works_authorships (
    work_id VARCHAR, author_id VARCHAR, author_name VARCHAR, author_position VARCHAR,
    is_corresponding BOOLEAN, institution_id VARCHAR, institution_ror VARCHAR,
    institution_country VARCHAR)
"""
INSTITUTIONS_DDL = """
CREATE TABLE lake.openalex.institutions (
    id VARCHAR, ror VARCHAR, display_name VARCHAR, country_code VARCHAR, type VARCHAR,
    city VARCHAR, region VARCHAR, country VARCHAR, latitude DOUBLE, longitude DOUBLE)
"""
REFERENCES_DDL = """
CREATE TABLE lake.openalex.work_references (work_id VARCHAR, referenced_work_id VARCHAR)
"""

_PMID_RE = re.compile(r"(\d+)$")


def _get(entity: str, params: dict) -> dict:
    public = f"{API}/{entity}?{urlencode(params)}"
    url = public
    if key := os.getenv("OPENALEX_API_KEY"):
        url += "&" + urlencode({"api_key": key})
    if mailto := os.getenv("OPENALEX_MAILTO"):
        url += "&" + urlencode({"mailto": mailto})
    try:
        return json.loads(get_text(url, use_cache=False))  # live data, never cached
    except (HttpError, RuntimeError) as exc:  # re-raised without the key-bearing URL
        why = f"HTTP {exc.status}" if isinstance(exc, HttpError) else "retries exhausted"
        raise RuntimeError(f"OpenAlex request failed ({why}): {public}") from None


def _paged(entity: str, params: dict) -> Iterator[dict]:
    """Every result of a query, cursor-paged at the maximum page size."""
    params = {**params, "per-page": PER_PAGE, "cursor": "*"}
    while True:
        page = _get(entity, params)
        yield from page["results"]
        cursor = page["meta"].get("next_cursor")
        # a short page is the last: skip the empty trailing call
        if not cursor or len(page["results"]) < PER_PAGE:
            return
        params["cursor"] = cursor


def fetch_by(entity: str, key: str, values: Iterable[str], select: str) -> Iterator[dict]:
    """Records whose ``key`` (``doi`` | ``pmid`` | ``openalex_id``) is any of ``values``."""
    values = sorted({str(v) for v in values})
    # ',' and '|' are the filter syntax's own separators and cannot be escaped.
    bad = [v for v in values if "," in v or "|" in v]
    if bad:
        print(f"  openalex: skipping {len(bad)} {key} value(s) containing ',' or '|': {bad[:3]}")
    values = [v for v in values if v not in bad]
    for i in range(0, len(values), BATCH):
        filt = f"{key}:{'|'.join(values[i:i + BATCH])}"
        yield from _paged(entity, {"filter": filt, "select": select})


def cited_by(oa_id: str) -> Iterator[dict]:
    """Every work citing ``oa_id`` (id, doi, ids only)."""
    return _paged("works", {"filter": f"cites:{oa_id}", "select": CITING_FIELDS})


def title_search(title: str, n: int = 25) -> list[dict]:
    """Top ``n`` title-search hits; the caller's SQL does the exact-title match."""
    query = re.sub(r"[,|]", " ", title)
    return _get(
        "works", {"filter": f"title.search:{query}", "select": WORK_FIELDS, "per-page": n}
    )["results"]


def bare_id(url: str | None) -> str | None:
    return url.rsplit("/", 1)[-1] if url else None


def work_row(r: dict) -> tuple:
    """``openalex.works`` row: (id, doi, pmid, title, publication_year, source_name,
    cited_by_count, is_retracted)."""
    pmid = _PMID_RE.search((r.get("ids") or {}).get("pmid") or "")
    source = (r.get("primary_location") or {}).get("source") or {}
    doi = r.get("doi")
    return (
        bare_id(r["id"]),
        doi.replace("https://doi.org/", "").lower() if doi else None,
        int(pmid.group(1)) if pmid else None,
        r.get("title"),
        r.get("publication_year"),
        source.get("display_name"),
        r.get("cited_by_count"),
        r.get("is_retracted"),
    )


def authorship_rows(r: dict) -> list[tuple]:
    """``openalex.works_authorships`` rows: one per (author, institution), dropping
    authors without an id and authorships without an institution, as the lake does."""
    rows = []
    for a in r.get("authorships") or []:
        author = a.get("author") or {}
        if not author.get("id"):
            continue
        for inst in a.get("institutions") or []:
            if not inst.get("id"):
                continue
            rows.append((
                bare_id(r["id"]), bare_id(author["id"]), author.get("display_name"),
                a.get("author_position"), a.get("is_corresponding"), bare_id(inst["id"]),
                inst.get("ror"), inst.get("country_code"),
            ))
    return rows


def institution_row(r: dict) -> tuple:
    """``openalex.institutions`` row."""
    geo = r.get("geo") or {}
    return (
        bare_id(r["id"]), r.get("ror"), r.get("display_name"), r.get("country_code"),
        r.get("type"), geo.get("city"), geo.get("region"), geo.get("country"),
        geo.get("latitude"), geo.get("longitude"),
    )
