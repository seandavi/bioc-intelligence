# Spec #100: follow-ups from the #91 review (region groupings)

Issue: [#100](https://github.com/seandavi/bioc-intelligence/issues/100). Base:
[`docs/specs/91-region-groupings.md`](91-region-groupings.md), merged in `ada2540`.

*Spec stage, 2026-10-23. No upstream API is involved. Facts below were checked against the
current tree on that date with DuckDB 2.0.0 and PyYAML in the project venv (see "Verification").*

## Goal

Close the seven findings in #100:

| Finding | What changes |
|---|---|
| code-r0-1, data-r0-3 | `regions.py` validation raises `ValueError` naming the bad entry for a missing key, a non-string value (`countries: [DE, EU]`, `countries: NO`) and an empty `countries` |
| code-r0-2 | tests for the three uncovered guards: duplicate code in a grouping, duplicate funder id, bad grouping id |
| code-r0-3 | `_regions()` reads the file and calls a pure `_parse(text)`. Tests call `_parse` directly, with no monkeypatching or `cache_clear` |
| code-r0-4 | `countries` is stored as a tuple, so the cached value can't be mutated through a list |
| data-r0-2 | `regions.yaml` gets a top-level `as_of` date. It is validated and carried as an `as_of DATE` column in `dim_region_group` and `mart_region_group`, with a DEFINITIONS entry |
| data-r0-4 | pin 23 supranational funders and 69 `funder_region_rows()` |
| data-r1-1 | both region-mart descriptions say a share is a lower bound. The `mart_funder_region` denominator becomes "works with at least one row here" |

## Non-goals

- No change to grouping membership, labels or kinds. No new grouping or funder.
- No per-grouping `source` field. The issue calls it optional. The sources and EC list version
  stay in the YAML header, and the `as_of` definition links to the published file.
- No `as_of` on `dim_funder_region` or `mart_funder_region`. Their groupings come from the same
  YAML, so the `mart_funder_region` description points to `mart_region_group.as_of`.
- No valid-from/valid-to history (still a non-goal from #91).
- `docs/specs/91-region-groupings.md` is not edited. It records what #91 specified, and this
  spec records the change.
- No frontend change. `frontend/src` does not read either region mart.
- No new HTTP calls and no fixture files.

## Design

### Files

| File | Change |
|---|---|
| `src/biocintel/regions.py` | split into `_parse(text)` + cached `_regions()`; stricter validation; `as_of`; tuple `countries`; 5-tuple `region_group_rows()`; `load_regions` inserts `as_of` |
| `src/biocintel/regions.yaml` | add `as_of: 2026-10-23`; header line points at it |
| `src/biocintel/schema.sql` | `as_of DATE` as the last column of `dim_region_group` |
| `src/biocintel/db.py` | migration: `ALTER TABLE dim_region_group ADD COLUMN IF NOT EXISTS as_of DATE` |
| `src/biocintel/pipeline/build_marts.py` | `mart_region_group` selects `as_of`; DEFINITIONS text for both region marts |
| `tests/test_regions.py` | rewrite the malformed-YAML test onto `_parse`; new cases; pinned counts; `as_of` and migration tests; update row unpacking for 5-tuples |
| `bioc-intelligence-spec.md` | §5: add `as_of` to `dim_region_group(...)` and `mart_region_group(...)` |

`CLAUDE.md` needs no change. Its region lines stay true.

### `regions.yaml`

Insert one top-level key **before** `groupings:`, after the header comment block:

```yaml
# Date the lists below were last checked against the sources above; published as
# mart_region_group.as_of. Bump it whenever a list is re-checked, changed or not.
as_of: 2026-10-23

groupings:
```

In the header, change the line `# Sources, checked 2026-10-23. Re-check the policy lists when
association agreements change.` to `# Sources (checked on the as_of date below). Re-check the
policy lists when association agreements change.` Leave the EC list version text ("V4.2,
07.10.2026") as it is.

`as_of` stays unquoted. PyYAML `safe_load` reads `2026-10-23` as `datetime.date(2026, 10, 23)`
and `'2026-10-23'` as a `str`. Only the unquoted form is accepted.

### `regions.py`

Module docstring: keep it, and add one sentence: "``as_of`` (the date the lists were checked)
is stamped on every ``dim_region_group`` row."

Add `import datetime as dt`. `KINDS` and the three regexes stay as they are.

```python
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
```

Notes for the implementer:

- `type(as_of) is not dt.date` (not `isinstance`) rejects a `datetime`, which is a `date`
  subclass, e.g. `as_of: 2026-10-23 10:00:00`.
- A missing key and a non-string value give the same message, `"... must be a string, got
  None"` or `"got ['DE', 'EU']"`. `countries: NO` (YAML `False`) gives `got False`. An entry with
  no `id` reports `funder None: ...` or `grouping None: ...`.
- `countries: ''` passes the string check and fails with `no countries`.
- Funder `name` stays optional and unread. Only `id` and `country` are required.
- The error-message prefixes change from #91. `grouping id 'X' must match`, `duplicate grouping
  id 'X'`, `funder id 'X' must match` and `duplicate funder id 'X'` become
  `grouping 'X': id must match`, `grouping 'X': duplicate grouping id`, `funder 'X': id must
  match` and `funder 'X': duplicate funder id`, so every message starts with the entry. Nothing
  outside `tests/test_regions.py` matches on these strings.

Row functions:

```python
def region_group_rows() -> list[tuple[str, str, str, str, dt.date]]:
    """dim_region_group rows: (country_code, grouping, grouping_label, grouping_kind, as_of)."""
    r = _regions()
    return sorted(
        (code, gid, g["label"], g["kind"], r["as_of"])
        for gid, g in r["groupings"].items()
        for code in g["countries"]
    )
```

`funder_region_rows()` is unchanged.

`load_regions`: the `dim_region_group` insert names its columns, so a migrated store, where
`as_of` was appended last by `ALTER`, and a fresh store take the same statement:

```python
con.executemany(
    "INSERT INTO dim_region_group (country_code, grouping, grouping_label, grouping_kind, as_of) "
    "VALUES (?, ?, ?, ?, ?)", group_rows)
```

The return value and the transaction are unchanged.

### DDL and migration

`schema.sql`, `dim_region_group`: add a last column. Keep the primary key.

```sql
    grouping_kind   VARCHAR NOT NULL,     -- 'policy' | 'geographic' | 'un_m49_region' | 'un_m49_subregion'
    as_of           DATE,                 -- regions.yaml as_of: date the lists were last checked
    PRIMARY KEY (country_code, grouping)
```

The column is nullable because DuckDB 2.0.0 rejects `ADD COLUMN IF NOT EXISTS ... NOT NULL`
(verified: "Adding a NOT NULL column with IF NOT EXISTS is not supported"). Fresh and migrated
stores keep the same shape. `_parse` guarantees a value, and `load_regions` replaces every row
on each build, so the column is never NULL after a `build-marts`.

`db.py`: after the `_DIM_FUNDER_COLUMNS` loop in `init_schema`, add one line:

```python
    con.execute("ALTER TABLE dim_region_group ADD COLUMN IF NOT EXISTS as_of DATE")
```

This follows the single-column `bridge_package_pub.source_release` line. No new list constant
for one column.

### `build_marts.py`

`_MART_SQL`, `mart_region_group`:

```sql
CREATE OR REPLACE TABLE mart_region_group AS
SELECT country_code, grouping, grouping_label, grouping_kind, as_of
FROM dim_region_group
ORDER BY grouping, country_code;
```

`mart_funder_region` SQL, `_MARTS`, `run()` and the unmapped-funder hint are unchanged.

`DEFINITIONS["mart_region_group"]`. Exact new text: the description gains one sentence at the
end, `grouping_kind` is reworded, and `as_of` is new. `country_code` and `grouping_label` are
unchanged.

```python
"mart_region_group": {
    "description": "One row per country x named region grouping, from the checked-in "
                   "regions.yaml. A country can be in several groupings. Groupings are "
                   "filters: join on country_code (e.g. mart_work_institution); never add "
                   "counts across groupings. Count DISTINCT work_id after joining: "
                   "mart_work_institution has several rows per work. No rows means the "
                   "country is unknown, not outside every grouping; for a share, use works "
                   "whose institution country is in some un_m49_region grouping as the "
                   "denominator. A work with both a known and an unknown location still "
                   "counts toward the denominator, so the share is a lower bound.",
    "columns": {
        "country_code": <unchanged>,
        "grouping": _GROUPING,
        "grouping_label": "Human-readable grouping name.",
        "grouping_kind": "policy (EU or Horizon Europe membership), geographic, "
                         "un_m49_region or un_m49_subregion. Policy groupings are "
                         "membership on the as_of date, not membership when a paper or "
                         "grant was written: the UK is never in eu27.",
        "as_of": "Date the membership lists were last checked against their sources (the "
                 "EU's member-state list, the European Commission's list of countries "
                 "associated to Horizon Europe, UN M49); the same on every row. Policy "
                 "groupings change over time (the UK joined Horizon Europe in 2024), so a "
                 "horizon_associated filter reflects this date. Sources and list versions: "
                 "https://github.com/seandavi/bioc-intelligence/blob/main/src/biocintel/regions.yaml",
    },
},
```

`DEFINITIONS["mart_funder_region"]["description"]`. Exact new text: the denominator clause is
replaced, and the lower-bound and `as_of` sentences are added. Columns are unchanged.

```python
"description": "One row per funder x region grouping. A funder takes the groupings of "
               "its OpenAlex country, except supranational funders OpenAlex gives no "
               "country (European Commission, ERC, Horizon 2020, ...), which take the "
               "curated groupings in regions.yaml. Funders with neither have no rows. "
               "A grouping is where the funder is based, not where the funded "
               "researchers are: EMBL (Germany) is in eu27, WHO (Switzerland) in "
               "horizon_associated. Count DISTINCT work_id after joining: "
               "mart_work_funder has several rows per work (awards, co-funders in the "
               "same grouping). No rows means the location is unknown, not outside every "
               "grouping; for a share, use works with at least one funder that has a row "
               "here as the denominator. A work with both a known and an unknown location "
               "still counts toward the denominator, so the share is a lower bound. "
               "Grouping membership is as of mart_region_group.as_of.",
```

"Works with at least one funder that has a row here" is equivalent to the old clause. Every
grouped code is in exactly one `un_m49_region` grouping, and every curated funder maps to
`EU`, which is in `un_europe`. So the dropped "or has basis curated" was redundant, as the
issue says.

The `DATE` → `date` type mapping already exists in `build_marts` (`datapackage.json`), so
`as_of` needs no type plumbing.

### CLI / `run()` entry points

None new. `biocintel build-marts` reloads the dims and writes `mart_region_group.parquet` with
the extra column.

### Upstream APIs and fixtures

None. No HTTP and no fixture files.

## Acceptance criteria

- [ ] `regions._parse` exists and is pure (text in, dict out). `regions._regions()` is
      `@cache`d and only reads the packaged file and calls `_parse`.
- [ ] `_parse` raises `ValueError` whose message starts with `grouping 'eu27':` for each of:
      `countries: [DE, EU]`, `countries: NO`, `countries: ''`, a missing `label`, a duplicate
      code (`DE DE EU`), a lowercase or 3-letter code, an unknown kind, and a duplicate
      grouping id. It raises `grouping 'EU-27':` for a bad grouping id, `funder 'F1':` for a
      duplicate funder id, a missing funder `country`, or a country in no grouping, and
      `funder 'X1':` for a bad funder id.
- [ ] `_parse` raises `ValueError` matching `as_of` when `as_of` is missing, quoted
      (`'2026-10-23'`) or a datetime.
- [ ] `tests/test_regions.py` has no `monkeypatch` and no `cache_clear`.
- [ ] `_regions()["groupings"][g]["countries"]` is a `tuple` for every grouping.
- [ ] `len(regions._regions()["funders"]) == 23` and `len(regions.funder_region_rows()) == 69`.
- [ ] `regions.yaml` has `as_of: 2026-10-23` and the header line points at it.
      `regions._regions()["as_of"] == datetime.date(2026, 10, 23)`.
- [ ] `region_group_rows()` returns 5-tuples ending in `as_of`. Grouping membership is
      unchanged: 26 groupings, 250 codes, 604 rows, and every existing membership test passes.
- [ ] After `load_regions` + `_MART_SQL` on an in-memory store, `mart_region_group` has columns
      `country_code, grouping, grouping_label, grouping_kind, as_of`. `as_of` is type `DATE`,
      and every row has `as_of = DATE '2026-10-23'`.
- [ ] Migration: a store whose `dim_region_group` was created with the #91 four-column DDL
      gains `as_of` on `db.init_schema`, and `load_regions` then fills it.
- [ ] `DEFINITIONS` text for `mart_region_group` (`description`, `grouping_kind`, new `as_of`)
      and `mart_funder_region` (`description`) matches this spec exactly.
      `tests/test_views_db.py` passes unchanged.
- [ ] `bioc-intelligence-spec.md` §5 lists `as_of` in `dim_region_group(...)` and
      `mart_region_group(...)`.
- [ ] No other mart's columns or rows change. `mart_funder_region` is byte-for-byte the same
      SQL.
- [ ] `uv run pytest` and `uv run ruff check src tests` pass.

## Test plan

All in `tests/test_regions.py`, offline:

1. **Existing tests, updated for 5-tuples.** `_members()` and the kinds loop in
   `test_every_country_has_one_m49_region_and_subregion` unpack as
   `code, grouping, _, kind, _` (or `code, grouping, *_`). `test_country_codes_are_strings...`
   uses `{g for _, g, *_ in rows}`. Add `assert len(rows) == 604`.
2. **`test_malformed_regions_yaml_is_rejected`**, rewritten. `_BASE` gains a first line
   `as_of: 2026-10-23`. The test body is:

   ```python
   @pytest.mark.parametrize("old, new, match", [...])
   def test_malformed_regions_yaml_is_rejected(old, new, match):
       assert old in _BASE
       with pytest.raises(ValueError, match=match):
           regions._parse(_BASE.replace(old, new))
   ```

   Add `test_base_regions_yaml_parses()`: `regions._parse(_BASE)` succeeds. This proves each
   case fails only because of its own edit. Cases (`old` → `new`, `match`). `_C` is the
   `countries` block of `_BASE`, `">-\n      DE EU"`:

   | old | new | match |
   |---|---|---|
   | `DE EU` | `de EU` | `grouping 'eu27': bad country code` |
   | `DE EU` | `DEU EU` | `grouping 'eu27': bad country code` |
   | `DE EU` | `DE DE EU` | `grouping 'eu27': duplicate country code` |
   | `kind: policy` | `kind: bogus` | `grouping 'eu27': unknown kind` |
   | `supranational_funders:` | a second `eu27` grouping (as today) + `supranational_funders:` | `grouping 'eu27': duplicate grouping id` |
   | `id: eu27` | `id: EU-27` | `grouping 'EU-27': id must match` |
   | `_C` | `[DE, EU]` | `grouping 'eu27': countries must be a string` |
   | `_C` | `NO` | `grouping 'eu27': countries must be a string` |
   | `_C` | `''` | `grouping 'eu27': no countries` |
   | `    label: EU\n` | `` | `grouping 'eu27': label must be a string` |
   | `id: F1` | `id: X1` | `funder 'X1': id must match` |
   | `country: EU}` | `country: EU}\n  - {id: F1, name: "EC", country: EU}` | `funder 'F1': duplicate funder id` |
   | `, country: EU` | `` | `funder 'F1': country must be a string` |
   | `country: EU` | `country: FR` | `funder 'F1': country 'FR' is in no grouping` |
   | `as_of: 2026-10-23\n` | `` | `as_of` |
   | `as_of: 2026-10-23` | `as_of: '2026-10-23'` | `as_of` |
   | `as_of: 2026-10-23` | `as_of: 2026-10-23 10:00:00` | `as_of` |

   Every `old` occurs exactly once in `_BASE` (`DE EU` only inside `_C`). `match` is a regex.
   The fragments above contain no regex metacharacters. All 17 cases were prototyped against
   the `_parse` code above and raise the listed message.
3. **`test_supranational_funder_count_is_pinned`**: `len(regions._regions()["funders"]) == 23`
   and `len(regions.funder_region_rows()) == 69`.
4. **`test_cached_countries_are_tuples`**: every `_regions()["groupings"][g]["countries"]` is a
   `tuple`.
5. **`test_region_group_mart_carries_as_of`**: in-memory store, `init_schema`, `load_regions`,
   `con.execute(_MART_SQL)`. Then
   `SELECT DISTINCT as_of FROM mart_region_group` == `[(datetime.date(2026, 10, 23),)]`, and
   `DESCRIBE mart_region_group` gives the five columns in order with `as_of` typed `DATE`.
6. **`test_region_group_as_of_migrates_old_store`**: on `db.connect(":memory:")`, run the #91
   four-column `CREATE TABLE dim_region_group (...)` (without `as_of`) first, then
   `db.init_schema(con)` and `regions.load_regions(con)`. Assert
   `SELECT count(*) FROM dim_region_group WHERE as_of IS NULL` is 0 and the row count is 604.
7. `test_load_regions_is_idempotent`, `test_funder_region_mart_country_and_curated_basis` and
   `test_curated_mapping_replaces_country` stay as they are and must pass.

`tests/test_views_db.py` (iterates `_MARTS`, checks DEFINITIONS covers every column) needs no
edit. It fails if `as_of` lacks a definition.

## Risks

- **Views file and published Parquet.** `mart_region_group` gains a column. The PR must say:
  after merge, the next monthly refresh publishes the new Parquet, and **the views file must
  then be regenerated** (`write_views_db` warns that the bound schema differs). Until then,
  DuckDB 1.0 clients reading the old views file over the new Parquet get "Contents of view were
  altered" for `mart_region_group` only. No manual data run is needed beyond that regeneration.
- **`as_of` goes stale silently.** Nothing checks that someone actually re-checked the lists
  before bumping the date, or that they bumped it after a re-check. The YAML comment states the
  rule. It is a human-curated date, the same as the lists.
- **Stricter validation can break a future hand edit** that today loads by accident, e.g. a
  quoted `as_of` or a funder entry without `country`. That is the intent: the build fails with
  a message naming the entry.
- **The outer cached dict is still mutable** (only `countries` becomes a tuple, as the issue
  suggests). All callers in the tree only read it.

## Verification (2026-10-23)

- `uv run python`: `yaml.safe_load('as_of: 2026-10-23')` → `{'as_of': datetime.date(2026, 10, 23)}`.
  The quoted form gives a `str`. `'a: 2026-10-23 10:00:00'` gives a `datetime`.
  `yaml.safe_load('countries: NO')` → `{'countries': False}`.
- Current packaged YAML: `len(_regions()['funders']) == 23`, `len(funder_region_rows()) == 69`,
  `len(region_group_rows()) == 604`.
- DuckDB 2.0.0: `ALTER TABLE t ADD COLUMN IF NOT EXISTS c DATE` on a populated table works
  (existing rows NULL). `... ADD COLUMN IF NOT EXISTS d DATE NOT NULL` fails with "Not
  implemented Error: Adding a NOT NULL column with IF NOT EXISTS is not supported".
- `seandavi/bioc-intelligence` is public, so the GitHub URL in the `as_of` definition resolves
  for readers.
- `grep -rn "region_group\|funder_region" frontend/src` finds nothing: no frontend reads either
  region mart.
- The `_parse`/`_check_entry` code in this spec, run against the packaged YAML with
  `as_of: 2026-10-23` inserted, gives 26 groupings, 23 funders and 604 codes. All 17 malformed
  cases in the test plan raise the listed message.
