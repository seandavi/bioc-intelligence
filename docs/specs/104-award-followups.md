# Spec #104: follow-ups from the #90 review (award detail)

Issue: [#104](https://github.com/seandavi/bioc-intelligence/issues/104). Base:
[`docs/specs/90-award-detail.md`](90-award-detail.md), merged in `eae42cd` (#105).

*Spec stage, 2026-10-23. The OpenAlex facts below were checked that day with curl against
`api.openalex.org/awards` and `help.openalex.org/data/awards.md`. See "Verification".*

## Goal

Close the three findings in #104:

| Finding | What changes |
|---|---|
| data-r0-1 | `mart_award` keeps only awards still on `bridge_work_funder`, and its description says what an `/awards` outage leaves behind |
| data-r0-2 | `amount_usd` DEFINITIONS text and the `schema.sql` comment say which rate OpenAlex uses, that it is not inflation-adjusted, and never to compare across years |
| data-r0-3 | `is_stub` is also true for a record with no title, start date, end date, amount or DOI, whatever its provenance; the DEFINITIONS text says so |

## Non-goals

- No change to `_enrich_awards` or the outage behaviour: an `/awards` outage still keeps last
  run's `dim_award`. The mart filters the stale rows; the dimension is not pruned.
- `amount_usd_basis` is still not stored (#90 decision). The definition says the basis is not
  stored.
- No DDL change, no new column, no migration. The `schema.sql` edit is a comment only, and
  `CREATE TABLE IF NOT EXISTS` never re-applies comments to an existing store.
- No new HTTP calls and no new fixture files. Tests build their input inline.
- No frontend change: nothing under `frontend/src` reads `mart_award`.
- No views-file regeneration: `mart_award`'s columns and types are unchanged.
- No data run is needed. The new filter, `is_stub` rule and DEFINITIONS text reach the
  published marts and `definitions.json` on the next monthly refresh. (The production store
  has no `dim_award` yet: no refresh has run since #90 merged.)
- `docs/specs/90-award-detail.md` and `docs/international-impact.md` are not edited.

## Design

### Files

| File | Change |
|---|---|
| `src/biocintel/pipeline/build_marts.py` | `mart_award` SQL gets a `WHERE`; `DEFINITIONS["mart_award"]` description, `amount_usd` and `is_stub` text |
| `src/biocintel/pipeline/enrich_from_lake.py` | `_AWARD_DIM_SQL` `is_stub` expression and the comment above it |
| `src/biocintel/schema.sql` | `dim_award.amount_usd` comment |
| `CLAUDE.md` | one clause in the `funders` bullet (lines 77-78) |
| `tests/test_marts.py` | update `test_award_mart_one_row_per_award_with_funder_name`; one new test |
| `tests/test_sources.py` | one new test |

### data-r0-1: `mart_award` filter (`build_marts.py`, `_MART_SQL`, lines 326-334)

Replace the block with:

```sql
-- Award detail per award credited on a linked work (#90): one row per award; join
-- mart_work_funder on award_id for the works. NIH detail stays in RePORTER (grant_id there).
-- Filtered to the bridge: after an /awards outage dim_award is last run's (#104).
CREATE OR REPLACE TABLE mart_award AS
SELECT a.award_id, a.funder_id, f.name AS funder_name, a.funder_award_id, a.title, a.scheme,
       a.start_date, a.end_date, a.amount, a.currency, a.amount_usd, a.award_doi,
       a.provenance, a.is_stub
FROM dim_award a
LEFT JOIN dim_funder f USING (funder_id)
WHERE a.award_id IN (SELECT award_id FROM bridge_work_funder)
ORDER BY f.name, a.funder_award_id, a.award_id;
```

`IN` (not `NOT IN`) is safe with the bridge's NULL `award_id` rows: a non-match is NULL and the
row is dropped. Awards credited since the last good `/awards` fetch have a `mart_work_funder`
row with an `award_id` and no `mart_award` row (a NULL left join), which the description now
says.

`DEFINITIONS["mart_award"]["description"]`: keep the current text and append one sentence, so
the rendered string is exactly:

> One row per OpenAlex award credited by a linked publication; join mart_work_funder on
> award_id for the publications. An award here means the paper credits that grant in its
> funding acknowledgement, not that the grant's money funded the software: never sum amount or
> amount_usd, within or across funders. Most awards are stubs (is_stub): funder and award
> number only. Detail completeness varies by funder, so counts of detailed awards measure
> funder metadata quality, not funding. For NIH awards RePORTER is authoritative: follow
> mart_work_funder.grant_id to mart_grant_attribution. After an OpenAlex /awards outage the
> detail is from the previous run, and awards credited since then are missing here.

### data-r0-2: `amount_usd` wording

`DEFINITIONS["mart_award"]["columns"]["amount_usd"]`, exactly:

> amount converted to US dollars by OpenAlex at an exchange rate it picks for that award:
> usually the rate on the award's start date, else a yearly average (the basis is not
> stored). Not inflation-adjusted. For display only: never sum, or compare across countries
> or years.

`schema.sql`, the `dim_award.amount_usd` line becomes (keep the column alignment):

```sql
    amount_usd       DOUBLE,               -- OpenAlex's USD conversion, usually at the start-date rate; not inflation-adjusted
```

### data-r0-3: `is_stub` fallback (`enrich_from_lake.py`, lines 283-297)

Replace the comment and the `is_stub` expression; the rest of `_AWARD_DIM_SQL` is unchanged:

```python
# Award detail (#90) for every award on bridge_work_funder, rebuilt whole. Funder and award
# number come from the bridge (they are the award entity's own); /awards adds the detail. A
# stub is an award known only from a publication's acknowledgement: an acknowledgement
# provenance, no /awards record at all (merged or withdrawn id), or a record with no title,
# dates, amount or DOI, so a provenance OpenAlex adds later still reads as a stub (#104).
_AWARD_DIM_SQL = """
INSERT INTO bi.dim_award
SELECT b.award_id, b.funder_id, b.funder_award_id, a.title, a.funder_scheme,
       a.start_date, a.end_date, a.amount, a.currency, a.amount_usd, a.doi, a.provenance,
       a.id IS NULL OR a.provenance IS NULL
           OR a.provenance IN ('crossref_work_funders', 'europepmc_work_funders',
                               'datacite_work_funders', 'crossref_work.grants')
           OR (a.title IS NULL AND a.start_date IS NULL AND a.end_date IS NULL
               AND a.amount IS NULL AND a.doi IS NULL) AS is_stub
FROM (SELECT award_id, min(funder_id) AS funder_id, min(funder_award_id) AS funder_award_id
      FROM bi.bridge_work_funder WHERE award_id IS NOT NULL GROUP BY award_id) b
LEFT JOIN lake.openalex.awards a ON a.id = b.award_id;
"""
```

The five columns are the ones the issue names (`lake.openalex.awards` column names: `title`,
`start_date`, `end_date`, `amount`, `doi`). `funder_scheme`, `currency` and `amount_usd` are
not checked: a scheme alone is not award detail, and the other two are NULL whenever `amount`
is. The closed provenance list stays, so a known acknowledgement source with some detail is
still a stub, as before.

`DEFINITIONS["mart_award"]["columns"]["is_stub"]`, exactly:

> True when nothing is known beyond a publication's funding acknowledgement: provenance
> crossref_work_funders, europepmc_work_funders, datacite_work_funders or crossref_work.grants,
> the award is missing from OpenAlex, or the record carries no title, dates, amount or DOI.
> Stubs have funder and award number only.

The `schema.sql` `is_stub` comment ("no record beyond a publication's acknowledgement") stays
true and is unchanged.

### `CLAUDE.md`

In the `funders` bullet, change "`mart_award` is one row per award, joined to
`mart_work_funder` on `award_id`." to "`mart_award` is one row per award still on
`bridge_work_funder`, joined to `mart_work_funder` on `award_id`."

### Entry points

None change. `biocintel build-marts` (`build_marts.run()`) builds the filtered `mart_award`;
`python -m biocintel.pipeline.enrich_from_lake` (`enrich_from_lake.run()`, `funders` step)
writes the new `is_stub`.

## Acceptance criteria

- [ ] `mart_award` holds no `award_id` that is absent from `bridge_work_funder`, even when
      `dim_award` has it.
- [ ] `mart_award` columns and order are unchanged (the `DESCRIBE` list in
      `test_award_mart_one_row_per_award_with_funder_name`).
- [ ] `DEFINITIONS["mart_award"]["description"]` ends with "After an OpenAlex /awards outage
      the detail is from the previous run, and awards credited since then are missing here."
      and otherwise equals the current text.
- [ ] `DEFINITIONS["mart_award"]["columns"]["amount_usd"]` equals the text above once the
      literals are joined; it contains "start date", "Not inflation-adjusted" and "or years",
      and no longer contains "a daily exchange rate".
- [ ] The `schema.sql` `dim_award.amount_usd` comment no longer says "daily-rate" and says
      "not inflation-adjusted".
- [ ] `dim_award.is_stub` is true for an `/awards` record whose provenance is outside the
      closed list and whose title, start date, end date, amount and DOI are all NULL; a record
      with any of those set and a non-acknowledgement provenance is still `false` (G111 in
      `test_enrich_all_steps_from_api` stays `false`).
- [ ] `DEFINITIONS["mart_award"]["columns"]["is_stub"]` equals the text above and contains "or
      the record carries no title, dates, amount or DOI".
- [ ] `CLAUDE.md` funders bullet says "still on `bridge_work_funder`".
- [ ] Existing tests pass, with `test_award_mart_one_row_per_award_with_funder_name` updated as
      below; `test_awards_outage_skips_only_that_step` passes unchanged.
- [ ] `uv run pytest` and `uv run ruff check src tests` pass (set up first with
      `uv venv && uv pip install -e '.[dev]'`; the worktree has no venv yet).
- [ ] No change under `data/` or `frontend/public/data/`; no DDL change, no migration.

## Test plan

All offline. No new fixture files.

1. **Update** `tests/test_marts.py::test_award_mart_one_row_per_award_with_funder_name`: the
   mart now needs bridge rows. Before `con.execute(_MART_SQL)`, insert
   ```python
   con.execute(
       "INSERT INTO bridge_work_funder VALUES "
       "('111','F1','G1','5F31CA1-02','openalex'), ('111','F1','G2','F31CA1','openalex')"
   )
   ```
   Assertions unchanged.
2. **New** `tests/test_marts.py::test_award_mart_drops_awards_no_longer_on_the_bridge`: the
   #104 outage case at mart level. `db.connect(":memory:")`, `_fixture(con)`, one `dim_funder`
   row `('F1','NCI',true)` as in test 1, `dim_award` rows `G1` and `Gold` (both funder `F1`,
   `is_stub` true, other columns NULL via a column list), and `bridge_work_funder` rows
   `('111','F1','G1','A1','openalex')`, `('111','F1','Gnew','A2','openalex')` and a funder-only
   `('111','F1',NULL,NULL,'openalex')`. After `_MART_SQL`:
   - `SELECT award_id FROM mart_award` is `[("G1",)]` (`Gold` dropped; the NULL bridge row does
     not drop `G1`);
   - `SELECT award_id FROM mart_work_funder WHERE award_id NOT IN (SELECT award_id FROM
     mart_award)` is `[("Gnew",)]` (a newly credited award: no detail row).
3. **New** `tests/test_sources.py::test_award_record_without_detail_is_a_stub(api_store,
   monkeypatch)`, modelled on `test_awards_missing_from_openalex_are_stub_rows`:
   `_seed_bridge(con)`, close, then wrap `openalex.get_text` so `/awards` returns
   ```python
   json.dumps({"meta": {"next_cursor": None}, "results": [
       {"id": "https://openalex.org/G111", "display_name": None, "funder_scheme": "F31",
        "start_date": None, "end_date": None, "amount": None, "currency": None,
        "amount_usd": None, "doi": None, "provenance": "some_new_acknowledgement_source"},
       {"id": "https://openalex.org/G222", "display_name": None, "funder_scheme": None,
        "start_date": "2023-02-01", "end_date": None, "amount": None, "currency": None,
        "amount_usd": None, "doi": None, "provenance": "nih_exporter"},
   ]})
   ```
   Run `enrich_from_lake.run(("works", "funders"), source="api")`, reopen the store, and
   assert `SELECT award_id, provenance, is_stub FROM dim_award ORDER BY award_id` is
   `[("G111", "some_new_acknowledgement_source", True), ("G222", "nih_exporter", False)]`
   (scheme alone does not count as detail; one date does).

No DEFINITIONS-text tests: the acceptance check is a read of the literals.

## Risks

- **Newly credited awards vanish from `mart_award` during an `/awards` outage.** Accepted and
  documented: they are still in `mart_work_funder` with funder and award number, and come
  back on the next good fetch. Before this change the mart was wrong in both directions.
- **The `amount_usd` rate rule is inferred, not documented.** OpenAlex's awards docs do not
  describe `amount_usd`; the "start-date rate, else a yearly average" wording comes from the
  `amount_usd_basis` values and the ratios below. If OpenAlex changes its basis the definition
  can drift. "It picks for that award" and "the basis is not stored" keep the text honest.
- **The detail fallback can mark a sparse full record as a stub** (a funder database row with
  only a scheme or currency). That is the intended reading: with no title, dates, amount or
  DOI there is nothing beyond funder and award number.

## Verification (2026-10-23)

- `GET https://api.openalex.org/awards?filter=id:https://openalex.org/G7004411822&select=id,amount,currency,amount_usd,amount_usd_basis,start_date,end_date,provenance`:
  `amount 11000000.0 GBP`, `amount_usd 17646171.3`, `amount_usd_basis "daily_rate"`,
  `start_date 2011-04-01`. Ratio 1.604, GBP/USD on 2011-04-01.
- `GET https://api.openalex.org/awards?group_by=amount_usd_basis`: `daily_rate` 2,738,992,
  `usd_native` 2,691,008, `annual_average` 624,854 (14.7M awards have no amount, so no basis).
- `GET https://api.openalex.org/awards?filter=amount_usd_basis:daily_rate,currency:EUR&select=...&per-page=4`:
  every ratio matches EUR/USD on the award's `start_date` (2021-01-01 → 1.227, 2018-01-01 →
  1.199, 2022-01-01 → 1.133, 2012-03-01 → 1.331). The same query with `annual_average`
  returns awards with no `start_date` and ratios 1.05-1.18, a yearly average.
- `https://help.openalex.org/data/awards.md` documents `amount` ("in `currency`") and
  `currency` ("Not converted across awards"), and names `provenance` sources, but does not
  document `amount_usd` or `amount_usd_basis`.
- The production store (`data/biocintel.duckdb`, opened read-only) has no `dim_award` table:
  no refresh has run since #90, so there are no stored rows to compare.
