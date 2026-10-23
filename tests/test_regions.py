"""Region groupings (#91): the packaged regions.yaml and the two marts built from it."""

import datetime
import re

import pytest

from biocintel import db, regions
from biocintel.pipeline.build_marts import _MART_SQL

EU27 = set(
    "AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split()
) | {"EU"}


def _members():
    out: dict[str, set[str]] = {}
    for code, grouping, *_ in regions.region_group_rows():
        out.setdefault(grouping, set()).add(code)
    return out


def test_country_codes_are_strings_and_norway_survives_yaml():
    rows = regions.region_group_rows()
    assert len(rows) == 604
    assert all(re.fullmatch(r"[A-Z]{2}", code) for code, *_ in rows)
    assert len({g for _, g, *_ in rows}) == 26
    assert len({c for c, *_ in rows}) == 250
    assert "NO" in _members()["horizon_associated"]
    assert "NO" in _members()["europe_geographic"]


def test_eu27_is_the_member_states_plus_eu_code():
    assert _members()["eu27"] == EU27
    assert not {"GB", "CH", "NO"} & _members()["eu27"]


def test_horizon_association_matches_ec_list_v4_2():
    m = _members()
    assert m["horizon_associated"] == set(
        "AL AM BA CH EG FO GB GE IL IS MD ME MK NO RS TN TR UA XK".split()
    )
    assert m["horizon_associated_pillar2"] == {"CA", "JP", "KR", "NZ"}


def test_every_country_has_one_m49_region_and_subregion():
    kinds: dict[str, dict[str, list[str]]] = {}
    for code, grouping, _, kind, _ in regions.region_group_rows():
        kinds.setdefault(code, {}).setdefault(kind, []).append(grouping)
    for code, k in kinds.items():
        if code == "EU":
            assert k["un_m49_region"] == ["un_europe"]
            assert "un_m49_subregion" not in k
            continue
        assert len(k["un_m49_region"]) == 1, code
        assert len(k["un_m49_subregion"]) == 1, code
    sub_of = {
        "un_northern_africa": "un_africa", "un_sub_saharan_africa": "un_africa",
        "un_latin_america_and_the_caribbean": "un_americas", "un_northern_america": "un_americas",
        "un_central_asia": "un_asia", "un_eastern_asia": "un_asia",
        "un_south_eastern_asia": "un_asia", "un_southern_asia": "un_asia",
        "un_western_asia": "un_asia", "un_eastern_europe": "un_europe",
        "un_northern_europe": "un_europe", "un_southern_europe": "un_europe",
        "un_western_europe": "un_europe", "un_australia_and_new_zealand": "un_oceania",
        "un_melanesia": "un_oceania", "un_micronesia": "un_oceania", "un_polynesia": "un_oceania",
    }
    for code, k in kinds.items():
        if code != "EU":
            assert sub_of[k["un_m49_subregion"][0]] == k["un_m49_region"][0], code
    m = _members()
    assert "TW" in m["un_eastern_asia"]
    assert "XK" in m["un_southern_europe"]
    assert "CY" in m["europe_geographic"]
    assert "CY" not in m["un_europe"]


_BASE = """as_of: 2026-10-23
groupings:
  - id: eu27
    label: EU
    kind: policy
    countries: >-
      DE EU
supranational_funders:
  - {id: F1, name: "EC", country: EU}
"""
_C = ">-\n      DE EU"


def test_base_regions_yaml_parses():
    regions._parse(_BASE)


@pytest.mark.parametrize("old, new, match", [
    ("DE EU", "de EU", "grouping 'eu27': bad country code"),
    ("DE EU", "DEU EU", "grouping 'eu27': bad country code"),
    ("DE EU", "DE DE EU", "grouping 'eu27': duplicate country code"),
    ("kind: policy", "kind: bogus", "grouping 'eu27': unknown kind"),
    ("supranational_funders:", "  - id: eu27\n    label: x\n    kind: policy\n"
                               "    countries: DE\nsupranational_funders:",
     "grouping 'eu27': duplicate grouping id"),
    ("id: eu27", "id: EU-27", "grouping 'EU-27': id must match"),
    (_C, "[DE, EU]", "grouping 'eu27': countries must be a string"),
    (_C, "NO", "grouping 'eu27': countries must be a string"),
    (_C, "''", "grouping 'eu27': no countries"),
    ("    label: EU\n", "", "grouping 'eu27': label must be a string"),
    ("id: F1", "id: X1", "funder 'X1': id must match"),
    ("country: EU}", "country: EU}\n  - {id: F1, name: \"EC\", country: EU}",
     "funder 'F1': duplicate funder id"),
    (", country: EU", "", "funder 'F1': country must be a string"),
    ("country: EU", "country: FR", "funder 'F1': country 'FR' is in no grouping"),
    ("as_of: 2026-10-23\n", "", "as_of"),
    ("as_of: 2026-10-23", "as_of: '2026-10-23'", "as_of"),
    ("as_of: 2026-10-23", "as_of: 2026-10-23 10:00:00", "as_of"),
])
def test_malformed_regions_yaml_is_rejected(old, new, match):
    assert old in _BASE
    with pytest.raises(ValueError, match=match):
        regions._parse(_BASE.replace(old, new))


def test_supranational_funder_count_is_pinned():
    assert len(regions._regions()["funders"]) == 23
    assert len(regions.funder_region_rows()) == 69


def test_cached_countries_are_tuples():
    assert all(isinstance(g["countries"], tuple) for g in regions._regions()["groupings"].values())


def test_region_group_mart_carries_as_of():
    con = db.connect(":memory:")
    db.init_schema(con)
    regions.load_regions(con)
    con.execute(_MART_SQL)
    assert con.execute("SELECT DISTINCT as_of FROM mart_region_group").fetchall() == [
        (datetime.date(2026, 10, 23),)]
    cols = [(r[0], r[1]) for r in con.execute("DESCRIBE mart_region_group").fetchall()]
    assert cols == [("country_code", "VARCHAR"), ("grouping", "VARCHAR"),
                    ("grouping_label", "VARCHAR"), ("grouping_kind", "VARCHAR"), ("as_of", "DATE")]


def test_region_group_as_of_migrates_old_store():
    con = db.connect(":memory:")
    con.execute(
        "CREATE TABLE dim_region_group (country_code VARCHAR NOT NULL, grouping VARCHAR NOT NULL, "
        "grouping_label VARCHAR NOT NULL, grouping_kind VARCHAR NOT NULL, "
        "PRIMARY KEY (country_code, grouping))")
    db.init_schema(con)
    regions.load_regions(con)
    nulls = con.execute("SELECT count(*) FROM dim_region_group WHERE as_of IS NULL").fetchone()[0]
    assert nulls == 0
    assert con.execute("SELECT count(*) FROM dim_region_group").fetchone()[0] == 604


def test_load_regions_is_idempotent():
    con = db.connect(":memory:")
    db.init_schema(con)
    first = regions.load_regions(con)
    assert first["dim_region_group"] > 0 and first["dim_funder_region"] > 0
    assert regions.load_regions(con) == first
    n = con.execute("SELECT count(*) FROM dim_region_group").fetchone()[0]
    assert n == first["dim_region_group"]


EU_GROUPS = {"eu27", "europe_geographic", "un_europe"}


def _funder_region(con):
    db.init_schema(con)
    regions.load_regions(con)
    con.execute(_MART_SQL)
    rows = con.execute("SELECT funder_id, grouping, basis FROM mart_funder_region").fetchall()
    out: dict[str, dict[str, set[str]]] = {}
    for fid, grouping, basis in rows:
        out.setdefault(fid, {}).setdefault(basis, set()).add(grouping)
    return out


def test_funder_region_mart_country_and_curated_basis():
    con = db.connect(":memory:")
    db.init_schema(con)
    con.execute(
        "INSERT INTO dim_funder (funder_id, name, curated, country_code) VALUES "
        "('F4320320879','DFG',false,'DE'), ('F4320320300','European Commission',false,NULL), "
        "('F7311471023','NextGenerationEU',false,'EU'), ('name:foo','foo',false,NULL)"
    )
    out = _funder_region(con)
    assert out["F4320320879"] == {"country": EU_GROUPS | {"un_western_europe"}}
    assert out["F4320320300"] == {"curated": EU_GROUPS}
    assert out["F7311471023"] == {"country": EU_GROUPS}
    assert "name:foo" not in out
    assert "F4320334678" not in out  # ERC: curated but absent from dim_funder


def test_curated_mapping_replaces_country():
    con = db.connect(":memory:")
    db.init_schema(con)
    con.execute(
        "INSERT INTO dim_funder (funder_id, name, curated, country_code) VALUES "
        "('F4320320300','European Commission',false,'BE')"
    )
    assert _funder_region(con)["F4320320300"] == {"curated": EU_GROUPS}
