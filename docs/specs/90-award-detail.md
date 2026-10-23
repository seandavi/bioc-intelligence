# Spec #90: award detail from OpenAlex `/awards` (`dim_award`, `mart_award`)

Issue: [#90](https://github.com/seandavi/bioc-intelligence/issues/90). Builds on #85 / PR #87
(`bridge_work_funder.award_id`). Background: `docs/international-impact.md` §1 and
recommendation 1.

*Spec stage, 2026-10-23. Everything below about OpenAlex `/awards` was checked live that day
with keyless curl calls; see "Verification" at the end.*

## Goal

For every OpenAlex award (`G…`) that a linked work credits (`bridge_work_funder.award_id`),
store the award's detail: title, scheme, start/end dates, amount/currency/amount_usd, award DOI,
`provenance`. Flag stubs, meaning awards with no record beyond a publication's funding
acknowledgement. Publish the result as a one-row-per-award mart whose definitions say outright
that a credited award is **not** money that funded the software.

- New dimension `dim_award`, rebuilt whole each run inside the existing `funders` enrich step.
  It is best-effort on its own: an `/awards` outage keeps last run's `dim_award` and never
  fails the funders bridge or the refresh.
- New mart `mart_award` (one row per award), joined to `mart_work_funder` on `award_id`.
- RePORTER (`dim_grant`) stays authoritative for NIH awards. Nothing here changes `dim_grant`,
  `bridge_work_grant` or the NIH match in `mart_work_funder`.

## Non-goals

- **Frontend.** No change to `frontend/`, not even `MARTS`/`LAZY_MARTS` in
  `frontend/src/db/duckdb.ts`. Showing awards on the dashboard is a follow-up issue.
- **Recipients, lead investigator, `institution_awarded`, `recipient_countries`,
  `funding_type`, `landing_page_url`, `amount_usd_basis`, parent/sub-awards, topics.** The
  issue's `dim_award` column list is the contract. Recipient geography can follow later if a
  use case needs it.
- **No change to `mart_work_funder`'s columns.** Award detail lives in its own mart (see
  Design → why a separate mart).
- **No join on `funder_award_id`.** It stays display text. The existing NIH core-number regex in
  `mart_work_funder` is untouched.
- **No `--source lake` support.** cdsci-lake has no awards table that this project knows of
  (its `works_awards` is already empty). Under `lake` the award step fails its SQL and is
  skipped, which is the same best-effort path as an API outage.
- **OpenAlex id drift (#95).** Awards come only from works whose stored OpenAlex id still
  resolves. That gap belongs to #95.
- **No new CLI flag or step name.** Awards ride on the existing `funders` step, so
  `DEFAULT_STEPS`/`ALL_STEPS` stay as they are.

## Upstream: what `/awards` looks like (verified 2026-10-23)

- Endpoint `https://api.openalex.org/awards`. It supports `filter`, `select`, `per-page`
  (200 max) and `cursor`, like `/works`.
- **The `id` filter needs full URLs. Bare ids silently match nothing:**
  - `/awards?filter=id:G3618239412` → `count: 0`, `results: []` (no error)
  - `/awards?filter=id:https://openalex.org/G3618239412` → 1 result
  - `|` OR-lists of full URLs work: `filter=id:https://openalex.org/G…|https://openalex.org/G…`
  - The urlencoded form that `openalex._get` builds works too (tested:
    `filter=id%3Ahttps%3A%2F%2Fopenalex.org%2FG7498357167%7C…&select=…&per-page=200&cursor=%2A`
    → 3 of 4 results, `next_cursor: null`).
  - `openalex_id:` (which `fetch_by` uses for works/funders/institutions) is **rejected** on
    `/awards` with `"openalex_id is not a valid field"`, and so are `openalex:` and
    `ids.openalex:`.
- An unknown or merged id is simply **absent** from `results`. Results are **not** in filter
  order.
- `select` works. The fields used here and their shapes:

| field | example (full record) | example (stub) |
|---|---|---|
| `id` | `"https://openalex.org/G7498357167"` | `"https://openalex.org/G1775034342"` |
| `display_name` (= title) | `"Advancing Epigenetic Sequencing Through Solid-Phase Enzymatic Approaches"` | `null` |
| `funder_scheme` | `"F31"`, `"H2020 - RIA"` | `null` |
| `start_date` / `end_date` | `"2023-02-01"` / `"2026-01-31"` (ISO date string or `null`) | `null` |
| `amount` / `currency` / `amount_usd` | `47694.0` / `"USD"` / `47694.0`; CORDIS `2999755.0` / `"EUR"` / `3597606.17` | `null` |
| `doi` | **two forms**: bare `"10.3030/777483"` (CORDIS) and URL `"https://doi.org/10.35802/090532"` (Wellcome via `crossref_work`) | `null` |
| `provenance` | `"nih_exporter"`, `"cordis"`, `"crossref_work"`, `"gepris"`, … | `"crossref_work_funders"` |

- Provenance values that are **acknowledgement-only** (spot-checked: every sampled record had
  null title, scheme, dates, amount and DOI): `crossref_work_funders` (7.2M awards
  OpenAlex-wide), `europepmc_work_funders` (1.5M), `crossref_work.grants` (233k) and
  `datacite_work_funders` (60k). Everything else (`nih_exporter`, `cordis`, `erc`,
  `gateway_to_research`, `snsf`, `crossref_work` = Crossref grant DOIs, `datacite` = DataCite
  grant DOIs, …) is a record from a funder or grant registry. A full record can still lack a
  field: NIH U54HG003273 has dates but `amount: null`.
- `works.awards[].funder_id` and `.funder_award_id` (already in `bridge_work_funder`) are the
  award entity's own `funder.id` / `funder_award_id`. For the 3 of W4392168904's 8 awards I
  checked against `/awards` (G1485666646, G1775034342, G7498357167), both fields matched exactly.
  So `dim_award` takes the funder and award number from the bridge
  and only the detail from `/awards`.
- Volume: the issue measured 3,063 distinct awards on our linked works, so 62 calls at 50 ids
  per batch, one page each. That is well inside the keyless daily allowance (each call cost
  $0.0001 of the $0.10/day keyless budget).

## Design

### Files

| File | Change |
|---|---|
| `src/biocintel/sources/openalex.py` | `AWARD_FIELDS`, `AWARDS_DDL`, `awards()`, `award_row()`, `_date()` |
| `src/biocintel/sources/__init__.py` | add `AWARDS_DDL` to `_DDL`; fetch awards in `_fill_for_enrich`'s `funders` block |
| `src/biocintel/schema.sql` | new `dim_award` table |
| `src/biocintel/pipeline/enrich_from_lake.py` | `_AWARD_DIM_SQL`, `_enrich_awards()`, call it in `run()`; module docstring's funders bullet |
| `src/biocintel/pipeline/build_marts.py` | `mart_award` in `_MART_SQL`, `_MARTS`, `DEFINITIONS` |
| `tests/fixtures/api/openalex_awards.json` | **new**: recorded `/awards` batch (below) |
| `tests/test_sources.py` | `/awards` branch in `api_store`; new and updated tests |
| `tests/test_marts.py` | one new test |
| `CLAUDE.md` | `funders` bullet + data-model paragraph |
| `bioc-intelligence-spec.md` | §5: `dim_award` under Dimensions, `mart_award` under Derived marts |

No change to `db.py`. `dim_award` is a new table, so `CREATE TABLE IF NOT EXISTS` in
`schema.sql` (run by `init_schema` on every connect) is the whole migration for existing
stores. No `ALTER TABLE` needed.

### Why a separate `mart_award` rather than columns on `mart_work_funder`

The issue allows either. One row per award means `amount` appears once per award, not once per
crediting work. Putting it on `mart_work_funder` would repeat it on every work row and make a
careless `sum(amount)` double-count as well as mislead. It also leaves `mart_work_funder`'s
published schema alone. The frontend joins `mart_work_funder` → `mart_award` on `award_id`.

### `src/biocintel/sources/openalex.py`

Add next to the existing constants, in this style:

```python
AWARD_FIELDS = (
    "id,display_name,funder_scheme,start_date,end_date,amount,currency,amount_usd,doi,provenance"
)

AWARDS_DDL = """
CREATE TABLE lake.openalex.awards (
    id VARCHAR, title VARCHAR, funder_scheme VARCHAR, start_date DATE, end_date DATE,
    amount DOUBLE, currency VARCHAR, amount_usd DOUBLE, doi VARCHAR, provenance VARCHAR)
"""
```

Functions (after `cited_by`; `award_row` after `funder_row`):

```python
def awards(ids: Iterable[str]) -> Iterator[dict]:
    """Award records for bare ``G…`` ids. /awards has no ``openalex_id`` filter, and its
    ``id`` filter needs full URLs: bare ids silently match nothing. Missing ids are absent."""
    return fetch_by("awards", "id", (f"https://openalex.org/{g}" for g in ids), AWARD_FIELDS)


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
```

- Add `from datetime import date` to the imports.
- Update `fetch_by`'s docstring key list: ``doi`` | ``pmid`` | ``openalex_id`` | ``id``
  (``/awards``, full URLs).
- Nothing else changes. `fetch_by` already sorts and deduplicates, batches 50 values per
  request and cursor-pages. A full URL contains neither `,` nor `|`.

### `src/biocintel/sources/__init__.py`

- Add `openalex.AWARDS_DDL` to `_DDL`, after `openalex.FUNDERS_DDL`.
- In `_fill_for_enrich`, inside `if "funders" in steps:`, after the existing funders
  `try/except`, add a second, independent block:

```python
        # Award detail (#90), best-effort on its own like funders: the award step
        # skips and last run's dim_award stays.
        gids = _column(con, "SELECT DISTINCT award_id FROM lake.openalex.works_awards")
        try:
            _insert(con, "openalex.awards", [openalex.award_row(r) for r in openalex.awards(gids)])
            print(f"  openalex: {_count(con, 'openalex.awards')} of {len(gids)} awards")
        except RuntimeError as exc:
            con.execute("DROP TABLE lake.openalex.awards")
            print(f"  openalex: awards unavailable ({exc})")
```

`lake.openalex.works_awards` holds exactly the working set's awards at this point. The
`citations` block, which loads citing works and their awards, runs later in the same function.
`award_rows` already drops awards without an id, so `award_id` is never NULL here.

### `src/biocintel/schema.sql`

Insert after `bridge_work_funder`:

```sql
-- Award detail from OpenAlex /awards for every award on bridge_work_funder (#90). Rebuilt
-- whole by the funders step; best-effort. A credited award is not money that funded the software.
CREATE TABLE IF NOT EXISTS dim_award (
    award_id         VARCHAR PRIMARY KEY,  -- OpenAlex award id ('G…'), bridge_work_funder.award_id
    funder_id        VARCHAR NOT NULL,     -- dim_funder.funder_id, as bridge_work_funder lists it
    funder_award_id  VARCHAR,              -- funder's own award number; display text, never a join key
    title            VARCHAR,
    scheme           VARCHAR,              -- OpenAlex funder_scheme: 'F31', 'H2020 - RIA', ...
    start_date       DATE,
    end_date         DATE,
    amount           DOUBLE,               -- in `currency`; never summed
    currency         VARCHAR,
    amount_usd       DOUBLE,               -- OpenAlex's daily-rate conversion
    award_doi        VARCHAR,              -- bare lower-case, e.g. '10.3030/777483' (CORDIS)
    provenance       VARCHAR,              -- OpenAlex source of the record; NULL when /awards lacks it
    is_stub          BOOLEAN NOT NULL      -- no record beyond a publication's acknowledgement
);
```

### `src/biocintel/pipeline/enrich_from_lake.py`

New SQL, after `_FUNDER_DIM_SQL`:

```python
# Award detail (#90) for every award on bridge_work_funder, rebuilt whole. Funder and award
# number come from the bridge (they are the award entity's own); /awards adds the detail. A
# stub is an award known only from a publication's acknowledgement: an acknowledgement
# provenance, or no /awards record at all (merged or withdrawn id).
_AWARD_DIM_SQL = """
INSERT INTO bi.dim_award
SELECT b.award_id, b.funder_id, b.funder_award_id, a.title, a.funder_scheme,
       a.start_date, a.end_date, a.amount, a.currency, a.amount_usd, a.doi, a.provenance,
       a.id IS NULL OR a.provenance IS NULL
           OR a.provenance IN ('crossref_work_funders', 'europepmc_work_funders',
                               'datacite_work_funders', 'crossref_work.grants') AS is_stub
FROM (SELECT award_id, min(funder_id) AS funder_id, min(funder_award_id) AS funder_award_id
      FROM bi.bridge_work_funder WHERE award_id IS NOT NULL GROUP BY award_id) b
LEFT JOIN lake.openalex.awards a ON a.id = b.award_id;
"""
```

New function, after `_enrich_funders`, in the same transaction pattern:

```python
def _enrich_awards(con: duckdb.DuckDBPyConnection) -> int:
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM bi.dim_award")
        con.execute(_AWARD_DIM_SQL)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    n, n_stub = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE is_stub) FROM bi.dim_award").fetchone()
    print(f"  dim_award: {n} ({n_stub} stubs)")
    return n
```

In `run()`, inside `if "funders" in steps:` and after the existing funders `try/except`, add an
independent block. It runs even when the funders bridge was skipped, so awards then come from
last run's bridge, which is consistent:

```python
            # Best-effort on its own: no lake.openalex.awards (API outage, or --source lake)
            # keeps last run's dim_award.
            try:
                counts["dim_award"] = _enrich_awards(con)
            except duckdb.Error as exc:
                print(f"  awards: skipped ({exc})")
```

Module docstring, `funders` bullet: append "…, plus award detail from `openalex.awards`
(`/awards`) → `dim_award` (#90), best-effort on its own."

Entry points do not change: `python -m biocintel.pipeline.enrich_from_lake` (default steps
include `funders`) and `run(steps, source)`. The systemd refresh needs no change.

### `src/biocintel/pipeline/build_marts.py`

`_MART_SQL`: insert after `mart_work_funder`:

```sql
-- Award detail per award credited on a linked work (#90): one row per award; join
-- mart_work_funder on award_id for the works. NIH detail stays in RePORTER (grant_id there).
CREATE OR REPLACE TABLE mart_award AS
SELECT a.award_id, a.funder_id, f.name AS funder_name, a.funder_award_id, a.title, a.scheme,
       a.start_date, a.end_date, a.amount, a.currency, a.amount_usd, a.award_doi,
       a.provenance, a.is_stub
FROM dim_award a
LEFT JOIN dim_funder f USING (funder_id)
ORDER BY f.name, a.funder_award_id, a.award_id;
```

`_MARTS`: add `"mart_award"` right after `"mart_work_funder"`.

`DEFINITIONS`: add after `"mart_work_funder"` (verbatim):

```python
    "mart_award": {
        "description": "One row per OpenAlex award credited by a linked publication; join "
                       "mart_work_funder on award_id for the publications. An award here means "
                       "the paper credits that grant in its funding acknowledgement, not that "
                       "the grant's money funded the software: never sum amount or amount_usd, "
                       "within or across funders. Most awards are stubs (is_stub): funder and "
                       "award number only. Detail completeness varies by funder, so counts of "
                       "detailed awards measure funder metadata quality, not funding. For NIH "
                       "awards RePORTER is authoritative: follow mart_work_funder.grant_id to "
                       "mart_grant_attribution.",
        "columns": {
            "award_id": "OpenAlex award id (G...); joins mart_work_funder.award_id.",
            "funder_id": "OpenAlex funder id (F...); joins mart_work_funder and "
                         "mart_funder_region.",
            "funder_name": "Funder name.",
            "funder_award_id": "The funder's own award number as OpenAlex records it. Display "
                               "text, not a join key: it can hold several numbers or a "
                               "programme name ('251217 and 255847', 'HORIZON2020').",
            "title": "Award title from the funder's record; empty for stubs.",
            "scheme": "Funding scheme as the funder names it (OpenAlex funder_scheme), e.g. "
                      "'F31' or 'H2020 - RIA'. Not harmonized across funders.",
            "start_date": "Award start date, when the funder's record has one.",
            "end_date": "Award end date, when the funder's record has one.",
            "amount": "Award amount in currency as the source records it; its scope (whole "
                      "award, one year, one share) varies by source. What the grant was "
                      "worth, not what funded the software: never sum.",
            "currency": "ISO 4217 currency code of amount.",
            "amount_usd": "amount converted to US dollars by OpenAlex at a daily exchange "
                          "rate. For display only: never sum or compare across countries.",
            "award_doi": "Award DOI, bare and lower-case (e.g. 10.3030/777483 for CORDIS), "
                         "when the funder registers one.",
            "provenance": "OpenAlex source of the award record: a funder or grant database "
                          "(nih_exporter, cordis, gateway_to_research, ...) or a publication's "
                          "acknowledgement (crossref_work_funders, europepmc_work_funders, "
                          "...). Empty when OpenAlex no longer returns the award.",
            "is_stub": "True when nothing is known beyond a publication's funding "
                       "acknowledgement: provenance crossref_work_funders, "
                       "europepmc_work_funders, datacite_work_funders or crossref_work.grants, "
                       "or the award is missing from OpenAlex. Stubs have funder and award "
                       "number only.",
        },
    },
```

The existing build check (`a mart column without one fails the build`) covers completeness.

### Fixture: `tests/fixtures/api/openalex_awards.json`

Record once with:

```
curl -s 'https://api.openalex.org/awards?filter=id:https://openalex.org/G7498357167|https://openalex.org/G1775034342|https://openalex.org/G7004411822&select=id,display_name,funder_scheme,start_date,end_date,amount,currency,amount_usd,doi,provenance&per-page=200'
```

Keep only `meta.next_cursor` (null) and `results`, as the other fixtures do. Then **relabel two
ids** so they join the existing `openalex_works.json` awards on W4392168904 (`G111`, `G222`,
both NHGRI). Leave every other field as recorded:

| recorded id | relabel to | what it is |
|---|---|---|
| `G7498357167` | `https://openalex.org/G111` | full `nih_exporter` record: title, scheme `F31`, 2023-02-01 → 2026-01-31, 47694.0 USD, no DOI |
| `G1775034342` | `https://openalex.org/G222` | stub, `crossref_work_funders`, all detail null |
| `G7004411822` | unchanged | Wellcome via `crossref_work`: URL-form DOI `https://doi.org/10.35802/090532`, 11000000.0 GBP, dates. Not on any fixture work, so it must **not** reach `dim_award` |

Add a line to `tests/test_sources.py`'s module docstring: `openalex_awards.json` recorded
2026-10-23, two ids relabelled to the works fixture's `G111`/`G222`.

## Acceptance criteria

- [ ] `openalex.awards(["G1", "G2"])` requests `filter=id:https://openalex.org/G1|https://openalex.org/G2`
      (full URLs) with `select=AWARD_FIELDS`.
- [ ] `openalex.award_row` on the Wellcome fixture record returns
      `("G7004411822", "Understanding the genetic basis …", "Cellular and Molecular Neuroscience",
      date(2011, 4, 1), date(2016, 11, 30), 11000000.0, "GBP", 17646171.3, "10.35802/090532",
      "crossref_work")`. On the stub (`G222`) it returns `("G222", None, None, None, None, None,
      None, None, None, "crossref_work_funders")`. `_date("2023")` and `_date(None)` return `None`.
- [ ] `enrich_from_lake.run(ALL_STEPS, source="api")` over `api_store` returns counts that
      include `"dim_award": 2`. `dim_award` holds exactly `G111` (is_stub false, provenance
      `nih_exporter`, scheme `F31`, amount 47694.0, start_date 2023-02-01, funder_id
      `F4320337348`, funder_award_id `5F31HG012892-02`) and `G222` (is_stub true, provenance
      `crossref_work_funders`, title NULL). There is no row for `G7004411822`.
- [ ] The `/awards` request in that run uses the filter
      `id:https://openalex.org/G111|https://openalex.org/G222`.
- [ ] An award that `/awards` does not return still gets a `dim_award` row: provenance NULL,
      is_stub true, funder_id/funder_award_id from the bridge.
- [ ] An `/awards` HTTP 500 under `--source api` skips only the award step. `bridge_work_funder`
      is still rebuilt, `"dim_award"` is absent from the counts, and a pre-existing `dim_award`
      row survives.
- [ ] `build_marts` exports `mart_award` with exactly the 14 columns above, in that order. Every
      column has a `DEFINITIONS` entry, and the description contains "never sum".
- [ ] `init_schema` on a store created before this change adds `dim_award`. It is a new table,
      so `CREATE TABLE IF NOT EXISTS` covers it.
- [ ] `mart_work_funder`'s columns are unchanged.
- [ ] `uv run pytest` and `uv run ruff check src tests` pass. No network in tests.
- [ ] `CLAUDE.md` and `bioc-intelligence-spec.md` §5 mention `dim_award` / `mart_award`.

## Test plan

All tests are offline and fixture-based.

`tests/test_sources.py`:

1. `api_store.fake_openalex`: add `if q.path == "/awards": return (FIXTURES /
   "openalex_awards.json").read_text()` next to the `/funders` branch. Without it, `/awards`
   falls through to the works fixture.
2. `test_openalex_award_row_normalizes_doi_and_dates`: the `award_row` and `_date` assertions
   above, on `_fixture("openalex_awards.json")`.
3. `test_openalex_awards_filter_needs_full_urls(monkeypatch)`: monkeypatch `openalex._get` (as
   `test_openalex_fetch_by_batches_pages_and_skips_separators` does), call
   `list(openalex.awards(["G2", "G1"]))` and assert entity `"awards"`, filter
   `"id:https://openalex.org/G1|https://openalex.org/G2"`, `select == openalex.AWARD_FIELDS`.
4. `test_enrich_all_steps_from_api`: add `"dim_award": 2` to the expected counts, assert
   `"id:https://openalex.org/G111|https://openalex.org/G222" in calls`, and assert the
   `dim_award` rows for `G111`/`G222` (and that `G7004411822` is absent).
5. `test_awards_missing_from_openalex_are_stub_rows(api_store, monkeypatch)`: wrap
   `openalex.get_text` so that `/awards` returns `{"meta": {"next_cursor": null}, "results": []}`.
   Run `("works", "funders")` and assert both awards have `provenance IS NULL`, `is_stub`, and
   the bridge's funder/award number.
6. `test_awards_outage_skips_only_that_step(api_store, monkeypatch)`: modelled on
   `test_funders_outage_skips_only_that_step`. Seed `INSERT INTO dim_award (award_id, funder_id,
   is_stub) VALUES ('Gold', 'F1', true)`, make `/awards` raise `http.HttpError(url, 500)`, run
   `("works", "funders")`, assert `"bridge_work_funder" in counts`, `"dim_award" not in counts`,
   and that `Gold` is still in `dim_award`.

`tests/test_marts.py`:

7. `test_award_mart_one_row_per_award_with_funder_name`: on `_fixture(con)`, insert a
   `dim_funder` row and two `dim_award` rows (one stub, one full), run `_MART_SQL`, and assert
   `DESCRIBE mart_award` column order and the rows (`funder_name` joined, stub detail NULL).

The existing `tests/test_views_db.py` (every `_MARTS` entry has a view and a datapackage
resource) and `tests/test_export_api.py` (copies every `_MARTS` entry) pick up `mart_award`
without edits. Run them to confirm.

## Rollout (for the PR description)

- Data run needed: the next `enrich_from_lake` (default steps include `funders`) followed by
  `build-marts`. The monthly refresh does both. Do not run them from the branch.
- New mart, so the published views file (`frontend/public/data/bioc-intelligence.duckdb`) needs
  regenerating after the new marts deploy to gain the `mart_award` view. `sync-marts.sh` in the
  refresh does this. Existing views are unaffected because no published mart's schema changes.
- About 62 extra OpenAlex calls per refresh, which fits the keyless allowance.

## Risks

- **Stub list is a closed list of provenance strings.** If OpenAlex adds another
  acknowledgement-only provenance, those awards show `is_stub = false` with all-null detail. The
  definition names the list, so the behaviour is auditable. Re-check with
  `/awards?group_by=provenance` if stub counts look low.
- **`funder_award_id` messiness.** It is shown as recorded. The NIH core-number match lives
  only in `mart_work_funder` and is unchanged.
- **Amounts mislead if summed.** This is mitigated only by the definitions and the
  one-row-per-award shape. Nothing prevents a consumer from summing.
- **`--source lake` never fills `dim_award`.** Its SQL fails on the missing
  `lake.openalex.awards`, the step is skipped and last run's rows stay. If cdsci-lake ever adds
  an `openalex.awards` table with these column names, the SQL would start reading it unchanged.
  With different names it would keep skipping.
- **Stale ids (#95).** Works whose stored OpenAlex id 404s contribute no awards. That is the
  same gap as funders today.
- **Fixture relabelling.** `G111`/`G222` carry real detail recorded under other ids
  (`G7498357167`, `G1775034342`). The docstring says so. It is the same practice as the existing
  trimmed fixtures, whose `G111`/`G222` ids are already synthetic.

## Verification (2026-10-23, keyless)

- `GET /awards?per-page=2` showed the full field list: `id`, `display_name`, `funder_award_id`,
  `funder{id,display_name,doi}`, `funder_scheme`, `start_date`, `end_date`, `amount`,
  `currency`, `amount_usd`, `amount_usd_basis`, `doi`, `provenance`, `lead_investigator`,
  `recipient_countries`, `institution_awarded`, `funding_type`, `landing_page_url`, …
- `filter=id:G3618239412` → 0. `filter=id:https://openalex.org/G3618239412` → 1.
  `openalex_id:` / `openalex:` / `ids.openalex:` → "not a valid field".
- A batch of 4 full URLs, one of them nonexistent (`G9999999999`), urlencoded as
  `openalex._get` builds it → 3 results, unordered, `next_cursor: null`.
- `/works/W4392168904?select=id,awards,funders`: 8 awards. For the 3 looked up on `/awards`,
  `funder_id`/`funder_award_id` matched the award records.
- `/awards?group_by=provenance`: `crossref_work_funders` 7,214,948, `nih_exporter` 2,185,073,
  `europepmc_work_funders` 1,540,466, …, `crossref_work.grants` 233,290, `cordis` 62,743,
  `datacite_work_funders` 59,686. Three samples each of `crossref_work.grants`,
  `datacite_work_funders` and `europepmc_work_funders` had all detail null. `crossref_work`
  (Wellcome grant DOIs) and `datacite` (NOAA grant DOIs) samples had title, dates and amounts.
- A read-only copy of the production store (`data/biocintel.duckdb`, main checkout) has no
  `bridge_work_funder` table yet (#85 merged, not yet run), and `frontend/public/data/` has no
  `mart_work_funder.parquet`. The 3,063-award figure is from `docs/international-impact.md`,
  not re-measured here.
- `date.fromisoformat` (Python 3.11+): `"2023-02-01"` parses; `"2023"` and `"2023-02"` raise
  `ValueError`, so `_date` maps them to None.
