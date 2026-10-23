# Spec #91: region groupings for countries and supranational funders

*Spec stage, 2026-10-23. Everything below about upstream data was checked live that day (keyless
OpenAlex, the EC and EU sites, UN M49); see "Verification" at the end.*

## Goal

Make "which Europe" (or which world region) a filter the dashboard applies, not a collection
boundary (scope decision in `docs/international-impact.md`). Concretely:

- A checked-in table, `src/biocintel/regions.yaml`, maps country code → membership in named
  groupings: `eu27`, `horizon_associated`, `horizon_associated_pillar2`, `europe_geographic`,
  and the UN M49 regions and sub-regions (`un_*`). A country can be in several groupings.
- The same file hand-maps the supranational funders OpenAlex gives no `country_code`
  (European Commission, ERC, Horizon 2020, FP7, ERDF, ESF, MSCA, …), keyed on the OpenAlex `F…`
  id that `dim_funder` uses since #85.
- `build_marts` loads it into `dim_region_group` + `dim_funder_region` and exports two marts,
  `mart_region_group` and `mart_funder_region`, so the frontend can filter
  `mart_work_institution` and `mart_work_funder` by grouping.
- Existing marts keep country codes. No grouping is baked into any count.

## Non-goals

- **Frontend.** No change to `frontend/` (not even `LAZY_MARTS` in `frontend/src/db/duckdb.ts`).
  A grouping filter on the dashboard is a follow-up issue.
- **Historical membership.** Groupings are *current* membership as of the date in
  `regions.yaml`. The UK is in `horizon_associated`, not `eu27`, for every year; no
  valid-from/valid-to columns.
- **Citing-work geography** (`mart_package_reach`, #92), award detail (#90), download geography
  (#94). They will join these tables; nothing here anticipates them.
- **New upstream API calls at runtime.** The table is static, checked in, and reviewed by hand.
  No new HTTP, no fixtures under `tests/fixtures/api/`.
- **Curating funders that already have an OpenAlex country.** EMBL (DE), IMI (BE), WHO (CH),
  Gates (US), HFSP (FR) keep their country's groupings (see Risks).
- No "EU27 + UK/CH/NO/IS" composite grouping. The frontend can union `eu27` with chosen
  countries.

## Design

### Files

| File | Change |
|---|---|
| `src/biocintel/regions.yaml` | **new**: verbatim content in the Appendix |
| `src/biocintel/regions.py` | **new**: parse + validate the YAML, load the two dims |
| `src/biocintel/schema.sql` | two new tables |
| `src/biocintel/pipeline/build_marts.py` | call `regions.load_regions(con)`; two marts in `_MART_SQL`, `_MARTS`, `DEFINITIONS`; one unmapped-funder warning |
| `tests/test_regions.py` | **new** |
| `CLAUDE.md` | Layout: add `regions.yaml` / `regions.py` lines; data-model paragraph: add the two dims and two marts |
| `bioc-intelligence-spec.md` | §5 Dimensions: add `dim_region_group`, `dim_funder_region`; Derived marts: add the two marts (one line each) |

No change to `db.py`: the tables are new, so `CREATE TABLE IF NOT EXISTS` in `schema.sql`
(run by `init_schema` on every connect) is the whole migration for existing stores. No
`ALTER TABLE` needed.

### `regions.yaml` format

```yaml
groupings:
  - id: eu27                                   # grouping id, unique, ^[a-z0-9_]+$
    label: European Union (27 member states)   # human-readable
    kind: policy                               # policy | geographic | un_m49_region | un_m49_subregion
    countries: >-                              # ONE space-separated string, never a YAML list
      AT BE BG ...
supranational_funders:
  - {id: F4320320300, name: "European Commission", country: EU}
```

`countries` is a single string split on whitespace because PyYAML's `safe_load` reads a bare
`NO` (Norway) as `False` (verified: `yaml.safe_load('[NO]') == [False]`). A supranational
funder's `country` is a code that appears in `groupings`; the funder takes every grouping that
code is in.

Country codes: ISO 3166-1 alpha-2 as OpenAlex writes them (`GR` not `EL`, `GB` not `UK`), plus
the three non-M49 codes OpenAlex uses (verified by `group_by=country_code` on `/funders` and
`/institutions`):

- `XK` Kosovo (23 institutions): `horizon_associated`, `europe_geographic`, `un_europe`,
  `un_southern_europe`.
- `TW` Taiwan (532 institutions, 241 funders): `un_asia`, `un_eastern_asia`. M49 does not list
  it separately.
- `EU` (22 funders, e.g. NextGenerationEU `F7311471023`): `eu27`, `europe_geographic`,
  `un_europe`. No sub-region.

Antarctica (`AQ`, no M49 region) is left out.

Grouping definitions (lists in the Appendix):

| id | kind | definition | count |
|---|---|---|---|
| `eu27` | policy | the 27 EU member states + `EU` | 28 codes |
| `horizon_associated` | policy | countries associated to the **whole** Horizon Europe programme (EC list V4.2, 07.10.2026) | 19 |
| `horizon_associated_pillar2` | policy | associated to Pillar II only: CA, JP, KR, NZ | 4 |
| `europe_geographic` | geographic | `un_europe` ∪ {CY} (Cyprus is EU but M49 Western Asia) | 54 |
| `un_<region>` | un_m49_region | 5 M49 regions (`un_africa`, `un_americas`, `un_asia`, `un_europe`, `un_oceania`) | 250 codes total |
| `un_<sub_region>` | un_m49_subregion | 17 M49 sub-regions, e.g. `un_western_europe`, `un_latin_america_and_the_caribbean` | |

Id slug rule for `un_*`: `"un_" + re.sub(r"[^a-z]+", "_", name.lower()).strip("_")`.

The two Horizon groupings are kept apart because the EC list itself separates whole-programme
from Pillar-II-only association, and folding Canada, Japan, Korea and New Zealand into a
"Europe-adjacent" filter would surprise a European reviewer. A union of the two is "all
Horizon associates". Australia and Morocco (transitional arrangements only) are in neither.

### `src/biocintel/regions.py`

Mirrors `funders.py`: a cached reader of the packaged YAML via `importlib.resources`.

```python
"""Region groupings: country / supranational funder → named groupings (#91). ..."""

from __future__ import annotations

import re
from functools import cache
from importlib import resources

import duckdb
import yaml

KINDS = ("policy", "geographic", "un_m49_region", "un_m49_subregion")


@cache
def _regions() -> dict:
    """Parsed and validated regions.yaml; raises ValueError on a malformed entry."""


def region_group_rows() -> list[tuple[str, str, str, str]]:
    """dim_region_group rows: (country_code, grouping, grouping_label, grouping_kind)."""


def funder_region_rows() -> list[tuple[str, str]]:
    """dim_funder_region rows: (funder_id, grouping), each supranational funder × every
    grouping its ``country`` is in."""


def load_regions(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Replace dim_region_group and dim_funder_region from regions.yaml in one transaction.
    Returns {"dim_region_group": n, "dim_funder_region": m}."""
```

Validation in `_regions()` (raise `ValueError` naming the bad entry):

- every country code matches `^[A-Z]{2}$`;
- grouping ids unique and match `^[a-z0-9_]+$`; `kind` in `KINDS`; no duplicate code within
  one grouping;
- funder ids match `^F\d+$` and are unique; each funder's `country` is in at least one grouping.

`load_regions` does `BEGIN`, `DELETE FROM` both tables, `executemany` inserts, `COMMIT`
(rollback on error), like `extract_people`'s replace. Rows are sorted for determinism.

### DDL (`schema.sql`, new section after the institution tables)

```sql
-- ── Region groupings from regions.yaml (#91), reloaded by build_marts. ──
-- Country → named grouping; one country can be in several. Filters, never baked into counts.
CREATE TABLE IF NOT EXISTS dim_region_group (
    country_code    VARCHAR NOT NULL,     -- ISO alpha-2 as OpenAlex writes it, plus XK, TW, EU
    grouping        VARCHAR NOT NULL,     -- 'eu27' | 'horizon_associated' | ... | 'un_western_europe'
    grouping_label  VARCHAR NOT NULL,
    grouping_kind   VARCHAR NOT NULL,     -- 'policy' | 'geographic' | 'un_m49_region' | 'un_m49_subregion'
    PRIMARY KEY (country_code, grouping)
);

-- Hand-mapped groupings for supranational funders OpenAlex gives no country_code.
CREATE TABLE IF NOT EXISTS dim_funder_region (
    funder_id  VARCHAR NOT NULL,          -- OpenAlex funder id ('F…'), dim_funder.funder_id
    grouping   VARCHAR NOT NULL,
    PRIMARY KEY (funder_id, grouping)
);
```

`grouping` is a DuckDB keyword in the `column_name` category; verified on DuckDB 2.0.0 that it
works unquoted as a column in `SELECT`, `WHERE`, `GROUP BY` and `ORDER BY`.

### `build_marts.py`

`run()`: after `db.init_schema(con)` and before `con.execute(_MART_SQL)`:

```python
counts.update(regions.load_regions(con))
```

(`from .. import db, regions`.) The dims are reloaded on every build, so a YAML edit shows up
in the next `build-marts` without re-running enrichment.

Append to `_MART_SQL`:

```sql
-- Country → region grouping (#91), for filtering country-coded marts. One country, many groupings.
CREATE OR REPLACE TABLE mart_region_group AS
SELECT country_code, grouping, grouping_label, grouping_kind
FROM dim_region_group
ORDER BY grouping, country_code;

-- Funder → region grouping: the curated groupings for supranational funders, else the
-- groupings of the funder's OpenAlex country. Funders with neither get no rows.
CREATE OR REPLACE TABLE mart_funder_region AS
SELECT * FROM (
    SELECT fr.funder_id, fr.grouping, 'curated' AS basis
    FROM dim_funder_region fr
    WHERE fr.funder_id IN (SELECT funder_id FROM dim_funder)
    UNION ALL
    SELECT f.funder_id, r.grouping, 'country' AS basis
    FROM dim_funder f
    JOIN dim_region_group r ON r.country_code = f.country_code
    WHERE f.funder_id NOT IN (SELECT funder_id FROM dim_funder_region)
)
ORDER BY funder_id, grouping;
```

A curated entry **replaces** the country path for that funder (if OpenAlex later gives the
European Commission a country, the curated `EU` mapping still wins).

Add `"mart_region_group"` and `"mart_funder_region"` to the end of `_MARTS`.

After the export loop in `run()`, print one curation hint (print only, never fail):

```python
unmapped = con.execute(
    "SELECT f.name, count(DISTINCT b.work_id) AS n FROM bridge_work_funder b "
    "JOIN dim_funder f USING (funder_id) "
    "WHERE f.funder_id NOT IN (SELECT funder_id FROM mart_funder_region) "
    "GROUP BY f.name ORDER BY n DESC, f.name LIMIT 5"
).fetchall()
```

and if non-empty, `print(f"  regions: funders on linked works with no grouping (add to regions.yaml if supranational): {unmapped}")`.

`DEFINITIONS` entries (exact text):

```python
_GROUPING = ("Grouping id: eu27, horizon_associated, horizon_associated_pillar2, "
             "europe_geographic, or un_<UN M49 region or sub-region>, e.g. un_western_europe.")

"mart_region_group": {
    "description": "One row per country x named region grouping, from the checked-in "
                   "regions.yaml. A country can be in several groupings. Groupings are "
                   "filters: join on country_code (e.g. mart_work_institution); never add "
                   "counts across groupings. Count DISTINCT work_id after joining: "
                   "mart_work_institution has several rows per work. No rows means the "
                   "country is unknown, not outside every grouping; for a share, use works "
                   "whose institution country is in some un_m49_region grouping as the "
                   "denominator.",
    "columns": {
        "country_code": "ISO 3166-1 alpha-2 code as OpenAlex writes it (GR, GB), plus XK "
                        "(Kosovo), TW (Taiwan, which UN M49 does not list; placed in Eastern "
                        "Asia) and EU, OpenAlex's code for EU-level bodies (in eu27, "
                        "europe_geographic and un_europe only).",
        "grouping": _GROUPING,
        "grouping_label": "Human-readable grouping name.",
        "grouping_kind": "policy (EU or Horizon Europe membership), geographic, "
                         "un_m49_region or un_m49_subregion. Policy groupings are current "
                         "membership as of regions.yaml, not membership when a paper or "
                         "grant was written: the UK is never in eu27.",
    },
},
"mart_funder_region": {
    "description": "One row per funder x region grouping. A funder takes the groupings of "
                   "its OpenAlex country, except supranational funders OpenAlex gives no "
                   "country (European Commission, ERC, Horizon 2020, ...), which take the "
                   "curated groupings in regions.yaml. Funders with neither have no rows. "
                   "A grouping is where the funder is based, not where the funded "
                   "researchers are: EMBL (Germany) is in eu27, WHO (Switzerland) in "
                   "horizon_associated. Count DISTINCT work_id after joining: "
                   "mart_work_funder has several rows per work (awards, co-funders in the "
                   "same grouping). No rows means the location is unknown, not outside every "
                   "grouping; for a share, use works whose funder is in some un_m49_region "
                   "grouping or has basis curated as the denominator.",
    "columns": {
        "funder_id": "OpenAlex funder id (F...); joins mart_work_funder.",
        "grouping": _GROUPING,
        "basis": "country (from the funder's OpenAlex country_code) or curated "
                 "(hand-mapped in regions.yaml).",
    },
},
```

No new `HONEST_VIEWS` and no new views-file macro.

### CLI / `run()` entry points

None new. `biocintel build-marts` (and `python -m biocintel.pipeline.build_marts`) loads the
dims and writes the two new Parquet files to `data/marts/`. No new refresh step.

### Upstream APIs and fixtures

None at runtime. The sources were checked once to build the YAML (URLs in its header and under
Verification). No fixture files.

## Acceptance criteria

- [ ] `src/biocintel/regions.yaml` matches the Appendix (26 groupings, 23 supranational funders).
- [ ] `regions.region_group_rows()` returns 26 groupings over 250 distinct codes; Norway (`NO`)
      is present as the string `"NO"` in `horizon_associated` and `europe_geographic`.
- [ ] `eu27` = the 27 member states + `EU`; `GB`, `CH`, `NO` not in it.
- [ ] `horizon_associated` = {AL AM BA CH EG FO GB GE IL IS MD ME MK NO RS TN TR UA XK};
      `horizon_associated_pillar2` = {CA JP KR NZ}.
- [ ] Every code except `EU` is in exactly one `un_m49_region` and exactly one
      `un_m49_subregion` grouping, and each code's sub-region is inside its region; `EU` is in
      `un_europe` and in no sub-region.
- [ ] `_regions()` raises `ValueError` for a lowercase/3-letter code, an unknown `kind`, a
      duplicate grouping id, a funder id not matching `^F\d+$`, and a funder `country` in no
      grouping.
- [ ] `load_regions` on an in-memory store fills both dims; a second call leaves the same counts.
- [ ] `mart_funder_region`: a funder with country `DE` gets `eu27`, `europe_geographic`,
      `un_europe`, `un_western_europe` (basis `country`); European Commission (`F4320320300`,
      NULL country) gets `eu27`, `europe_geographic`, `un_europe` (basis `curated`); a funder
      with country `EU` gets the same three (basis `country`); a NULL-country, uncurated funder
      gets no rows; a curated funder absent from `dim_funder` gets no rows; a curated funder
      that also has a country gets only the curated rows.
- [ ] Both marts are in `_MARTS`, have `DEFINITIONS` for every column, and
      `tests/test_views_db.py` passes unchanged (it iterates `_MARTS`).
- [ ] No existing mart's columns or rows change.
- [ ] `uv run pytest` and `uv run ruff check src tests` pass.
- [ ] `CLAUDE.md` and `bioc-intelligence-spec.md` §5 mention the two dims and two marts.

## Test plan

`tests/test_regions.py`, offline, against the real packaged `regions.yaml` and an in-memory
store (`db.connect(":memory:")` + `db.init_schema`), in the style of `tests/test_marts.py`:

1. `test_country_codes_are_strings_and_norway_survives_yaml`: all codes match `^[A-Z]{2}$`;
   `"NO"` in `horizon_associated`.
2. `test_eu27_is_the_member_states_plus_eu_code`: exact set.
3. `test_horizon_association_matches_ec_list_v4_2`: exact sets for both Horizon groupings.
4. `test_every_country_has_one_m49_region_and_subregion`: the nesting rule above, plus
   `TW → un_eastern_asia`, `XK → un_southern_europe`, `CY ∈ europe_geographic`,
   `CY ∉ un_europe`.
5. `test_malformed_regions_yaml_is_rejected` (parametrized): monkeypatch the YAML text the
   loader reads (call `_regions.cache_clear()` before and after) for each invalid case in the
   acceptance list; expect `ValueError`.
6. `test_load_regions_is_idempotent`.
7. `test_funder_region_mart_country_and_curated_basis`: insert into `dim_funder` DFG
   (`F4320320879`, `DE`), the European Commission (`F4320320300`, NULL country),
   NextGenerationEU (`F7311471023`, `EU`) and an uncurated NULL-country funder (`name:foo`);
   run `load_regions` then `_MART_SQL`; assert the rows and `basis` exactly as in the
   acceptance list, and that ERC (`F4320334678`, curated but not inserted) has no rows.
8. `test_curated_mapping_replaces_country`: the European Commission inserted with
   `country_code = 'BE'` still gets only its three curated rows (no `un_western_europe`).

`tests/test_views_db.py` covers DEFINITIONS completeness for the new marts without edits.

## Risks

- **Membership lists go stale.** Horizon association changes (Australia and Morocco are in
  transition; the EC list is versioned, V4.2 of 07.10.2026). The YAML header names the source
  and check date; re-check when a Horizon-specific claim goes into a proposal.
- **Host country is not reach.** EMBL, WHO, HFSP, IMI are intergovernmental or joint bodies
  that OpenAlex gives a host country; they land in that country's groupings. The
  `mart_funder_region` definition says so. A curated entry can override one later if a
  reviewer objects.
- **New NULL-country funders** after a refresh get no grouping. `build-marts` prints the top
  five by works so they can be added; nothing fails.
- **`EU` is in `dim_region_group` as if it were a country**, so "countries in eu27" counts 28.
  The `country_code` definition says so; a frontend country picker should drop `EU`.
- **Data run.** PR #87's funders step has not run on production yet (the 2026-10-07 store has
  no `bridge_work_funder`), so `mart_funder_region` is mostly empty until the next monthly
  refresh runs enrichment + `build-marts`. The views file skips a mart until its Parquet is
  published (`write_views_db` warns), so the two new views appear on the refresh after the
  marts first deploy. The PR should say so; no manual data run is needed.

## Verification (2026-10-23)

- OpenAlex funders of our 1,178 `dim_work.openalex_id`s (`/works?filter=openalex:W…|W…&select=id,funders`,
  24 calls; `/funders?filter=openalex:F…|F…&select=id,display_name,country_code,ids`, 17 calls):
  904 works with funders, 805 funders, 782 with a `country_code`. The 23 without are all EU
  bodies (listed in the Appendix, by works: European Commission 84, H2020 ERC 21, Horizon 2020
  19, ERDF 11, …). EMBL `F4320314023` is DE, IMI `F4320326631` BE, Gates `F4320306137` US,
  WHO `F4320307856` CH. `/funders` does not accept `ror` in `select`.
- `/funders?filter=country_code:EU` → 22 funders (NextGenerationEU, EuroHPC JU, HaDEA, REA, …).
  `/funders?group_by=country_code` and `/institutions?group_by=country_code`: the only codes not
  in M49 are `TW`, `EU` (funders) and `TW`, `XK` (institutions).
- EU27: european-union.europa.eu "EU countries" lists 27 (Austria … Sweden).
- Horizon Europe: EC "List of participating countries in Horizon Europe" V4.2, 07.10.2026,
  23 associated countries; Canada, Japan, Korea, New Zealand Pillar II only; UK from 2024,
  Switzerland and Egypt from 2025; Australia, Morocco transitional; Liechtenstein not
  associating.
- UN M49: the overview page's English table (248 rows; 5 regions, 17 sub-regions; Antarctica
  has no region; Cyprus, Türkiye, Israel, Armenia, Georgia, Azerbaijan are Western Asia).

## Appendix: `src/biocintel/regions.yaml` (verbatim)

```yaml
# Region groupings for countries and supranational funders (#91; see biocintel/regions.py).
#
# Groupings are views, not collection scope: marts keep country codes and the frontend
# filters by grouping. One country can be in several groupings.
#
# Country codes are ISO 3166-1 alpha-2 as OpenAlex writes them (GR, GB), plus three codes
# OpenAlex uses that UN M49 lacks: XK (Kosovo; placed in Southern Europe), TW (Taiwan;
# placed in Eastern Asia) and EU (OpenAlex's code for EU-level bodies such as
# NextGenerationEU; in eu27, europe_geographic and un_europe only).
#
# `countries` is one space-separated string, never a YAML list: YAML reads a bare NO
# (Norway) as false.
#
# Sources, checked 2026-10-23. Re-check the policy lists when association agreements change.
# - eu27: https://european-union.europa.eu/principles-countries-history/eu-countries_en
# - horizon_associated, horizon_associated_pillar2: EC "List of participating countries in
#   Horizon Europe" V4.2, 07.10.2026,
#   https://ec.europa.eu/info/funding-tenders/opportunities/docs/2021-2027/common/guidance/list-3rd-country-participation_horizon-euratom_en.pdf
#   (UK associated from 2024, Switzerland and Egypt from 2025, Japan Pillar II from 2026;
#   Australia and Morocco are still under transitional arrangements and are not listed).
# - un_*: UN M49 overview, https://unstats.un.org/unsd/methodology/m49/overview/
#   (region and sub-region; intermediate regions are not used).

groupings:
  - id: eu27
    label: European Union (27 member states)
    kind: policy
    countries: >-
      AT BE BG CY CZ DE DK EE ES EU FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK
  - id: horizon_associated
    label: Associated to Horizon Europe (whole programme)
    kind: policy
    countries: >-
      AL AM BA CH EG FO GB GE IL IS MD ME MK NO RS TN TR UA XK
  - id: horizon_associated_pillar2
    label: Associated to Horizon Europe Pillar II only
    kind: policy
    countries: >-
      CA JP KR NZ
  - id: europe_geographic
    label: Europe, geographic (UN M49 Europe plus Cyprus)
    kind: geographic
    countries: >-
      AD AL AT AX BA BE BG BY CH CY CZ DE DK EE ES EU FI FO FR GB GG GI GR HR HU IE IM IS IT
      JE LI LT LU LV MC MD ME MK MT NL NO PL PT RO RS RU SE SI SJ SK SM UA VA XK
  - id: un_africa
    label: Africa (UN M49 region)
    kind: un_m49_region
    countries: >-
      AO BF BI BJ BW CD CF CG CI CM CV DJ DZ EG EH ER ET GA GH GM GN GQ GW IO KE KM LR LS LY
      MA MG ML MR MU MW MZ NA NE NG RE RW SC SD SH SL SN SO SS ST SZ TD TF TG TN TZ UG YT ZA
      ZM ZW
  - id: un_americas
    label: Americas (UN M49 region)
    kind: un_m49_region
    countries: >-
      AG AI AR AW BB BL BM BO BQ BR BS BV BZ CA CL CO CR CU CW DM DO EC FK GD GF GL GP GS GT
      GY HN HT JM KN KY LC MF MQ MS MX NI PA PE PM PR PY SR SV SX TC TT US UY VC VE VG VI
  - id: un_asia
    label: Asia (UN M49 region)
    kind: un_m49_region
    countries: >-
      AE AF AM AZ BD BH BN BT CN CY GE HK ID IL IN IQ IR JO JP KG KH KP KR KW KZ LA LB LK MM
      MN MO MV MY NP OM PH PK PS QA SA SG SY TH TJ TL TM TR TW UZ VN YE
  - id: un_europe
    label: Europe (UN M49 region)
    kind: un_m49_region
    countries: >-
      AD AL AT AX BA BE BG BY CH CZ DE DK EE ES EU FI FO FR GB GG GI GR HR HU IE IM IS IT JE
      LI LT LU LV MC MD ME MK MT NL NO PL PT RO RS RU SE SI SJ SK SM UA VA XK
  - id: un_oceania
    label: Oceania (UN M49 region)
    kind: un_m49_region
    countries: >-
      AS AU CC CK CX FJ FM GU HM KI MH MP NC NF NR NU NZ PF PG PN PW SB TK TO TV UM VU WF WS
  - id: un_northern_africa
    label: Northern Africa (UN M49 sub-region of Africa)
    kind: un_m49_subregion
    countries: >-
      DZ EG EH LY MA SD TN
  - id: un_sub_saharan_africa
    label: Sub-Saharan Africa (UN M49 sub-region of Africa)
    kind: un_m49_subregion
    countries: >-
      AO BF BI BJ BW CD CF CG CI CM CV DJ ER ET GA GH GM GN GQ GW IO KE KM LR LS MG ML MR MU
      MW MZ NA NE NG RE RW SC SH SL SN SO SS ST SZ TD TF TG TZ UG YT ZA ZM ZW
  - id: un_latin_america_and_the_caribbean
    label: Latin America and the Caribbean (UN M49 sub-region of Americas)
    kind: un_m49_subregion
    countries: >-
      AG AI AR AW BB BL BO BQ BR BS BV BZ CL CO CR CU CW DM DO EC FK GD GF GP GS GT GY HN HT
      JM KN KY LC MF MQ MS MX NI PA PE PR PY SR SV SX TC TT UY VC VE VG VI
  - id: un_northern_america
    label: Northern America (UN M49 sub-region of Americas)
    kind: un_m49_subregion
    countries: >-
      BM CA GL PM US
  - id: un_central_asia
    label: Central Asia (UN M49 sub-region of Asia)
    kind: un_m49_subregion
    countries: >-
      KG KZ TJ TM UZ
  - id: un_eastern_asia
    label: Eastern Asia (UN M49 sub-region of Asia)
    kind: un_m49_subregion
    countries: >-
      CN HK JP KP KR MN MO TW
  - id: un_south_eastern_asia
    label: South-eastern Asia (UN M49 sub-region of Asia)
    kind: un_m49_subregion
    countries: >-
      BN ID KH LA MM MY PH SG TH TL VN
  - id: un_southern_asia
    label: Southern Asia (UN M49 sub-region of Asia)
    kind: un_m49_subregion
    countries: >-
      AF BD BT IN IR LK MV NP PK
  - id: un_western_asia
    label: Western Asia (UN M49 sub-region of Asia)
    kind: un_m49_subregion
    countries: >-
      AE AM AZ BH CY GE IL IQ JO KW LB OM PS QA SA SY TR YE
  - id: un_eastern_europe
    label: Eastern Europe (UN M49 sub-region of Europe)
    kind: un_m49_subregion
    countries: >-
      BG BY CZ HU MD PL RO RU SK UA
  - id: un_northern_europe
    label: Northern Europe (UN M49 sub-region of Europe)
    kind: un_m49_subregion
    countries: >-
      AX DK EE FI FO GB GG IE IM IS JE LT LV NO SE SJ
  - id: un_southern_europe
    label: Southern Europe (UN M49 sub-region of Europe)
    kind: un_m49_subregion
    countries: >-
      AD AL BA ES GI GR HR IT ME MK MT PT RS SI SM VA XK
  - id: un_western_europe
    label: Western Europe (UN M49 sub-region of Europe)
    kind: un_m49_subregion
    countries: >-
      AT BE CH DE FR LI LU MC NL
  - id: un_australia_and_new_zealand
    label: Australia and New Zealand (UN M49 sub-region of Oceania)
    kind: un_m49_subregion
    countries: >-
      AU CC CX HM NF NZ
  - id: un_melanesia
    label: Melanesia (UN M49 sub-region of Oceania)
    kind: un_m49_subregion
    countries: >-
      FJ NC PG SB VU
  - id: un_micronesia
    label: Micronesia (UN M49 sub-region of Oceania)
    kind: un_m49_subregion
    countries: >-
      FM GU KI MH MP NR PW UM
  - id: un_polynesia
    label: Polynesia (UN M49 sub-region of Oceania)
    kind: un_m49_subregion
    countries: >-
      AS CK NU PF PN TK TO TV WF WS

# Funders OpenAlex lists on our works with no country_code (all EU bodies, 2026-10-23). Each
# takes the groupings of `country`. Funders that have a country_code in OpenAlex (EMBL DE,
# IMI BE, WHO CH, Gates US) are not listed: their country's groupings apply.
supranational_funders:
  - {id: F4320320300, name: "European Commission", country: EU}
  - {id: F4320338335, name: "H2020 European Research Council", country: EU}
  - {id: F4320332999, name: "Horizon 2020 Framework Programme", country: EU}
  - {id: F4320335322, name: "European Regional Development Fund", country: EU}
  - {id: F4320334678, name: "European Research Council", country: EU}
  - {id: F4320334960, name: "Seventh Framework Programme", country: EU}
  - {id: F4320338352, name: "FP7 Ideas: European Research Council", country: EU}
  - {id: F4320338080, name: "European Social Fund", country: EU}
  - {id: F4320338377, name: "FP7 Health", country: EU}
  - {id: F4320335254, name: "Horizon 2020", country: EU}
  - {id: F4320317617, name: "E-Rare", country: EU}
  - {id: F4320334322, name: "HORIZON EUROPE Framework Programme", country: EU}
  - {id: F4320338337, name: "H2020 Marie Skłodowska-Curie Actions", country: EU}
  - {id: F4320338438, name: "HORIZON EUROPE Marie Sklodowska-Curie Actions", country: EU}
  - {id: F4320319638, name: "EOSC-Life", country: EU}
  - {id: F4320332197, name: "Directorate-General for Research and Innovation", country: EU}
  - {id: F4320333065, name: "Seventh Framework Programme", country: EU}
  - {id: F4320334679, name: "Research Executive Agency", country: EU}
  - {id: F4320334680, name: "Education, Audiovisual and Culture Executive Agency", country: EU}
  - {id: F4320335551, name: "Erasmus+", country: EU}
  - {id: F4320337662, name: "H2020 Excellent Science", country: EU}
  - {id: F4320337665, name: "H2020 Spreading Excellence and Widening Participation", country: EU}
  - {id: F4320338364, name: "FP7 Research infrastructures", country: EU}
```
