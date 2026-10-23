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
from collections.abc import Iterable, Iterator, Sequence
from datetime import date
from urllib.parse import urlencode

from ..http import HttpError, get_text

API = "https://api.openalex.org"
BATCH = 50  # OR-values per filter
PER_PAGE = 200  # the API maximum
WORK_FIELDS = (
    "id,doi,ids,title,publication_year,primary_location,cited_by_count,is_retracted,authorships,"
    "funders,awards,locations"
)
CITING_FIELDS = "id,doi,ids"
INSTITUTION_FIELDS = "id,ror,display_name,country_code,type,geo"
FUNDER_FIELDS = "id,display_name,ids,country_code"
AWARD_FIELDS = (
    "id,display_name,funder_scheme,start_date,end_date,amount,currency,amount_usd,doi,provenance"
)

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
WORKS_FUNDERS_DDL = """
CREATE TABLE lake.openalex.works_funders (work_id VARCHAR, funder_id VARCHAR, ror VARCHAR)
"""
WORKS_AWARDS_DDL = """
CREATE TABLE lake.openalex.works_awards (
    work_id VARCHAR, award_id VARCHAR, funder_award_id VARCHAR, funder_id VARCHAR)
"""
FUNDERS_DDL = """
CREATE TABLE lake.openalex.funders (
    id VARCHAR, display_name VARCHAR, ror VARCHAR, crossref_id VARCHAR, country_code VARCHAR)
"""
AWARDS_DDL = """
CREATE TABLE lake.openalex.awards (
    id VARCHAR, title VARCHAR, funder_scheme VARCHAR, start_date DATE, end_date DATE,
    amount DOUBLE, currency VARCHAR, amount_usd DOUBLE, doi VARCHAR, provenance VARCHAR)
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
    """Records whose ``key`` (``doi`` | ``pmid`` | ``openalex_id`` | ``id``
    for ``/awards``, full URLs) is any of ``values``."""
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


# Reach dimensions (#92) -> OpenAlex group_by field.
REACH_GROUP_BY = {"country": "authorships.countries", "funder": "funders.id"}


def citing_groups(oa_ids: Sequence[str], group_by: str) -> tuple[int, list[tuple]]:
    """Works citing any of ``oa_ids`` (one OR'd filter, so distinct citing works), grouped by
    ``group_by``: ``(meta.count, [(key, key_name, count), ...])``. At most 200 groups, the
    largest first (no paging). The unknown group comes back as ``(None, None, count)``."""
    # ponytail: no length guard; a package has at most 10 works and OpenAlex allows 100 OR values
    page = _get("works", {
        "filter": "cites:" + "|".join(oa_ids),
        "group_by": f"{group_by}:include_unknown",
        "per-page": PER_PAGE,
    })
    groups = []
    for g in page["group_by"]:
        key = bare_id(g["key"])
        if key.lower() == "unknown":
            groups.append((None, None, g["count"]))
        else:
            groups.append((key, g.get("key_display_name"), g["count"]))
    return page["meta"]["count"], groups


def awards(ids: Iterable[str]) -> Iterator[dict]:
    """Award records for bare ``G…`` ids. /awards has no ``openalex_id`` filter, and its
    ``id`` filter needs full URLs: bare ids silently match nothing. Missing ids are absent."""
    return fetch_by("awards", "id", (f"https://openalex.org/{g}" for g in ids), AWARD_FIELDS)


def title_search(title: str, n: int = 25) -> list[dict]:
    """Top ``n`` title-search hits; the caller's SQL does the exact-title match."""
    query = re.sub(r"[,|]", " ", title)
    return _get(
        "works", {"filter": f"title.search:{query}", "select": WORK_FIELDS, "per-page": n}
    )["results"]


def bare_id(url: str | None) -> str | None:
    return url.rsplit("/", 1)[-1] if url else None


def bare_doi(url: str | None) -> str | None:
    return url.replace("https://doi.org/", "").lower() if url else None


def work_row(r: dict) -> tuple:
    """``openalex.works`` row: (id, doi, pmid, title, publication_year, source_name,
    cited_by_count, is_retracted)."""
    pmid = _PMID_RE.search((r.get("ids") or {}).get("pmid") or "")
    source = (r.get("primary_location") or {}).get("source") or {}
    return (
        bare_id(r["id"]),
        bare_doi(r.get("doi")),
        int(pmid.group(1)) if pmid else None,
        r.get("title"),
        r.get("publication_year"),
        source.get("display_name"),
        r.get("cited_by_count"),
        r.get("is_retracted"),
    )


def alt_doi_rows(r: dict) -> list[tuple]:
    """(work_id, doi) per distinct location DOI other than the work's own doi (e.g. the bioRxiv
    preprint OpenAlex merged into its journal version)."""
    dois = {bare_doi(loc.get("doi")) for loc in r.get("locations") or []}
    return [(bare_id(r["id"]), d) for d in sorted(dois - {None, bare_doi(r.get("doi"))})]


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


def funder_rows(r: dict) -> list[tuple]:
    """``openalex.works_funders`` rows: (work_id, funder_id, ror), one per funder."""
    return [
        (bare_id(r["id"]), bare_id(f["id"]), f.get("ror"))
        for f in r.get("funders") or [] if f.get("id")
    ]


def award_rows(r: dict) -> list[tuple]:
    """``openalex.works_awards`` rows: (work_id, award_id, funder_award_id, funder_id)."""
    return [
        (bare_id(r["id"]), bare_id(a["id"]), a.get("funder_award_id"), bare_id(a.get("funder_id")))
        for a in r.get("awards") or [] if a.get("id")
    ]


def _date(s: str | None) -> date | None:
    """ISO ``YYYY-MM-DD`` (the /awards format), else None rather than failing the insert."""
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def award_row(r: dict) -> tuple:
    """``openalex.awards`` row: (id, title, funder_scheme, start_date, end_date, amount,
    currency, amount_usd, doi, provenance). DOI bare-lowercase, as for works."""
    doi = r.get("doi")
    return (
        bare_id(r["id"]), r.get("display_name"), r.get("funder_scheme"),
        _date(r.get("start_date")), _date(r.get("end_date")), r.get("amount"),
        r.get("currency"), r.get("amount_usd"),
        doi.replace("https://doi.org/", "").lower() if doi else None, r.get("provenance"),
    )


def funder_row(r: dict) -> tuple:
    """``openalex.funders`` row: (id, display_name, ror, crossref_id, country_code)."""
    ids = r.get("ids") or {}
    return (
        bare_id(r["id"]), r.get("display_name"), ids.get("ror"), ids.get("crossref"),
        r.get("country_code"),
    )
