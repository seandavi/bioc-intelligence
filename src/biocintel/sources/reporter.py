"""NIH RePORTER v2 API → rows shaped like the lake's ``reporter.publink`` / ``projects``.

The lake loads RePORTER's ExPORTER CSVs; this mirrors their value formats:
``publink.project_number`` is the *core* project number, ``admin_ic`` the two-letter
IC code, ``ic_name`` upper-case, and ``pi_names`` ``LAST, FIRST MIDDLE (contact)``
joined by ``;``. ``projects/search`` by core number returns every fiscal year,
sub-projects included, so ``fy_first``/``fy_last`` and the parent-row preference work.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator

from ..http import post_json

API = "https://api.reporter.nih.gov/v2"
PAGE = 500  # the API maximum
MAX_RESULTS = 15_000  # "Maximum offset is 14,999": a bigger search must be split
PMID_BATCH = 200
PROJECT_BATCH = 50  # a P30 cancer center alone has ~1k sub-project rows
_PAUSE = 1.0  # RePORTER asks for at most ~1 request per second
_PROJECT_FIELDS = [
    "CoreProjectNum", "ProjectNum", "FiscalYear", "AgencyIcAdmin", "ProjectTitle",
    "SubprojectId", "Organization", "PrincipalInvestigators",
]

PUBLINK_DDL = "CREATE TABLE lake.reporter.publink (pmid BIGINT, project_number VARCHAR)"
PROJECTS_DDL = """
CREATE TABLE lake.reporter.projects (
    core_project_num VARCHAR, project_num VARCHAR, fiscal_year INTEGER, admin_ic VARCHAR,
    ic_name VARCHAR, project_title VARCHAR, subproject_id VARCHAR, org_name VARCHAR,
    org_country VARCHAR, pi_names VARCHAR)
"""


class TooManyResults(RuntimeError):
    """A search past the API's offset ceiling; raised before any result is yielded."""


def _search(endpoint: str, criteria: dict, **extra) -> Iterator[dict]:
    offset = 0
    while True:
        time.sleep(_PAUSE)
        page = post_json(
            f"{API}/{endpoint}/search",
            {"criteria": criteria, "offset": offset, "limit": PAGE, **extra},
        )
        if page["meta"]["total"] > MAX_RESULTS:
            raise TooManyResults(f"{endpoint}: {page['meta']['total']} results for {criteria}")
        yield from page["results"]
        offset += PAGE
        if offset >= page["meta"]["total"]:
            return


def publinks(pmids: Iterable[int]) -> list[tuple]:
    """Distinct ``reporter.publink`` rows (pmid, core project number) for ``pmids``."""
    pmids = sorted(set(pmids))
    rows = set()
    for i in range(0, len(pmids), PMID_BATCH):
        for r in _search("publications", {"pmids": pmids[i:i + PMID_BATCH]}):
            if r.get("coreproject"):
                rows.add((r["pmid"], r["coreproject"]))
    return sorted(rows)


def projects(core_nums: Iterable[str]) -> Iterator[dict]:
    """Every fiscal-year row (sub-projects included) of each core project."""
    cores = sorted(set(core_nums))
    for i in range(0, len(cores), PROJECT_BATCH):
        yield from _projects(cores[i:i + PROJECT_BATCH])


def _projects(cores: list[str]) -> Iterator[dict]:
    try:
        yield from _search("projects", {"project_nums": cores}, include_fields=_PROJECT_FIELDS)
    except TooManyResults:
        if len(cores) == 1:
            raise
        half = len(cores) // 2
        yield from _projects(cores[:half])
        yield from _projects(cores[half:])


def pi_names(pis: list[dict] | None) -> str | None:
    names = [
        f"{p.get('last_name') or ''}, {p.get('first_name') or ''} {p.get('middle_name') or ''}"
        .upper() + (" (contact)" if p.get("is_contact_pi") else "")
        for p in pis or []
    ]
    return ";".join(names) or None


def project_row(r: dict) -> tuple:
    """``reporter.projects`` row."""
    ic = r.get("agency_ic_admin") or {}
    org = r.get("organization") or {}
    sub = r.get("subproject_id")
    return (
        r.get("core_project_num"), r.get("project_num"), r.get("fiscal_year"), ic.get("code"),
        (ic.get("name") or "").upper() or None, r.get("project_title"),
        str(sub) if sub is not None else None, org.get("org_name"), org.get("org_country"),
        pi_names(r.get("principal_investigators")),
    )
