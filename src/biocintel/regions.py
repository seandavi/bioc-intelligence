"""Region groupings: country / supranational funder → named groupings (#91).

``regions.yaml`` maps ISO country codes to named groupings (EU27, Horizon Europe association,
UN M49 regions, ...) and hand-maps the supranational funders OpenAlex gives no country. The
groupings are filters for the frontend, never baked into a count. ``load_regions`` reloads the
two dims on every ``build-marts``, so a YAML edit needs no re-enrichment. ``as_of`` (the date the
lists were checked) is stamped on every ``dim_region_group`` row.
"""

from __future__ import annotations

import datetime as dt
import re
from functools import cache
from importlib import resources

import duckdb
import yaml

KINDS = ("policy", "geographic", "un_m49_region", "un_m49_subregion")

_CODE_RE = re.compile(r"^[A-Z]{2}$")
_GROUPING_RE = re.compile(r"^[a-z0-9_]+$")
_FUNDER_RE = re.compile(r"^F\d+$")


def _parse(text: str) -> dict:
    """Parse and validate regions.yaml text; raises ValueError naming the bad entry.

    Returns {"as_of": date, "groupings": {id: {"label", "kind", "countries": tuple}},
    "funders": {funder_id: country}}."""
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("regions.yaml: top level must be a mapping")
    as_of = raw.get("as_of")
    if type(as_of) is not dt.date:
        raise ValueError(f"regions.yaml: as_of must be an unquoted YYYY-MM-DD date, got {as_of!r}")
    for key in ("groupings", "supranational_funders"):
        if not isinstance(raw.get(key), list):
            raise ValueError(f"regions.yaml: {key} must be a list")
    groupings: dict[str, dict] = {}
    for g in raw["groupings"]:
        gid = _check_entry(g, "grouping", ("id", "label", "kind", "countries"))
        if not _GROUPING_RE.match(gid):
            raise ValueError(f"grouping {gid!r}: id must match {_GROUPING_RE.pattern}")
        if gid in groupings:
            raise ValueError(f"grouping {gid!r}: duplicate grouping id")
        if g["kind"] not in KINDS:
            raise ValueError(f"grouping {gid!r}: unknown kind {g['kind']!r}")
        codes = tuple(g["countries"].split())
        if not codes:
            raise ValueError(f"grouping {gid!r}: no countries")
        for code in codes:
            if not _CODE_RE.match(code):
                raise ValueError(f"grouping {gid!r}: bad country code {code!r}")
        if len(set(codes)) != len(codes):
            raise ValueError(f"grouping {gid!r}: duplicate country code")
        groupings[gid] = {"label": g["label"], "kind": g["kind"], "countries": codes}
    funders: dict[str, str] = {}
    for f in raw["supranational_funders"]:
        fid = _check_entry(f, "funder", ("id", "country"))
        if not _FUNDER_RE.match(fid):
            raise ValueError(f"funder {fid!r}: id must match {_FUNDER_RE.pattern}")
        if fid in funders:
            raise ValueError(f"funder {fid!r}: duplicate funder id")
        if not any(f["country"] in g["countries"] for g in groupings.values()):
            raise ValueError(f"funder {fid!r}: country {f['country']!r} is in no grouping")
        funders[fid] = f["country"]
    return {"as_of": as_of, "groupings": groupings, "funders": funders}


def _check_entry(entry: object, what: str, keys: tuple[str, ...]) -> str:
    """Require a mapping whose ``keys`` are all strings; return its id."""
    if not isinstance(entry, dict):
        raise ValueError(f"{what} entry {entry!r}: must be a mapping")
    for key in keys:
        if not isinstance(entry.get(key), str):
            raise ValueError(f"{what} {entry.get('id')!r}: {key} must be a string, "
                             f"got {entry.get(key)!r}")
    return entry["id"]


@cache
def _regions() -> dict:
    """The packaged regions.yaml, parsed and validated once per process."""
    return _parse(resources.files("biocintel").joinpath("regions.yaml").read_text(encoding="utf-8"))


def region_group_rows() -> list[tuple[str, str, str, str, dt.date]]:
    """dim_region_group rows: (country_code, grouping, grouping_label, grouping_kind, as_of)."""
    r = _regions()
    return sorted(
        (code, gid, g["label"], g["kind"], r["as_of"])
        for gid, g in r["groupings"].items()
        for code in g["countries"]
    )


def funder_region_rows() -> list[tuple[str, str]]:
    """dim_funder_region rows: (funder_id, grouping), each supranational funder × every
    grouping its ``country`` is in."""
    r = _regions()
    return sorted(
        (fid, gid)
        for fid, country in r["funders"].items()
        for gid, g in r["groupings"].items()
        if country in g["countries"]
    )


def load_regions(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Replace dim_region_group and dim_funder_region from regions.yaml in one transaction.
    Returns {"dim_region_group": n, "dim_funder_region": m}."""
    group_rows, funder_rows = region_group_rows(), funder_region_rows()
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM dim_region_group")
        con.execute("DELETE FROM dim_funder_region")
        con.executemany(
            "INSERT INTO dim_region_group (country_code, grouping, grouping_label, "
            "grouping_kind, as_of) VALUES (?, ?, ?, ?, ?)", group_rows)
        con.executemany("INSERT INTO dim_funder_region VALUES (?, ?)", funder_rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"dim_region_group": len(group_rows), "dim_funder_region": len(funder_rows)}
