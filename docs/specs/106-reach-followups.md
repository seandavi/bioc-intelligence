# Spec #106: follow-ups from the #92 review (package reach)

Issue: [#106](https://github.com/seandavi/bioc-intelligence/issues/106). Base:
[`docs/specs/92-package-reach.md`](92-package-reach.md), merged in `eeee975` (#107).

*Spec stage, 2026-10-23. The OpenAlex facts below were checked that day with curl. See
"Verification".*

## Goal

Close the six findings in #106:

| Finding | What changes |
|---|---|
| code-r0-1 | `enrich_from_lake.py` module docstring: summary line names `fact_package_reach`, the stray blank line goes, the `reach` bullet uses double backticks |
| code-r0-2 | one blank line between `_FUNDER_DIM_SQL` and the `_REACH_WORKS_SQL` comment |
| data-r0-1 | new `fact_package_reach.n_works INTEGER` (+ migration), filled from `len(ids)` in `_enrich_reach`, carried into `mart_package_reach`; DEFINITIONS say the counts cover "confident primary papers that OpenAlex resolves (n_works of them)" |
| data-r0-2 | DEFINITIONS `mart_package_reach` description says it is not `mart_package_impact.n_citing_works` |
| data-r0-3 | `dimension` / `key` text says "author affiliation", not "author" |
| data-r0-4 | description says a funder with no row may still fund citing works, and when the funder list is complete |

## Non-goals

- `n_works`, not `oa_ids VARCHAR[]`: the issue offers both. A list repeated on every row of a
  2048-row-group mart buys nothing the frontend needs; the ids are reproducible from
  `bridge_package_pub` + `dim_work`. The count is what makes a snapshot-to-snapshot jump
  explainable.
- No change to which works are counted: `_REACH_WORKS_SQL` keeps `AND l.oa_id IS NOT NULL`. A
  confident paper with no live id is still left out; it is now visible as a lower `n_works`.
- No new HTTP calls, no new fixture files. `n_works` is `len(ids)` of ids already in hand.
- No change to `mart_package_impact` or its `n_citing_works` text.
- No frontend change: nothing under `frontend/src` reads `mart_package_reach`.
- No data run. `reach` is opt-in and has never run in production: the production store has
  no `fact_package_reach` table, and the published views file (last published 2026-10-07) has
  no `mart_package_reach` view. The new column ships with the first reach run and the next
  views-file regeneration, both of which happen anyway.
- `docs/specs/92-package-reach.md` and `docs/international-impact.md` are not edited.

## Design

### Files

| File | Change |
|---|---|
| `src/biocintel/pipeline/enrich_from_lake.py` | docstring (code-r0-1); blank line (code-r0-2); `_enrich_reach` writes `n_works` with an explicit column list |
| `src/biocintel/schema.sql` | `fact_package_reach.n_works` column + comment |
| `src/biocintel/db.py` | `init_schema` migration: `ADD COLUMN IF NOT EXISTS n_works INTEGER` |
| `src/biocintel/pipeline/build_marts.py` | `mart_package_reach` SQL selects `r.n_works`; `DEFINITIONS["mart_package_reach"]` text |
| `bioc-intelligence-spec.md` | `fact_package_reach` and `mart_package_reach` column lists (§5) |
| `CLAUDE.md` | `reach` bullet mentions `n_works` |
| `tests/test_marts.py` | update `test_package_reach_mart_latest_snapshot_and_shares`; one new migration test |
| `tests/test_sources.py` | `_seed_reach_bridge` insert; `test_enrich_reach_from_api` asserts `n_works` |
| `tests/test_extract_people.py` | `test_rerun_keeps_reach_funders` insert |

### code-r0-1: module docstring (`enrich_from_lake.py`, lines 1-32)

Line 1 becomes (88 chars; the old text plus `fact_package_reach` is 105, over ruff's 100):

```python
"""enrich_from_lake — fill dim_work, dim_grant, fact_citation_edge, fact_package_reach.
```

Delete the blank line between the `citations` bullet ("…Run it deliberately for a full
refresh.") and the `reach` bullet. The `reach` bullet becomes:

```
- **reach** (opt-in, api-only) — per package, the works citing its ``doi``/``citation_file``
  primary papers (one OR'd ``cites:`` filter over this run's live OpenAlex ids), counted by
  author affiliation country and by funder via OpenAlex ``group_by`` → ``fact_package_reach``
  (snapshot-stamped, with ``n_works``, the papers counted); citing-work funders are merged
  into ``dim_funder`` (#92). Needs ``OPENALEX_API_KEY`` (~2 calls per package). Best-effort.
```

Each line stays ≤ 100 chars.

### code-r0-2: blank line (`enrich_from_lake.py`, lines 253-254)

Insert one empty line between the closing `"""` of `_FUNDER_DIM_SQL` and
`# Each package's confident primary works with a live OpenAlex id: …`. The comment text is
unchanged.

### data-r0-1: `n_works`

**DDL (`schema.sql`, `fact_package_reach`)**. Append the column after `_snapshot`, so a fresh
store and a migrated one have the same column order (`ALTER … ADD COLUMN` appends; the
`alias_dois` and `as_of` columns follow the same rule). The table comment gains one sentence:

```sql
-- Works citing each package's confident primary papers, counted by OpenAlex group_by (#92).
-- Append-only, snapshot-stamped. Counts are distinct citing works per row; never add them
-- across packages or keys (a work has several countries and funders). n_works is per
-- package, repeated on every row of it (#106).
CREATE TABLE IF NOT EXISTS fact_package_reach (
    package_name  VARCHAR NOT NULL,
    repo          VARCHAR NOT NULL,
    dimension     VARCHAR NOT NULL,       -- 'total' | 'country' | 'funder'
    key           VARCHAR,                -- ISO alpha-2 | OpenAlex funder id 'F…'; NULL = unknown (and the total row)
    key_name      VARCHAR,                -- OpenAlex display name; NULL with key
    n_citing      BIGINT NOT NULL,
    _snapshot     DATE NOT NULL,
    n_works       INTEGER                 -- confident primary papers with a live OpenAlex id (the cites: list); NULL before #106
);
```

Nullable: rows written before #106 have no value, and no backfill is possible.

**Migration (`db.py`, `init_schema`)**. After the `dim_region_group … as_of` line:

```python
    con.execute("ALTER TABLE fact_package_reach ADD COLUMN IF NOT EXISTS n_works INTEGER")
```

No new module-level list: one column, as `as_of` and `source_release` are done.

**Writer (`enrich_from_lake.py`, `_enrich_reach`)**. Every row tuple gains `len(ids)` as a
seventh element, and the insert names its columns (`ids` is already the package's distinct
sorted OpenAlex ids from `_REACH_WORKS_SQL`; `ids = tuple(ids)` comes first):

```python
        res = memo[ids]
        rows.append((pkg, repo, "total", None, None, res["country"][0], len(ids)))
        for dim, (_, groups) in res.items():
            rows += [(pkg, repo, dim, key, name, n, len(ids)) for key, name, n in groups]
```

```python
            con.executemany(
                "INSERT INTO bi.fact_package_reach (package_name, repo, dimension, key, key_name, "
                "n_citing, n_works, _snapshot) VALUES (?, ?, ?, ?, ?, ?, ?, current_date)",
                rows,
            )
```

The funder-id comprehension (`r[3]` where `r[2] == "funder"`) is unchanged: indexes 2 and 3
do not move. `n_works` is always ≥ 1: `_REACH_WORKS_SQL` inner-joins `linked` and drops NULL
ids, so a package with no resolved paper has no rows at all (unchanged).

**Mart (`build_marts.py`, `_MART_SQL`, `mart_package_reach`)**. Select `r.n_works` between
`share_of_citing` and `_snapshot`:

```sql
SELECT r.package_name, r.repo, r.dimension, r.key, r.key_name, r.n_citing,
       t.n_citing                         AS n_citing_total,
       r.n_citing / NULLIF(t.n_citing, 0) AS share_of_citing,
       r.n_works,
       r._snapshot
```

Mart columns, in order: `package_name, repo, dimension, key, key_name, n_citing,
n_citing_total, share_of_citing, n_works, _snapshot`. `n_works` is INTEGER.

### DEFINITIONS `mart_package_reach` (`build_marts.py`, data-r0-1..4)

Keep the existing literal-concatenation style. `**_PKG`, `key_name`, `n_citing_total`,
`share_of_citing` and `_snapshot` are unchanged. The others become, once joined, exactly:

**`description`**:

> One row per package x dimension (total, country, funder) x key: works citing the package's
> confident primary papers (match_method doi, doi_alias or citation_file) that OpenAlex
> resolves (n_works of them), counted by OpenAlex at the latest snapshot. A confident paper
> with no live OpenAlex id is left out, so a package's total can change between snapshots
> because n_works did, not only because more works cite it. n_citing counts distinct citing
> works across all of those papers (one OR'd query), so a work citing two of them counts
> once. Values are not additive: not across packages (a work citing two packages counts for
> each) and not across keys (a work counts once for every author affiliation country and
> every funder), so adding countries into a region over-counts. Join key to
> mart_region_group or mart_funder_region to filter rows, and read each key on its own.
> Funder rows are the 200 largest only (the unknown, NULL-key row among them), so they do not
> add up to the total even before overlap. A funder with no row may still fund citing works
> below the top 200; a package with fewer than 200 funder rows has its full list. Not the
> same as mart_package_impact.n_citing_works, which counts stored citation edges over all
> linked papers (including description_doi).

**`dimension`**:

> total (one row: all distinct citing works), country (a country of any author affiliation
> on the citing work, OpenAlex authorships.countries) or funder (a funder OpenAlex lists on
> the citing work; the 200 largest only).

**`key`**:

> ISO 3166-1 alpha-2 country code (joins mart_region_group.country_code) or OpenAlex funder
> id F... (joins mart_funder_region.funder_id). NULL on the total row, and on the row
> counting citing works with no known affiliation country or no listed funder: NULL means
> unknown, not elsewhere.

**`n_citing`**:

> Distinct citing works with this key, across the package's n_works confident primary papers
> (total row: all citing works). Not additive across packages or keys.

**`n_works`** (new; insert between `share_of_citing` and `_snapshot`):

> Confident primary papers OpenAlex resolves to a live work at this snapshot: the papers
> every count on the package's rows covers (the same value on each of its rows). A confident
> paper OpenAlex does not resolve is not counted, so a change in n_works between snapshots
> moves the counts for reasons other than new citing works. NULL on snapshots fetched before
> n_works was recorded.

"The unknown, NULL-key row among them" is new relative to the issue's wording: the curl below
shows OpenAlex's 200-group cap includes the `unknown` group, so "200 funder rows" in the
issue's sentence counts that row too.

### `bioc-intelligence-spec.md` (§5)

```text
fact_package_reach(                    -- (#92)
  package_name, repo,
  dimension,                           -- 'total' | 'country' | 'funder'
  key, key_name,                       -- NULL key = unknown (and the total row)
  n_citing, _snapshot,
  n_works                              -- resolved confident primary papers counted (#106)
)
```

```text
mart_package_reach(                    -- citing-work countries/funders per package (#92)
  package_name, repo, dimension, key, key_name,
  n_citing, n_citing_total, share_of_citing, n_works, _snapshot
)
```

### `CLAUDE.md`

In the `reach` bullet, change "→ `fact_package_reach` (country, funder, total;
snapshot-stamped)" to "→ `fact_package_reach` (country, funder, total, with `n_works`, the
resolved papers counted; snapshot-stamped)".

### Entry points

None change. `python -m biocintel.pipeline.enrich_from_lake --steps reach`
(`enrich_from_lake.run(("reach",), source="api")`) writes `n_works`; `biocintel build-marts`
(`build_marts.run()`) carries it into `mart_package_reach`; `biocintel init-db` /
`db.init_schema` migrates an existing store.

## Acceptance criteria

- [ ] `enrich_from_lake.py` line 1 is exactly the docstring line above; the module docstring
      has no blank line between the `citations` and `reach` bullets; the `reach` bullet has no
      single-backtick spans.
- [ ] Exactly one blank line separates `_FUNDER_DIM_SQL`'s closing `"""` from the
      `_REACH_WORKS_SQL` comment.
- [ ] A fresh `init_schema` store's `fact_package_reach` columns are, in order,
      `package_name, repo, dimension, key, key_name, n_citing, _snapshot, n_works`, with
      `n_works` INTEGER and nullable.
- [ ] `init_schema` on a store whose `fact_package_reach` lacks `n_works` adds it; existing
      rows read NULL; running `init_schema` twice is a no-op.
- [ ] After `enrich_from_lake.run(("reach",), source="api")` on the `_seed_reach_bridge`
      fixture, every current-snapshot row has `n_works` = 1 for `limma`, `sesame`, `sesame2`
      and 2 for `pair`.
- [ ] `mart_package_reach` columns are `package_name, repo, dimension, key, key_name,
      n_citing, n_citing_total, share_of_citing, n_works, _snapshot`, and `n_works` equals
      the fact row's value.
- [ ] `DEFINITIONS["mart_package_reach"]` has an `n_works` entry (the build fails without
      one), and the `description`, `dimension`, `key`, `n_citing` and `n_works` strings equal
      the text above once the literals are joined. In particular the description contains
      "that OpenAlex resolves (n_works of them)", "Not the same as
      mart_package_impact.n_citing_works" and "A funder with no row may still fund citing
      works below the top 200"; `dimension` contains "author affiliation"; no string contains
      "a country of any author on" or "no known author country".
- [ ] `bioc-intelligence-spec.md` §5 and `CLAUDE.md` mention `n_works` as above.
- [ ] `uv run pytest` and `uv run ruff check src tests` pass (set up first with
      `uv venv && uv pip install -e '.[dev]'`; the worktree has no venv yet).
- [ ] No change under `data/` or `frontend/public/data/`; no new fixture files.

## Test plan

All offline, using the existing recorded fixtures `tests/fixtures/api/openalex_reach_countries.json`
and `openalex_reach_funders.json`. No new fixture files.

1. **Update** `tests/test_marts.py::test_package_reach_mart_latest_snapshot_and_shares`.
   Each positional `VALUES` tuple gains an eighth value (column order is now
   `…, n_citing, _snapshot, n_works`): `NULL` on the two `2026-09-01` rows, `2` on the four
   `limma` `2026-10-01` rows, `1` on `zero`. The `cols` assertion becomes
   `["package_name", "repo", "dimension", "key", "key_name", "n_citing", "n_citing_total",
   "share_of_citing", "n_works", "_snapshot"]`; the snapshot check reads `r[9]` instead of
   `r[8]`. Add
   `assert dict(con.execute("SELECT package_name, max(n_works) FROM mart_package_reach GROUP
   BY 1").fetchall()) == {"limma": 2, "zero": 1}`. The `rows` (`r[5:8]`) assertion is
   unchanged.
2. **New** `tests/test_marts.py::test_package_reach_n_works_migrates_pre_106_store`:
   `db.connect(":memory:")`; create the #92 table by hand
   (`CREATE TABLE fact_package_reach (package_name VARCHAR NOT NULL, repo VARCHAR NOT NULL,
   dimension VARCHAR NOT NULL, key VARCHAR, key_name VARCHAR, n_citing BIGINT NOT NULL,
   _snapshot DATE NOT NULL)`) and insert `('limma','bioc','total',NULL,NULL,10,'2026-09-01')`.
   Call `db.init_schema(con)` twice. Assert `information_schema.columns` for the table gives
   `n_works` with `data_type` `INTEGER` as the last column, and `SELECT n_works FROM
   fact_package_reach` is `[(None,)]`. Then `con.execute(_MART_SQL)` and assert `SELECT
   n_works, n_citing_total FROM mart_package_reach` is `[(None, 10)]` (a pre-#106 snapshot
   still builds).
3. **Update** `tests/test_sources.py::_seed_reach_bridge`: the `old` row's `VALUES` gains a
   trailing `NULL`.
4. **Update** `tests/test_sources.py::test_enrich_reach_from_api`: after the `per_package`
   assertion, add
   ```python
   assert con.execute(
       "SELECT package_name, min(n_works), max(n_works) FROM fact_package_reach "
       "WHERE _snapshot = current_date GROUP BY 1 ORDER BY 1"
   ).fetchall() == [("limma", 1, 1), ("pair", 2, 2), ("sesame", 1, 1), ("sesame2", 1, 1)]
   ```
   (`pair` is the only package with two resolved papers, matching the existing
   `"cites:W2146512944|W4392168904" in calls` assertion.)
5. **Update** `tests/test_extract_people.py::test_rerun_keeps_reach_funders`: both
   `fact_package_reach` `VALUES` tuples gain a trailing `1`. Assertions unchanged.

`test_reach_skips_without_api_key` and `test_reach_outage_keeps_last_snapshot` pass with
only the `_seed_reach_bridge` change. No DEFINITIONS-text test beyond what the build already
enforces: the acceptance check is a read of the literals.

## Risks

- **Views file.** `mart_package_reach` gains a column. It is not in the published views file
  yet, so no 1.0 client can hit "Contents of view were altered" from this change. The PR
  should still say the views file is regenerated after the first marts deploy that carries
  the reach mart, as with any new mart.
- **`n_works` counts resolved papers, not all confident ones.** It shows a drop in resolved
  papers but not which paper dropped, and the number of confident papers that OpenAlex did
  not resolve is not stored. Accepted: the issue asks for the resolved count, and the
  confident set is in `bridge_package_pub`.
- **Old snapshots keep NULL.** `mart_package_reach` uses only the latest snapshot, so NULL
  reaches the mart only if no reach run has happened since this merge. The definition says
  so.

## Verification (2026-10-23)

- `GET https://api.openalex.org/works?filter=cites:W2146512944&group_by=funders.id:include_unknown&per-page=200`
  (limma's paper, keyless): `meta.count` 38,833, `groups_count` 200, and the first of the 200
  groups is `{"key": "unknown", "count": 10551}`. The last is Emory University (71). So the
  unknown group takes one of the 200 slots, which the description now says.
- `GET https://api.openalex.org/works/W2146512944?select=id,authorships`: each authorship's
  `countries` equals its `institutions[].country_code` (e.g. `["AU"]` for two Australian
  institutions, `["US"]` for Harvard). The OpenAlex authorship docs
  (`docs.openalex.org/api-entities/works/work-object/authorship-object`) say the
  institutions' countries are mirrored into `countries`, so the field holds affiliation
  countries, not nationality (data-r0-3).
- The production store (`../bioc-intelligence/data/biocintel.duckdb`, opened read-only) has
  no `fact_package_reach` table, and
  `../bioc-intelligence/frontend/public/data/bioc-intelligence.duckdb` has no view matching
  `%reach%`. There are no stored reach rows to migrate or compare.
