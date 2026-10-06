"""Funder normalization for ``fnd`` entries in ``Authors@R``.

Declared funder names are free text: the Chan Zuckerberg Initiative alone appears
as ``CZI``, ``Chan Zuckerberg Initiative (CZI)`` and ``Silicon Valley Foundation
CZF2019-002443``. A small curated alias table (``funder_aliases.yaml``) maps those
variants to one id; anything it doesn't know stays its own funder, keyed by its
normalized name, so identical spellings still merge and nothing is dropped.

NIH grant numbers in a name or comment (``NIH NHGRI U24HG004059``,
``5U24HG004059-18``, ``1U01CA235487``) are reduced to the *core project number*
(``U24HG004059``), which is ``dim_grant.grant_id`` (the RePORTER
``core_project_num``), so a funder row can join the grant it names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from importlib import resources

import yaml

from .authors import normalize_name

# [type 1-9] activity code (U24, R01, UM1, RF1, K99) + IC (2 letters) + serial (6 digits)
# [-year/suffix]. Type is dropped, so "5U24HG004059-18" and "U24HG004059" both give the
# core project number.
_NIH_GRANT_RE = re.compile(
    r"\b[1-9]?([A-Z][A-Z0-9]\d[A-Z]{2}\d{6})(?:-\d{1,2}[A-Z0-9]*)?\b"
)


@dataclass(frozen=True)
class Funder:
    funder_id: str
    name: str
    curated: bool  # True when the alias table recognised it
    grant_number: str | None = None  # NIH core project number, if one was written


@cache
def _aliases() -> tuple[tuple[str, str, tuple[re.Pattern[str], ...]], ...]:
    text = resources.files("biocintel").joinpath("funder_aliases.yaml").read_text(encoding="utf-8")
    return tuple(
        (e["id"], e["name"], tuple(re.compile(p, re.IGNORECASE) for p in e["match"]))
        for e in yaml.safe_load(text)
    )


def nih_grant_numbers(*texts: str) -> list[str]:
    """NIH core project numbers found in ``texts`` (order kept, duplicates dropped)."""
    found: list[str] = []
    for text in texts:
        for m in _NIH_GRANT_RE.finditer(text or ""):
            if m.group(1) not in found:
                found.append(m.group(1))
    return found


def _match(text: str) -> tuple[str, str] | None:
    for fid, name, patterns in _aliases():
        if any(p.search(text) for p in patterns):
            return fid, name
    return None


def resolve_funder(declared: str, notes: tuple[str, ...] = ()) -> Funder:
    """Normalize one declared funder (``fnd`` person name + comment text)."""
    grants = nih_grant_numbers(declared, *notes)
    grant = grants[0] if grants else None
    hit = _match(declared) or _match(" ".join(notes))
    if hit:
        return Funder(hit[0], hit[1], True, grant)
    bare = " ".join(_NIH_GRANT_RE.sub("", declared).split()) or declared
    return Funder(f"name:{normalize_name(bare)}", bare, False, grant)
