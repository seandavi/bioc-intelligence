# Spec #92: `mart_package_reach`, the citing-work countries and funders per package

Issue: [#92](https://github.com/seandavi/bioc-intelligence/issues/92). Background:
`docs/international-impact.md` §2 and recommendation 3. Related: #91 (region groupings, merged)
and #95 (stored OpenAlex ids drift).

## Goal

For every package, count the research that cites its papers, by author country and by funder,
using OpenAlex `group_by` on the works citing the package's confident primary papers. Store the
counts as an append-only, snapshot-stamped fact (`fact_package_reach`) and export them as
`mart_package_reach`. The frontend filters that mart with the #91 groupings
(`mart_region_group` for countries, `mart_funder_region` for funders). The step is opt-in and
best-effort, like `institutions`: a failure logs, skips and keeps the last snapshot.

## Non-goals

- **No frontend change** and no `export_api` change. The mart is published by the existing
  `sync-marts.sh` glob. Showing it on the Package page is a follow-up issue.
- **No ecosystem-wide distinct counts** (citing-work funders joined to `fact_citation_edge`,
  ~7k calls). The issue rules this out of scope.
- **No region-level distinct counts.** Getting "N EU-authored works cite DESeq2" needs one
  filter call per grouping (`authorships.countries:DE|FR|…`) and is a follow-up. Per-country rows
  can't be summed into a region (see Risks).
- **No funder long tail.** Cursor paging works on `group_by`, but paging past page 1 needs a key
  and returns groups sorted by id rather than by count. Funder rows stay at the top 200 by count,
  as the issue accepts.
- **No change to `systemd/biocintel-refresh.service`** in this PR (see *Production*).
- **No fix for #95.** This step avoids the stale-id trap by reading this run's live ids (below).
  It does not repair `dim_work`.

## What upstream looks like (verified 2026-10-23, keyless curl)

1. **Countries.**
   `https://api.openalex.org/works?filter=cites:W2179438025&group_by=authorships.countries:include_unknown&per-page=200`
   → 200. `meta.count` = 91,675 (distinct citing works) and `meta.groups_count` = 181: 180
   countries plus `{"key": "https://openalex.org/countries/UNKNOWN", "key_display_name":
   "unknown", "count": 2117}`. Groups are sorted by `count` descending, and each is
   `{"key": "https://openalex.org/countries/US", "key_display_name": "United States", "count":
   35415}`. Each call costs `meta.cost_usd` = 0.0001. Group counts sum to 142,814 > 91,675,
   because a work counts once for each of its authors' countries.
2. **Funders.** `...&group_by=funders.id:include_unknown&per-page=200` → 200 groups,
   `groups_count` = 200, which is the cap: the long tail is truncated. Keys are
   `https://openalex.org/F4320320879` (DFG, 4,296), and the unknown group is
   `{"key": "unknown", "key_display_name": "unknown", "count": 16036}`. So **the two unknown
   spellings differ**: the country one is `…/countries/UNKNOWN`, the funder one is a bare
   `unknown`.
3. **OR = distinct citing works.** Counts for `filter=cites:W2179438025` (DESeq2), `cites:W2146512944`
   (limma), `cites:W2179438025,cites:W2146512944` (both) and `cites:W2179438025|W2146512944`
   (either) are 91,675, 38,833, 5,666 and **124,842 = 91,675 + 38,833 − 5,666**. An OR'd filter
   counts each citing work once.
4. **A stale id silently returns zero.** `W2921099115` is a stored `dim_work.openalex_id` for
   `10.1101/577452`. `GET /works/W2921099115` → 404, but `filter=cites:W2921099115` → 200 with
   `count: 0` and `group_by: []`. Looking up `doi:10.1101/577452` now returns `W2970457274`. A
   reach call keyed on a stored id would therefore record a fake zero.
5. **Keyless limits.** Page 1 with `cursor=*` is served keyless. Page 2 is
   `{"error": "API key required for cursor paging"}`, which is why paging is out (non-goals). Keyless
   budget is $0.10/day, about 1,000 calls, shared per IP.
6. **No `group_by=funders.country_code`.** The request returns an error body with no `meta`.
   Funder countries come from `/funders` (step 3 below).
7. **Fixture source.** sesame's paper `W4392168904` (already in `tests/fixtures/api`) has 24 citing
   works. Countries: 17 groups (US 13, DE 2, …, UNKNOWN 2). Funders: 31 groups (unknown 8,
   F4320332161 NIH 7, F4320337354 NIGMS 6, F4320337348 NHGRI 3, …, F4320320300 European
   Commission 1).

Working-set size, from a copy of the production store (snapshot 2026-10-07): 947 packages
have ≥1 `doi`/`citation_file` primary link to a work with an OpenAlex id, and they form 893
distinct work sets. 746 of the 967 linked packages have exactly one work, and the rest have up
to 10. So one run is about 893 × 2 group_by calls plus ⌈funders/50⌉ `/funders` calls: roughly
2k calls, about $0.20.

## Design

### Approved decisions (supervisor, 2026-10-23)

- **Grain: per package, OR'd.** One `cites:W1|W2|…` call per package per dimension, over the
  package's distinct live OpenAlex ids. This renames the issue's `fact_work_reach` to
  `fact_package_reach`. Per-work counts can't give a package number for the 221 packages with
  several works.
- **Which links count:** `bridge_package_pub.role = 'primary' AND match_method IN ('doi',
  'citation_file')`, the same set as the `package_pubs_confident` view. `description_doi` is
  excluded because it sometimes cites a dependency's paper and would credit the package with
  that paper's citers.
- **Live ids only:** ids come from this run's `linked` temp table, which `_fill_for_enrich`
  re-resolves from PMID/DOI every run. Never from `dim_work.openalex_id`, because of item 4 above.
- **Funder regions:** the step fetches `/funders` for the reach funder ids and merges them into
  `dim_funder` (`curated = false`), so `mart_funder_region` covers them unchanged.
  `extract_people._write` must keep those rows (below).
- Opt-in (`--steps …,reach`), api-only, and skipped when `OPENALEX_API_KEY` is unset. No keyless
  fallback. `:include_unknown` → NULL-key row. A `dimension = 'total'` row carries `meta.count`.
  Funders are top-200.

### `src/biocintel/sources/openalex.py`

Add next to `cited_by`:

```python
# Reach dimensions (#92) -> OpenAlex group_by field.
REACH_GROUP_BY = {"country": "authorships.countries", "funder": "funders.id"}


def citing_groups(oa_ids: Sequence[str], group_by: str) -> tuple[int, list[tuple]]:
    """Works citing any of ``oa_ids`` (one OR'd filter, so distinct citing works), grouped by
    ``group_by``: ``(meta.count, [(key, key_name, count), ...])``. At most 200 groups, the
    largest first (no paging). The unknown group comes back as ``(None, None, count)``."""
```

- One call: `_get("works", {"filter": "cites:" + "|".join(oa_ids), "group_by":
  f"{group_by}:include_unknown", "per-page": PER_PAGE})`. `_get` already adds `api_key` and
  `mailto`, never caches, and raises `RuntimeError` without the key on failure.
- Each group maps to `key = bare_id(g["key"])`. That's `US` from `…/countries/US`, `F4320320879`
  from `…/F4320320879`, `UNKNOWN` from `…/countries/UNKNOWN`, and `unknown` from `unknown`. If
  `key.lower() == "unknown"`, the tuple is `(None, None, g["count"])`; otherwise it's
  `(key, g.get("key_display_name"), g["count"])`. Order is as returned.
- Returns `(page["meta"]["count"], groups)`.
- Add `Sequence` to the existing `collections.abc` import. No length guard: a package has at
  most 10 works, and OpenAlex allows 100 OR values (`# ponytail:` comment naming that ceiling).

### `src/biocintel/pipeline/enrich_from_lake.py`

- `ALL_STEPS = ("works", "institutions", "funders", "grants", "citations", "reach")`.
  `DEFAULT_STEPS` is unchanged.
- Import: `from ..sources import connect_with_sources, openalex` (plus `import os`).
- Module docstring: add a bullet. "**reach** (opt-in, api-only) — per package, the works citing
  its `doi`/`citation_file` primary papers (one OR'd `cites:` filter over this run's live
  OpenAlex ids), counted by author country and by funder via OpenAlex `group_by` →
  `fact_package_reach` (snapshot-stamped); citing-work funders are merged into `dim_funder`
  (#92). Needs `OPENALEX_API_KEY` (~2 calls per package). Best-effort."

New SQL constants:

```python
# Each package's confident primary works with a live OpenAlex id: this run's `linked`, never
# a stored dim_work.openalex_id, which can be stale, and a stale id's `cites:` filter
# returns 0, not an error (#95). Same set as the package_pubs_confident view.
_REACH_WORKS_SQL = """
SELECT b.package_name, b.repo, list_sort(list(DISTINCT l.oa_id)) AS oa_ids
FROM bi.bridge_package_pub b
JOIN linked l ON b.work_id = CAST(l.pmid AS VARCHAR) OR b.work_id = l.doi
WHERE b.role = 'primary' AND b.match_method IN ('doi', 'citation_file')
  AND l.oa_id IS NOT NULL
GROUP BY b.package_name, b.repo
ORDER BY b.package_name, b.repo;
"""

# Citing-work funders join dim_funder so mart_funder_region can group them (#91). A curated
# or already-enriched row keeps its name/curated flag; registry fields fill in, never blank out.
_REACH_FUNDER_DIM_SQL = """
INSERT INTO bi.dim_funder (funder_id, name, curated, ror, crossref_id, country_code)
SELECT r.key, COALESCE(any_value(f.display_name), any_value(r.key_name), r.key), false,
       any_value(f.ror), any_value(f.crossref_id), any_value(f.country_code)
FROM (SELECT DISTINCT key, key_name FROM bi.fact_package_reach
      WHERE _snapshot = current_date AND dimension = 'funder' AND key IS NOT NULL) r
LEFT JOIN reach_funder f ON f.id = r.key
GROUP BY r.key
ON CONFLICT (funder_id) DO UPDATE SET
    ror = COALESCE(excluded.ror, ror),
    crossref_id = COALESCE(excluded.crossref_id, crossref_id),
    country_code = COALESCE(excluded.country_code, country_code);
"""
```

(`COALESCE(excluded.x, x)` in `DO UPDATE` was checked on DuckDB 2.0.0: it keeps the existing
value when the new one is NULL.)

New function:

```python
def _enrich_reach(con: duckdb.DuckDBPyConnection) -> int:
    """fact_package_reach rows for today's snapshot (+ citing-work funders into dim_funder)."""
```

1. `packages = con.execute(_REACH_WORKS_SQL).fetchall()`. Memoise on the id tuple:
   `memo: dict[tuple[str, ...], dict[str, tuple[int, list[tuple]]]]`, filled with
   `{dim: openalex.citing_groups(ids, field) for dim, field in openalex.REACH_GROUP_BY.items()}`.
   Print once before the loop:
   `f"  reach: {len(packages)} packages, {len(sets)} distinct work sets "
   f"(~{2 * len(sets)} OpenAlex calls)…"`.
2. Build `rows: list[tuple]` of `(package_name, repo, dimension, key, key_name, n_citing)`.
   Each package gets one `(pkg, repo, "total", None, None, res["country"][0])`, then every
   country and funder group. The total is `meta.count` of the country call; both calls share the
   filter, so it is the same.
3. `funder_ids = sorted({r[3] for r in rows if r[2] == "funder" and r[3] is not None})`. Then
   `funders = [openalex.funder_row(r) for r in openalex.fetch_by("funders", "openalex_id",
   funder_ids, openalex.FUNDER_FIELDS)]`.
4. **All fetching happens before any write.** Then, *outside* the transaction (DuckDB writes one
   attached database per transaction, and temp is a separate catalog):
   `CREATE OR REPLACE TEMP TABLE reach_funder (id VARCHAR, display_name VARCHAR, ror VARCHAR,
   crossref_id VARCHAR, country_code VARCHAR)` and `executemany` the funder rows when there
   are any.
5. `BEGIN`; `DELETE FROM bi.fact_package_reach WHERE _snapshot = current_date` (makes a same-day
   rerun idempotent; earlier snapshots are never touched);
   `executemany("INSERT INTO bi.fact_package_reach VALUES (?, ?, ?, ?, ?, ?, current_date)",
   rows)` when there are rows; `con.execute(_REACH_FUNDER_DIM_SQL)`; `COMMIT`. Wrap it in the
   existing `try/except: ROLLBACK; raise` pattern from `_enrich_funders`.
6. Return `len(rows)`.

In `run()`, after the `grants` block and before `citations`:

```python
if "reach" in steps:
    if source != "api":
        print("  reach: skipped (OpenAlex group_by is api-only; use --source api)")
    elif not os.getenv("OPENALEX_API_KEY"):
        print("  reach: skipped: set OPENALEX_API_KEY in the environment "
              "(~2 OpenAlex calls per linked package, past the keyless daily budget)")
    else:
        # Best-effort (spec §3), like institutions: fetches finish before any write.
        try:
            counts["fact_package_reach"] = _enrich_reach(con)
            print(f"  fact_package_reach: {counts['fact_package_reach']} rows")
        except (RuntimeError, duckdb.Error) as exc:
            print(f"  reach: skipped ({exc})")
```

`main()`'s `--steps` help: append "; 'reach' is opt-in and needs OPENALEX_API_KEY". No new
`biocintel` subcommand: run it with
`uv run python -m biocintel.pipeline.enrich_from_lake --steps works,institutions,funders,grants,reach`
(or `--steps reach` alone; `linked` is built every run).

`biocintel.sources.connect_with_sources` / `_fill_for_enrich` are **unchanged**. `reach` needs
only the bridge works it always loads.

### `src/biocintel/pipeline/extract_people.py`

In `_write`, the `dim_funder` keep clause becomes:

```python
# dim_funder also holds the funders OpenAlex lists on works (enrich_from_lake, #85) and on
# works citing a package (fact_package_reach, #92): keep those, and the registry ids already
# on a declared one. `key IS NOT NULL`: a NULL in a NOT IN list would keep every row.
keep = (
    " WHERE funder_id NOT IN (SELECT funder_id FROM bridge_work_funder"
    " UNION SELECT key FROM fact_package_reach WHERE dimension = 'funder' AND key IS NOT NULL)"
    if table == "dim_funder" else ""
)
```

The NULL warning is literal. `x NOT IN (…, NULL)` is never TRUE, so without the filter the
DELETE would match nothing and stale Authors@R funders would never be pruned. All snapshots
count, so a funder from an older snapshot is kept. Extra `dim_funder` rows are harmless.

### DDL

`src/biocintel/schema.sql`, after `fact_citation_edge`:

```sql
-- Works citing each package's confident primary papers, counted by OpenAlex group_by (#92).
-- Append-only, snapshot-stamped. Counts are distinct citing works per row; never add them
-- across packages or keys (a work has several countries and funders).
CREATE TABLE IF NOT EXISTS fact_package_reach (
    package_name  VARCHAR NOT NULL,
    repo          VARCHAR NOT NULL,
    dimension     VARCHAR NOT NULL,       -- 'total' | 'country' | 'funder'
    key           VARCHAR,                -- ISO alpha-2 | OpenAlex funder id 'F…'; NULL = unknown (and the total row)
    key_name      VARCHAR,                -- OpenAlex display name; NULL with key
    n_citing      BIGINT NOT NULL,
    _snapshot     DATE NOT NULL
);
```

**Migration:** none needed. It's a new table, and `init_schema` runs `schema.sql` (`CREATE …
IF NOT EXISTS`) on every connect. No `ALTER` list in `db.py`. A column named `key` works
unquoted in DuckDB 2.0.0 for `CREATE`, `SELECT`, `WHERE … IS NULL` and `COMMENT ON COLUMN
v.key`.

### Mart

Append to `build_marts._MART_SQL`, after `mart_funder_region`:

```sql
-- Citing-work reach per package (#92), latest snapshot. One row per package x dimension x key;
-- the total row's n_citing is the denominator. Join key to mart_region_group.country_code
-- (country rows) or mart_funder_region.funder_id (funder rows) to filter, never to sum.
CREATE OR REPLACE TABLE mart_package_reach AS
WITH r AS (
    SELECT * FROM fact_package_reach
    QUALIFY _snapshot = MAX(_snapshot) OVER ()
)
SELECT r.package_name, r.repo, r.dimension, r.key, r.key_name, r.n_citing,
       t.n_citing                         AS n_citing_total,
       r.n_citing / NULLIF(t.n_citing, 0) AS share_of_citing,
       r._snapshot
FROM r
JOIN r t ON t.package_name = r.package_name AND t.repo = r.repo AND t.dimension = 'total'
ORDER BY r.package_name, r.repo, r.dimension, r.n_citing DESC, r.key NULLS LAST;
```

The snapshot is one global `MAX`: a run writes every package or nothing, so the latest snapshot
is complete. `/` on BIGINTs gives DOUBLE in DuckDB.

- `_MARTS`: append `"mart_package_reach"`.
- `_ROW_GROUP_SIZE`: add `"mart_package_reach": 2048` (sorted by package, so DuckDB-WASM can
  range-read one package, as `mart_package_downloads_monthly` does).

`DEFINITIONS["mart_package_reach"]`, verbatim:

```python
"mart_package_reach": {
    "description": "One row per package x dimension (total, country, funder) x key: works "
                   "citing the package's confident primary papers (match_method doi or "
                   "citation_file), counted by OpenAlex at the latest snapshot. n_citing counts "
                   "distinct citing works across all of those papers (one OR'd query), so a "
                   "work citing two of them counts once. Values are not additive: not across "
                   "packages (a work citing two packages counts for each) and not across keys "
                   "(a work counts once for every author country and every funder), so adding "
                   "countries into a region over-counts. Join key to mart_region_group or "
                   "mart_funder_region to filter rows, and read each key on its own. Funder rows "
                   "are the 200 largest funders only, so they do not add up to the total even "
                   "before overlap.",
    "columns": {
        **_PKG,
        "dimension": "total (one row: all distinct citing works), country (a country of any "
                     "author on the citing work, OpenAlex authorships.countries) or funder (a "
                     "funder OpenAlex lists on the citing work; the 200 largest only).",
        "key": "ISO 3166-1 alpha-2 country code (joins mart_region_group.country_code) or "
               "OpenAlex funder id F... (joins mart_funder_region.funder_id). NULL on the total "
               "row, and on the row counting citing works with no known author country or no "
               "listed funder: NULL means unknown, not elsewhere.",
        "key_name": "Country or funder name as OpenAlex displays it; NULL when key is NULL.",
        "n_citing": "Distinct works citing any of the package's confident primary papers that "
                    "have this key (total row: all of them). Not additive across packages or "
                    "keys.",
        "n_citing_total": "The package's total: distinct citing works, the denominator of "
                          "share_of_citing.",
        "share_of_citing": "n_citing / n_citing_total, 0-1; NULL when nothing cites the "
                           "package. Shares across keys add up to more than 1.",
        "_snapshot": "Date the counts were fetched from OpenAlex.",
    },
},
```

A new mart is a mart schema change. After the new marts deploy, a human regenerates the views
file (`frontend/public/data/bioc-intelligence.duckdb`). Until then `write_views_db` warns and
skips the unpublished mart. The PR must say so.

### Docs

- `CLAUDE.md`: in the enrich step list, after `citations`, add a `reach` (**opt-in**, api-only)
  bullet: "`group_by` on works citing each package's `doi`/`citation_file` primary papers
  (one OR'd `cites:` filter, this run's live ids) → `fact_package_reach` (country, funder,
  total; snapshot-stamped) and the citing-work funders merged into `dim_funder`. ~2 calls
  per package: needs `OPENALEX_API_KEY` and is skipped without it. Funders are top-200 by
  count." Add `fact_package_reach` to the facts list and `mart_package_reach` to the marts
  list in *Data model shape*.
- `bioc-intelligence-spec.md` §5: add `fact_package_reach(package_name, repo, dimension, key,
  key_name, n_citing, _snapshot)` after `fact_citation_edge`, and
  `mart_package_reach(package_name, repo, dimension, key, key_name, n_citing, n_citing_total,
  share_of_citing, _snapshot)` after `mart_funder_region`, each with a `-- (#92)` comment. §7:
  add `openalex group_by -> fact_package_reach (opt-in)` to the `enrich_from_lake.py` line.
- `README.md`: the `OPENALEX_API_KEY` sentence covers the opt-in `citations` **and `reach`**
  steps.

### Upstream calls at runtime and the fixtures to record

- Runtime: `GET https://api.openalex.org/works?filter=cites:<W…|W…>&group_by=authorships.countries:include_unknown&per-page=200&api_key=…`,
  the same with `funders.id:include_unknown`, and then
  `GET /funders?filter=openalex_id:<F…|…>&select=id,display_name,ids,country_code&per-page=200&cursor=*`
  through the existing `fetch_by` (50 ids per call).
- **Record, keyless**, into `tests/fixtures/api/`, keeping `meta.count`, `meta.groups_count`
  and the full `group_by` list, and dropping `meta.notice`, `meta.x_query` and every other `meta`
  key:
  - `openalex_reach_countries.json` ←
    `curl 'https://api.openalex.org/works?filter=cites:W4392168904&group_by=authorships.countries:include_unknown&per-page=200'`
  - `openalex_reach_funders.json` ←
    `curl 'https://api.openalex.org/works?filter=cites:W4392168904&group_by=funders.id:include_unknown&per-page=200'`

  Test expectations come from the recorded files. On 2026-10-23 they were count 24. Countries
  were 17 groups: US 13 first, `…/countries/UNKNOWN` 2. Funders were 31 groups: `unknown` 8
  first, then F4320332161 7, F4320337354 6, F4320337348 3; F4320320300 "European Commission" 1.
  If a re-recording no longer has F4320337348 and F4320320300, pick other ids for the
  dim_funder assertions below and say so in the test docstring.
- Update the `tests/test_sources.py` module docstring to list the two new fixtures.

## Acceptance criteria

- [ ] `openalex.citing_groups(["W1", "W2"], "authorships.countries")` with `get_text`
      monkeypatched to the countries fixture sends `filter=cites:W1|W2`,
      `group_by=authorships.countries:include_unknown` and `per-page=200`. It returns
      `(24, groups)` where `groups[0] == ("US", "United States", 13)` and the unknown group is
      `(None, None, 2)`. With the funders fixture, `("F4320332161", "National Institutes of
      Health", 7)` is present, the bare-`unknown` group is `(None, None, 8)`, and no key
      contains `openalex.org`.
- [ ] `enrich_from_lake.ALL_STEPS` contains `"reach"`, and `DEFAULT_STEPS` is still
      `("works", "institutions", "funders", "grants")`.
- [ ] With `OPENALEX_API_KEY` set and the API faked from fixtures, `enrich_from_lake.run(("reach",),
      source="api")` on a store whose bridge has limma (citation_file), sesame (doi), `pair`
      (limma + sesame, both doi), `sesame2` (sesame, citation_file) and `notconf` (sesame,
      description_doi only), and whose `dim_work` has a stale `('38407446', openalex_id
      'Wstale')` row:
      - writes `fact_package_reach` rows for limma, sesame, pair and sesame2 only (not
        `notconf`). Each package has exactly one `total` row (key NULL, n_citing 24), 17
        country rows and 31 funder rows, all with `_snapshot = current_date`;
      - requests `cites:W2146512944|W4392168904` for `pair`, never anything containing `Wstale`,
        and requests `cites:W4392168904` exactly twice (sesame and sesame2 share one memoised
        pair of calls);
      - returns `counts["fact_package_reach"] == 4 * 49`.
- [ ] After that run, `dim_funder` holds F4320320300 with name "European Commission",
      `curated` FALSE and `country_code` NULL (not in the `/funders` fixture). A pre-existing
      curated row `('F4320337348', 'NHGRI (declared)', true, NULL, NULL, NULL)` keeps its name
      and `curated`, and gains `country_code 'US'` and `ror 'https://ror.org/00baak391'` from
      the `/funders` fixture.
- [ ] Running the same call again the same day leaves the row count unchanged. A pre-existing
      row with `_snapshot = '2026-09-01'` survives both runs.
- [ ] Without `OPENALEX_API_KEY`: no `group_by` request is made, `"fact_package_reach" not in
      counts`, and stdout contains `set OPENALEX_API_KEY`.
- [ ] When any `group_by` request fails (`HttpError(500)` → `RuntimeError`), the run doesn't
      raise, `"fact_package_reach" not in counts`, and the store's `fact_package_reach` and
      `dim_funder` are unchanged. Other steps in the same run still land: run
      `("works", "reach")` and see `counts["dim_work"] == 2`.
- [ ] `extract_people._write` keeps a `dim_funder` row referenced only by a `fact_package_reach`
      funder row. It still deletes a stale declared funder referenced by nothing, even when
      `fact_package_reach` also holds NULL-key rows.
- [ ] `mart_package_reach` reads only the latest snapshot and has exactly the columns
      `package_name, repo, dimension, key, key_name, n_citing, n_citing_total, share_of_citing,
      _snapshot`. `share_of_citing` is `n_citing / total`, 1.0 on the total row, and NULL for a
      package whose total is 0. The NULL-key unknown row is kept.
- [ ] `mart_package_reach` is in `_MARTS` with `ROW_GROUP_SIZE 2048`, and every column has a
      `DEFINITIONS` entry. `tests/test_views_db.py` passes unchanged: it builds every `_MARTS`
      entry and fails on an undefined column.
- [ ] No test touches the network. `uv run pytest` and `uv run ruff check src tests` pass.
- [ ] `CLAUDE.md`, `bioc-intelligence-spec.md` §5/§7 and `README.md` are updated as in *Docs*.
- [ ] The PR body says: (1) a views-file regeneration is needed after the new marts deploy;
      (2) the step is opt-in, so production produces nothing until
      `systemd/biocintel-refresh.service` runs
      `enrich_from_lake --steps works,institutions,funders,grants,reach` with
      `OPENALEX_API_KEY` in its environment, which a human provisions (the unit is not edited
      here).

## Test plan

All offline. No new test file is needed; extend the existing ones.

1. **`tests/test_sources.py`**
   - `test_openalex_citing_groups_parses_keys_and_unknown`: monkeypatch `openalex.get_text`
     to capture the URL and return each fixture in turn. Assert the query params with
     `parse_qs` and the tuples from the first acceptance criterion.
   - `api_store` fixture: in `fake_openalex`, branch **before** the `cites:` branch. If
     `"group_by" in parse_qs(q.query)`, return `openalex_reach_countries.json` when the
     group_by starts with `authorships.countries` and `openalex_reach_funders.json` otherwise.
     `calls.append(filt)` stays first, so tests can count filters. Existing tests are
     unaffected: they never request `group_by`.
   - `test_enrich_reach_from_api(api_store, monkeypatch)`: `monkeypatch.setenv(
     "OPENALEX_API_KEY", "k")`, seed the bridge, the stale `dim_work` row, the curated NHGRI
     `dim_funder` row and a `2026-09-01` fact row, then run `("reach",)` twice. Assert the third,
     fourth and fifth acceptance criteria.
   - `test_reach_skips_without_api_key(api_store, monkeypatch, capsys)`: `delenv`, run
     `("reach",)`, and assert the sixth criterion.
   - `test_reach_outage_keeps_last_snapshot(api_store, monkeypatch)`: wrap `get_text` to raise
     `http.HttpError(url, 500)` when the URL has `group_by`, run `("works", "reach")`, and
     assert the seventh criterion.
2. **`tests/test_enrich_steps.py`**: `test_imports_without_lake_client` also asserts
   `"reach" in ALL_STEPS and "reach" not in DEFAULT_STEPS`.
3. **`tests/test_extract_people.py`**: `test_rerun_keeps_reach_funders`, modelled on
   `test_rerun_keeps_openalex_funders_and_registry_ids`. It inserts `dim_funder` rows `Freach`
   and `Fstale` (both curated FALSE, unreferenced except `Freach` by `fact_package_reach
   ('p','bioc','funder','Freach','R',1,'2026-10-01')`) plus a NULL-key funder fact row. After
   `_write(con, assemble([]))`, `Freach` remains and `Fstale` is gone.
4. **`tests/test_marts.py`**: `test_package_reach_mart_latest_snapshot_and_shares`. Use
   `db.init_schema` on `:memory:` with fact rows for `limma` on `2026-09-01` (total 10, US 4) and
   `2026-10-01` (total 20, US 5, a NULL country row 2, funder F1 3), plus `zero` on
   `2026-10-01` (total 0 only). Run `_MART_SQL` and assert: only `2026-10-01` rows; limma US
   `n_citing_total 20`, `share_of_citing 0.25`; the total row has share 1.0; the NULL-key row is
   kept; `zero`'s share is NULL; the column list is exact.
5. **`tests/test_views_db.py`**: unchanged. It covers DEFINITIONS once the mart is in `_MARTS`.

Optional manual smoke (implementer, with a key, read-only: a copy of a store under `TMPDIR` via
`BIOCINTEL_DB_PATH`, never `data/`): `--steps reach`, then check DESeq2's total is ≈ 91.7k and
DE ≈ 10.1k.

## Risks

- **Not additive, and easy to misread.** Country rows can't be added into a region. 142,814
  country memberships for 91,675 DESeq2 citing works is about 1.56 countries per work. The
  DEFINITIONS text says so. A region headline needs the follow-up per-grouping filter calls.
- **Differs from `mart_package_impact.n_citing_works`.** That column counts
  `fact_citation_edge` over all links, including `description_doi`, and only after the opt-in
  `citations` step. Reach counts confident links only, from live OpenAlex. Both are right for
  what they say. The About page should name which one a headline uses.
- **Funder tail truncation.** For DESeq2 the 200th funder has 189 citing works, so every funder
  below that is absent, and absent doesn't mean zero. The definitions say so.
- **Unknown group can fall off.** With `:include_unknown`, a work set whose citing works span
  ≥ 200 known countries could push the unknown group off the page. The maximum seen is 180, so
  that is unlikely. Funder unknown is usually the largest group.
- **Live-id dependence.** Correctness rests on `linked.oa_id` being re-resolved from PMID/DOI each
  run, which `_fill_for_enrich` does today. If a DOI resolves to no work at all, the package
  gets no reach rows, which is absent and not zero. #95 tracks the drift.
- **Cost and keys.** About 2k calls, ~$0.20 and ~10 min per run (sequential). Production is
  keyless today, so nothing runs there until a key is provisioned and the unit's `--steps` is
  extended. That's a human decision; see the last acceptance criterion.
- **Store growth.** About 100–350k fact rows per monthly snapshot (≤ 1 + 181 + 201 per package).
  That's fine for DuckDB. The Parquet mart holds only the latest snapshot.
- **Data run.** No backfill. The first `--steps …,reach` run with a key fills the fact. After the
  new marts deploy, regenerate the views file.
