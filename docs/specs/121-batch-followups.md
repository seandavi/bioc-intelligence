# Spec #121: batch review follow-ups (#111, #113, #115, #117)

Issue: [#121](https://github.com/seandavi/bioc-intelligence/issues/121). It closes the unchecked
items of [#111](https://github.com/seandavi/bioc-intelligence/issues/111) (#98 review),
[#113](https://github.com/seandavi/bioc-intelligence/issues/113) (#104 review),
[#115](https://github.com/seandavi/bioc-intelligence/issues/115) (#106 review) and
[#117](https://github.com/seandavi/bioc-intelligence/issues/117) (#109 review) in one PR.

*Spec stage, 2026-10-30. The OpenAlex fact the new test relies on was checked that day with curl,
and the new tests were run as a scratch probe against the current code. See "Verification".*

## Goal

Close nine findings. One is a code change (#117 data-r0-2). The rest change text, tests or
comments.

| Finding | What changes |
|---|---|
| #111 code-r0-1 | new boundary test in `tests/test_rsec.py`: a shrink to exactly half still updates |
| #111 code-r0-2 | `schema.sql` comment on `in_elixir_rsec` (comment only); note in #98 spec non-goal |
| #111 data-r0-1 | #98 spec Risks: the recovery path for a tripped floor is corrected |
| #111 data-r0-2 | `mart_package_directory.biotools_id` definition: matched in any repo, set independently of `in_elixir_rsec` |
| #113 code-r0-1 | `CLAUDE.md` funders bullet re-wrapped (lines 77-78) |
| #113 data-r0-1 | `mart_award.is_stub` definition and the `_AWARD_DIM_SQL` comment: the NULL-provenance case, softer last sentence |
| #115 data-r0-1 | `mart_package_reach.n_works` definition: distinct OpenAlex works, so merged ids count once |
| #117 code-r0-1 | `docs/specs/102-alias-precedence.md`: "superseded by #109" pointer under three stale quotes |
| #117 data-r0-2 | `_REACH_WORKS_SQL` gains an alias branch in its `linked` join; fixture test of a `citation_file` row keyed only by an alias DOI |

#117 data-r0-1 and frontend-r0-1 are already checked (done in #118) and are skipped.

## Non-goals

- No DDL change and no migration. The `schema.sql` edit is to a `--` comment only, so
  `db.init_schema` and every existing store are unaffected.
- No new mart column, no mart schema change, so the views file does not need regenerating early.
- No change to `rsec.py` (the `<` floor stays as it is; the new test pins it).
- No change to the `is_stub` SQL expression. Only its definition text and code comment change.
- No edit to `DEFINITIONS["mart_award"]["description"]` ("Most awards are stubs (is_stub): funder
  and award number only."). #113 names only the `is_stub` column text; "most" keeps that sentence
  true enough. If the reviewer wants it aligned, that is a one-line follow-up.
- No change to `_LINKED_SQL`, `link_works`, or the `works_alt_dois` guard in
  `sources/__init__.py`. The double link noted in #117 data-r0-1 (iCite-fallback preprint plus
  alias) needs its own issue.
- No new HTTP calls and no new fixture files. The new reach test reuses
  `tests/fixtures/api/openalex_works_merged.json`, `openalex_reach_countries.json` and
  `openalex_reach_funders.json`.
- No frontend change. No data run.

## Design

### Files

| File | Change |
|---|---|
| `src/biocintel/pipeline/enrich_from_lake.py` | `_REACH_WORKS_SQL` join + its comment (#117 data-r0-2); `_AWARD_DIM_SQL` comment (#113 data-r0-1) |
| `src/biocintel/pipeline/build_marts.py` | `DEFINITIONS` text: `mart_package_directory.biotools_id`, `mart_award.is_stub`, `mart_package_reach.n_works` |
| `src/biocintel/schema.sql` | line 40 comment |
| `CLAUDE.md` | lines 77-78 re-wrap |
| `docs/specs/98-rsec-followups.md` | Non-goals line 28-29 note; Risks first bullet |
| `docs/specs/102-alias-precedence.md` | three pointer lines |
| `tests/test_rsec.py` | `test_refresh_updates_on_exact_half_shrink` |
| `tests/test_sources.py` | `test_reach_counts_citation_file_row_keyed_by_alias_doi` |
| `tests/test_marts.py` | `test_definitions_explain_stub_reach_and_biotools` |

Keep every edited Python line at 100 characters or fewer (ruff) and keep the existing
literal-concatenation style for `DEFINITIONS` strings.

### #117 data-r0-2: `_REACH_WORKS_SQL` alias branch

`enrich_from_lake.py` lines 255-266 become exactly:

```python
# Each package's confident primary works with a live OpenAlex id: this run's `linked`, never
# a stored dim_work.openalex_id, which can be stale, and a stale id's `cites:` filter
# returns 0, not an error (#95). Same set as the package_pubs_confident view. A bridge row
# keyed by a DOI OpenAlex merged into the work (a citation_file preprint DOI) matches
# through works_alt_dois, as in _LINKED_SQL (#117).
_REACH_WORKS_SQL = """
SELECT b.package_name, b.repo, list_sort(list(DISTINCT l.oa_id)) AS oa_ids
FROM bi.bridge_package_pub b
JOIN linked l ON b.work_id = CAST(l.pmid AS VARCHAR) OR b.work_id = l.doi
  OR b.work_id IN (SELECT a.doi FROM works_alt_dois a WHERE a.work_id = l.oa_id)
WHERE b.role = 'primary' AND b.match_method IN ('doi', 'doi_alias', 'citation_file')
  AND l.oa_id IS NOT NULL
GROUP BY b.package_name, b.repo
ORDER BY b.package_name, b.repo;
"""
```

Only the comment's last two lines and the `OR b.work_id IN (...)` line are new. The subquery form
is the one the issue gives and the one `_REKEY_EDGES_SQL` already uses; it adds no duplicate rows,
and `list(DISTINCT l.oa_id)` would absorb them anyway. `works_alt_dois` exists (empty) under
`--source lake` too (`lake.WORKS_ALT_DOIS_DDL`), though reach is skipped there.

Effect on counts: a package whose only confident bridge row is a `citation_file` row keyed by a
merged preprint DOI now gets reach rows (before: none). A package that also has the journal
PMID/DOI row keeps the same `oa_ids`, so `n_works` and the counts are unchanged. `n_works` can only
go up for a package, never down.

The module docstring (lines 27-32) and CLAUDE.md `reach` bullet (lines 84-88) already say reach
counts `doi`/`doi_alias`/`citation_file` papers. After this change that is true; no edit.

### #113 data-r0-1: `is_stub`

**`build_marts.py`, `DEFINITIONS["mart_award"]["columns"]["is_stub"]`.** Once the literals are
joined, the full string is exactly:

> True when nothing is known beyond a publication's funding acknowledgement: provenance
> crossref_work_funders, europepmc_work_funders, datacite_work_funders or crossref_work.grants,
> the award is missing from OpenAlex or its record has no provenance, or the record carries no
> title, dates, amount or DOI. Treat stubs as funder and award number only; any detail on them is
> unverified.

**`enrich_from_lake.py`, the comment above `_AWARD_DIM_SQL` (lines 284-288).** It becomes exactly:

```python
# Award detail (#90) for every award on bridge_work_funder, rebuilt whole. Funder and award
# number come from the bridge (they are the award entity's own); /awards adds the detail. A
# stub is an award known only from a publication's acknowledgement: an acknowledgement
# provenance, no /awards record at all (merged or withdrawn id) or one with no provenance, or
# a record with no title, dates, amount or DOI, so a provenance OpenAlex adds later still
# reads as a stub (#104).
```

### #115 data-r0-1: `n_works`

**`DEFINITIONS["mart_package_reach"]["columns"]["n_works"]`.** Append one sentence before the
"NULL on snapshots…" sentence. Once joined, the full string is exactly:

> Confident primary papers OpenAlex resolves to a live work at this snapshot: the papers every
> count on the package's rows covers (the same value on each of its rows). A confident paper
> OpenAlex does not resolve is not counted, so a change in n_works between snapshots moves the
> counts for reasons other than new citing works. Counted as distinct OpenAlex works, so two
> confident ids that OpenAlex merges into one work count once. NULL on snapshots fetched before
> n_works was recorded.

### #111 data-r0-2: `biotools_id`

**`DEFINITIONS["mart_package_directory"]["columns"]["biotools_id"]`.** Insert one sentence after
"…prefix wins.". Once joined, the full string is exactly:

> bio.tools identifier: the RSEc data/<id>/ folder holding both this package's Bioconductor
> record and a bio.tools record. When bio.tools has two entries, the curated id without the
> bioconductor- prefix wins. Matched by package name in any repo, and set independently of
> in_elixir_rsec (it can be non-NULL when in_elixir_rsec is FALSE). NULL when there is none, or
> when the package has not yet been checked against the listing (new package, or the fetch was
> skipped). Values carry over from the last successful fetch.

### #111 code-r0-2: `schema.sql` comment

Line 40 becomes exactly (column padding unchanged):

```sql
    in_elixir_rsec      BOOLEAN,          -- in ELIXIR RSEc imports/bioconductor (#93); NULL = not yet checked (new package or skipped fetch)
```

**`docs/specs/98-rsec-followups.md`, Non-goals, the bullet at lines 28-29** ("No change to
`parse_rsec_paths`, … No DDL change and no new mart column."): append the sentence
"A comment-only edit to `schema.sql` (the `in_elixir_rsec` NULL wording, #121) is allowed." to
the end of that bullet, re-wrapped to the bullet's width.

### #111 data-r0-1: #98 Risks

In `docs/specs/98-rsec-followups.md`, replace the first Risks bullet (lines 189-192) with exactly:

```markdown
- **The floor can hold back a real large removal.** If RSEc genuinely drops more than half of
  the Bioconductor imports, the store keeps last month's values and each refresh prints the skip
  line until someone looks. That is the intended trade: stale-but-correct over silently wrong.
  Re-running `extract-packages` does not clear it: `refresh_dim_package` returns before
  `update_dim_package`, so the stored counts stay at last month's values and the next run skips
  again against the same smaller listing. The code has no override. Clearing a real large
  removal needs a code change (or a follow-up issue adding an override), or a human resetting
  `in_elixir_rsec`/`biotools_id` to NULL in the production store (agents may not; see
  `AGENTS.md`). Until then the published mart serves the carried-over values with no fetch
  date. (Corrected by #121.)
```

### #113 code-r0-1: CLAUDE.md re-wrap

`CLAUDE.md` lines 77-78 (from "  last run's `dim_award`." to "never sum `amount`.") become exactly
these three lines; the words do not change:

```markdown
  last run's `dim_award`. `mart_award` is one row per award still on `bridge_work_funder`,
  joined to `mart_work_funder` on `award_id`. A credited award is not money that funded the
  software: never sum `amount`.
```

### #117 code-r0-1: pointers in the #102 spec

In `docs/specs/102-alias-precedence.md`, add one indented line directly under each of three
bullets, as a continuation of the bullet (two-space indent, matching the bullet's wrapped lines):

| Under the bullet at | Added line |
|---|---|
| line 125-126 (`alias_dois` text, "A DOI OpenAlex also holds as a separate work is never listed.") | `  (Superseded by #109: see `build_marts.DEFINITIONS["mart_work"]`.)` |
| line 130-131 (`match_method` text, "is a preprint OpenAlex merged into this work; doi shows the journal version") | `  (Superseded by #109: see `build_marts.DEFINITIONS["mart_package_work"]`.)` |
| lines 166-168 (CLAUDE.md #95 paragraph, "is still some work's own DOI is never an alias (#102).") | `    (Superseded by #109: see CLAUDE.md.)` (four spaces: it is a nested bullet) |

The quoted text itself stays: #102 remains the record of what it specified.

### #111 code-r0-1: boundary test

New test in `tests/test_rsec.py`, after `test_refresh_updates_on_modest_shrink`:

```python
def test_refresh_updates_on_exact_half_shrink(monkeypatch):
    con = _primed(monkeypatch)
    con.execute("UPDATE dim_package SET in_elixir_rsec = TRUE, biotools_id = 'x' "
                "WHERE package_name = 'gone'")  # store holds 4 listed / 4 ids
    keep = {f"imports/bioconductor/{n}.bioconductor.json" for n in ("limma", "ace")}
    monkeypatch.setattr(
        rsec, "fetch_rsec_paths",
        lambda: [p for p in _paths() if not p.startswith("imports/bioconductor/") or p in keep],
    )
    assert rsec.refresh_dim_package(con) == 2  # 2 listed is exactly half of 4: `<` updates
```

With `<` changed to `<=` this returns `None`, so the test catches the regression.

### #117 data-r0-2: reach fixture test

New test in `tests/test_sources.py`, after `test_reach_outage_keeps_last_snapshot`. It uses the
`api_store` fixture, but swaps `openalex.get_text` for a fake that serves HiLDA's merged journal
work (`openalex_works_merged.json`: `W2970457274`, PMID 31523512, journal DOI
10.7717/peerj.7557, preprint 10.1101/577452 in `locations`) and the recorded `group_by` fixtures:

```python
def test_reach_counts_citation_file_row_keyed_by_alias_doi(api_store, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "k")
    con, calls = api_store
    con.execute(
        "INSERT INTO bridge_package_pub (package_name, repo, work_id, role, match_method, "
        "confidence) VALUES "
        "('HiLDA', 'bioc', '10.1101/577452', 'primary', 'citation_file', 0.9),"
        "('both', 'bioc', '10.1101/577452', 'primary', 'citation_file', 0.9),"
        "('both', 'bioc', '31523512', 'primary', 'doi_alias', 1.0)"
    )
    con.close()
    merged = (FIXTURES / "openalex_works_merged.json").read_text()

    def fake_openalex(url, **_kw):
        query = parse_qs(urlparse(url).query)
        filt = query["filter"][0]
        calls.append(filt)
        if group_by := query.get("group_by"):
            name = "countries" if group_by[0].startswith("authorships.countries") else "funders"
            return (FIXTURES / f"openalex_reach_{name}.json").read_text()
        if "10.1101/577452" in filt or "31523512" in filt:
            return merged
        return json.dumps({"meta": {"next_cursor": None}, "results": []})

    monkeypatch.setattr(openalex, "get_text", fake_openalex)
    counts = enrich_from_lake.run(("reach",), source="api")
    assert counts["fact_package_reach"] == 2 * 49
    assert calls.count("cites:W2970457274") == 2  # both packages share one pair of calls
    con = lake.db.connect(lake.DB_PATH)
    # the alias row alone reaches the journal work; alias + journal PMID is one work (#115)
    assert con.execute(
        "SELECT package_name, count(*), min(n_works), max(n_works) FROM fact_package_reach "
        "GROUP BY 1 ORDER BY 1"
    ).fetchall() == [("HiLDA", 49, 1, 1), ("both", 49, 1, 1)]
```

`HiLDA` has only the alias-keyed `citation_file` row (the #117 case). `both` adds the `doi_alias`
row `link_works` writes, keyed by the journal PMID, so it also shows the #115 merge case:
two confident bridge rows, one OpenAlex work, `n_works = 1`. Before the fix the run writes 49 rows
(only `both`), so the first assert fails.

Update the module docstring of `tests/test_sources.py` only if a new fixture were added; none is.

### Definitions test

New test in `tests/test_marts.py`, after `test_definitions_explain_alias_dois_and_doi_alias`:

```python
def test_definitions_explain_stub_reach_and_biotools():
    award = DEFINITIONS["mart_award"]["columns"]
    reach = DEFINITIONS["mart_package_reach"]["columns"]
    directory = DEFINITIONS["mart_package_directory"]["columns"]
    assert "its record has no provenance" in award["is_stub"]
    assert "any detail on them is unverified" in award["is_stub"]
    assert "Stubs have funder and award number only" not in award["is_stub"]
    assert "Counted as distinct OpenAlex works" in reach["n_works"]
    assert "set independently of in_elixir_rsec" in directory["biotools_id"]
```

### Entry points

None change. `biocintel build-marts` (`build_marts.run()`) and `write_views_db` pick up the new
`DEFINITIONS` text. `enrich_from_lake.run(("reach",), source="api")` (and `python -m
biocintel.pipeline.enrich_from_lake --steps reach`) picks up the new join.

## Acceptance criteria

- [ ] `_REACH_WORKS_SQL` and its comment equal the block above.
- [ ] The `_AWARD_DIM_SQL` comment equals the block above; the `_AWARD_DIM_SQL` string itself is
      unchanged.
- [ ] `DEFINITIONS["mart_award"]["columns"]["is_stub"]`, `["mart_package_reach"]["columns"]
      ["n_works"]` and `["mart_package_directory"]["columns"]["biotools_id"]` equal the texts
      above once their literals are joined.
- [ ] `schema.sql` line 40 equals the line above; `git diff origin/main -- src/biocintel/schema.sql`
      changes only that comment.
- [ ] `CLAUDE.md` lines 77-78 are replaced by the three lines above and no other `CLAUDE.md` line
      changes.
- [ ] The #98 spec's first Risks bullet equals the block above and its schema non-goal bullet
      ends with the comment-only sentence. It no longer says "Clearing it means running
      `extract-packages`".
- [ ] The #102 spec has the three "(Superseded by #109: …)" lines and its quoted text is
      unchanged.
- [ ] `test_refresh_updates_on_exact_half_shrink`, `test_reach_counts_citation_file_row_keyed_by_alias_doi`
      and `test_definitions_explain_stub_reach_and_biotools` exist and pass. The reach test fails
      on `origin/main`'s `_REACH_WORKS_SQL`.
- [ ] `uv sync`, then `uv run pytest` and `uv run ruff check src tests` pass.
- [ ] No change under `data/` or `frontend/public/data/`, no new fixture files. `git diff
      origin/main --stat` lists only the nine files in the Files table plus this spec.
- [ ] The PR body says "Closes #111, closes #113, closes #115, closes #117, closes #121".

## Test plan

All offline (`uv run pytest`).

1. `tests/test_rsec.py::test_refresh_updates_on_exact_half_shrink`: pins the strict `<` floor at
   the integer boundary 2 of 4.
2. `tests/test_sources.py::test_reach_counts_citation_file_row_keyed_by_alias_doi`: an
   alias-keyed `citation_file` row now gets reach rows; alias + PMID on one work gives
   `n_works = 1`. The existing `test_enrich_reach_from_api`, `test_reach_skips_without_api_key`
   and `test_reach_outage_keeps_last_snapshot` must still pass unchanged (they have no
   `works_alt_dois` rows, so the new branch never matches).
3. `tests/test_marts.py::test_definitions_explain_stub_reach_and_biotools`: the three new texts.
   `tests/test_views_db.py::test_views_db_over_fixture_marts` runs over the new strings unchanged;
   the new text adds no quote characters beyond the apostrophes `_q` already escapes.
4. `uv run ruff check src tests`.

## Risks

- **Reach counts rise for some packages on the next reach run.** Packages whose only confident
  paper is a merged preprint cited from CITATION start getting rows, and `n_works` changes for
  none of the others. This is the fix, but a snapshot-to-snapshot comparison of
  `mart_package_reach` will show new packages. Reach is opt-in and not yet in the monthly
  refresh, so nothing published moves until someone runs it.
- **The `OR … IN (subquery)` join** is correlated per `linked` row. `linked` is ~1.2k rows and
  the bridge a few thousand, so this is milliseconds; `_REKEY_EDGES_SQL` already does the same.
- **Views-file comments lag.** The new `DEFINITIONS` text reaches the published views file and
  `datapackage.json` on the next monthly `sync-marts.sh`. Descriptions only; no client breaks.

## Verification (2026-10-30)

- `GET https://api.openalex.org/works/doi:10.1101/577452?select=id,doi,ids` returns
  `W2970457274`, `doi` `https://doi.org/10.7717/peerj.7557`, PMID 31523512: the preprint DOI is
  still merged into the journal work, matching `tests/fixtures/api/openalex_works_merged.json`
  (whose `locations` include `https://doi.org/10.1101/577452`). No new fixture is recorded.
- The reach test above, run as a scratch file against `origin/main` (`b8e8560`), fails with
  `assert 49 == 98` (only `both` gets rows). With the one-line join change it passes, as do all of
  `tests/test_sources.py`. The scratch file and the change were removed afterwards.
- The rsec boundary case, run as a scratch script: the primed store plus the `gone` update holds
  `(4, 4)`; the two-package listing returns 2 and prints "2 packages listed, 3 with a bio.tools
  id".
