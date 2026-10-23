# Spec #109: follow-ups from the #102 review (alias precedence)

Issue: [#109](https://github.com/seandavi/bioc-intelligence/issues/109). Base:
[`docs/specs/102-alias-precedence.md`](102-alias-precedence.md), merged in `e5233e0` (#110).

*Spec stage, 2026-10-23. The OpenAlex fact below was checked that day with curl. See
"Verification".*

## Goal

Close the four findings in #109. Every change is to text: docstrings, CLAUDE.md, a spec quote,
`DEFINITIONS` strings and two frontend lookup tables.

| Finding | What changes |
|---|---|
| code-r0-1 | `enrich_from_lake.py` module docstring and the CLAUDE.md `reach` bullet say reach counts `doi`/`doi_alias`/`citation_file` papers |
| code-r0-2 + data-r0-1 | `mart_work.alias_dois` definition, CLAUDE.md and the #95 spec quote say only a DOI that is a *loaded* work's own DOI is never an alias |
| data-r0-2 | About METHODS table gains a `doi_alias` row; ImpactLeaderboard `METHOD_LABEL` gains `doi_alias` |
| data-r0-3 | `mart_package_work.match_method` definition says the alias is "usually the preprint", not always |

## Non-goals

- No behaviour change. The guard in `sources/__init__.py` (`DELETE FROM works_alt_dois WHERE doi
  IN (SELECT doi FROM lake.openalex.works …)`) stays as it is. The issue asks for the text to
  match the code, not the code to match the text. Counts don't change either: marts use
  `alias_dois` only to match bridge keys.
- No schema, migration, mart-column, HTTP or fixture change. `_REACH_WORKS_SQL` already includes
  `doi_alias` (since #102).
- `Package.tsx` stays as it is: the issue says its `doi_alias` chip label ("DESCRIPTION DOI
  (merged preprint)") can stay.
- No edits to other "preprint merged into its journal version" wording that #109 does not name:
  `mart_package_work.doi` and `mart_work.alias_dois` (both say "e.g." or give one case),
  `HONEST_VIEWS["package_pubs_confident"]`, the `link_works.py` docstring and the line-33
  comment, `enrich_from_lake.py` lines 39-40 and 70, `sources/openalex.py::alt_doi_rows`,
  `schema.sql` line 80. If they should change too, that needs its own issue.
- `docs/specs/102-alias-precedence.md` is not edited. Only the #95 quote is narrowed, as the
  issue asks.
- No data run. `DEFINITIONS` text goes into the views file's column comments and
  `datapackage.json` on the next `sync-marts.sh` (monthly refresh). No mart schema changes, so
  the views file does not have to be regenerated early.

## Design

### Files

| File | Change |
|---|---|
| `src/biocintel/pipeline/enrich_from_lake.py` | module docstring `reach` bullet (code-r0-1) |
| `CLAUDE.md` | `reach` bullet (code-r0-1); #95/#102 paragraph alias sentence (code-r0-2) |
| `src/biocintel/pipeline/build_marts.py` | `DEFINITIONS["mart_work"]["columns"]["alias_dois"]` (code-r0-2); `DEFINITIONS["mart_package_work"]["columns"]["match_method"]` (data-r0-3) |
| `docs/specs/95-openalex-id-drift.md` | the `alias_dois` quote at line 188 (code-r0-2) |
| `frontend/src/pages/About.tsx` | `METHODS` row (data-r0-2) |
| `frontend/src/pages/ImpactLeaderboard.tsx` | `METHOD_LABEL` entry (data-r0-2) |
| `tests/test_marts.py` | four new asserts in `test_definitions_explain_alias_dois_and_doi_alias` |

### code-r0-1: reach bullets

**`enrich_from_lake.py`, module docstring, lines 27-31.** Adding `` ``doi_alias``/ `` pushes line
27 past ruff's 100 characters, so the bullet is rewrapped. It becomes exactly:

```
- **reach** (opt-in, api-only) — per package, the works citing its
  ``doi``/``doi_alias``/``citation_file`` primary papers (one OR'd ``cites:`` filter over this
  run's live OpenAlex ids), counted by author affiliation country and by funder via OpenAlex
  ``group_by`` → ``fact_package_reach`` (snapshot-stamped, with ``n_works``, the papers
  counted); citing-work funders are merged into ``dim_funder`` (#92). Needs
  ``OPENALEX_API_KEY`` (~2 calls per package). Best-effort.
```

**`CLAUDE.md`, lines 84-88.** Rewrapped the same way, it becomes exactly:

```
- `reach` (**opt-in**, api-only) — `group_by` on works citing each package's
  `doi`/`doi_alias`/`citation_file` primary papers (one OR'd `cites:` filter, this run's live
  ids) → `fact_package_reach` (country, funder, total, with `n_works`, the resolved papers
  counted; snapshot-stamped) and the citing-work funders merged into `dim_funder`. ~2 calls
  per package: needs `OPENALEX_API_KEY` and is skipped without it. Funders are top-200 by count.
```

### code-r0-2 / data-r0-1: what "never an alias" covers

The code's rule: a DOI is dropped from `works_alt_dois` only when it is the own DOI of a work in
this run's `lake.openalex.works`. That table holds the works fetched for linking (package DOIs and
title hits) and for enrichment (linked works, and citing works when `citations` runs). A live
preprint that nothing fetched in the run can stay as an alias.

**`build_marts.py`, `DEFINITIONS["mart_work"]["columns"]["alias_dois"]`.** Replace the sentence
"A DOI OpenAlex also holds as a separate work is never listed." Once the literals are joined, the
full string is exactly:

> Other DOIs OpenAlex lists for this work, e.g. the bioRxiv preprint a package's CITATION cites
> after OpenAlex merged it into the journal version. NULL when OpenAlex lists none, and always
> NULL for works enriched under --source lake (the lake drops locations) or from iCite alone, so
> NULL does not mean the work has no preprint. A DOI that is another linked or loaded work's own
> DOI is never listed; a preprint OpenAlex still keeps as its own work can be listed if this run
> did not load it. doi is the version the metrics describe.

Keep the existing literal-concatenation style with lines of 100 characters or fewer.

**`CLAUDE.md`, line 99.** "a DOI that is still some work's own DOI is never an alias (#102)" becomes
"a DOI that is some loaded work's own DOI is never an alias (#102)". The rest of the sentence and
paragraph stays as it is.

**`docs/specs/95-openalex-id-drift.md`, line 188.** In the quoted string, replace "A DOI OpenAlex
also holds as a separate work is never listed." with the same two clauses as above ("A DOI that is
another linked or loaded work's own DOI is never listed; a preprint OpenAlex still keeps as its own
work can be listed if this run did not load it."). Change the trailing "(amended by #102)" to
"(amended by #102, narrowed by #109)". The quote then equals the new definition text.

### data-r0-2: frontend tables

**`frontend/src/pages/About.tsx`, `METHODS`.** Insert this row between the `doi` and
`citation_file` rows (in confidence order, then by provenance), with the text taken from the issue:

```tsx
  ["doi_alias", "1.0", "A DOI from the package's own metadata that OpenAlex has merged into another version of the paper (usually the bioRxiv preprint of the journal article). The link and its metrics point at the version OpenAlex keeps."],
```

**`frontend/src/pages/ImpactLeaderboard.tsx`, `METHOD_LABEL`.** Insert between `doi` and
`citation_file`:

```tsx
  doi_alias: "DOI (merged preprint)",
```

### data-r0-3: `match_method` definition

**`build_marts.py`, `DEFINITIONS["mart_package_work"]["columns"]["match_method"]`.** Once the
literals are joined, the full string is exactly:

> How the link was made: doi (the package's own DOI), doi_alias (the package's DOI is another
> version of the paper, usually the preprint, that OpenAlex merged into this work; doi shows the
> version OpenAlex keeps), citation_file (CITATION / CITATION.cff), description_doi (a DOI in
> Description, sometimes a dependency's paper), title_search, manual.

"doi shows the journal version" becomes "doi shows the version OpenAlex keeps", because a Zenodo
or arXiv alias is not always merged into a journal article.

### Entry points

None change. `biocintel build-marts` (`build_marts.run()`) and `write_views_db` pick up the new
`DEFINITIONS` text. The frontend change ships on the next Pages deploy.

## Acceptance criteria

- [ ] `enrich_from_lake.py`'s `reach` bullet and CLAUDE.md's `reach` bullet are exactly the text
      above. Both name `doi_alias`, and no line in `enrich_from_lake.py` is longer than 100
      characters.
- [ ] `DEFINITIONS["mart_work"]["columns"]["alias_dois"]` equals the text above once the literals
      are joined. It contains "another linked or loaded work's own DOI" and does not contain "also
      holds as a separate work".
- [ ] CLAUDE.md contains "a DOI that is some loaded work's own DOI is never an alias" and no
      longer contains "still some work's own DOI".
- [ ] The `alias_dois` quote in `docs/specs/95-openalex-id-drift.md` equals the new definition
      text and ends "(amended by #102, narrowed by #109)".
- [ ] `DEFINITIONS["mart_package_work"]["columns"]["match_method"]` equals the text above. It
      contains "usually the preprint" and not "is a preprint OpenAlex merged".
- [ ] About `METHODS` has the `doi_alias` row above as its second entry. `METHOD_LABEL` in
      `ImpactLeaderboard.tsx` maps `doi_alias` to `"DOI (merged preprint)"`. `Package.tsx` is
      unchanged.
- [ ] `uv run pytest` and `uv run ruff check src tests` pass. The worktree has no venv yet, so set
      one up first with `uv venv && uv pip install -e '.[dev]'`.
- [ ] `cd frontend && npm ci && npm run typecheck && npm run lint` pass, the same checks as
      `frontend-ci.yml`.
- [ ] No change under `data/` or `frontend/public/data/`. No new fixture files. `git diff
      origin/main --stat` lists only the seven files in the Files table (plus this spec).

## Test plan

All offline.

1. **Update** `tests/test_marts.py::test_definitions_explain_alias_dois_and_doi_alias` and add:
   ```python
   assert "another linked or loaded work's own DOI" in work["alias_dois"]
   assert "also holds as a separate work" not in work["alias_dois"]
   assert "usually the preprint" in pkg_work["match_method"]
   assert "is a preprint OpenAlex merged" not in pkg_work["match_method"]
   ```
   Keep the existing asserts. They still hold.
2. `tests/test_views_db.py::test_views_db_over_fixture_marts` (views-file column comments and
   `datapackage.json`) runs on the new strings unchanged. Nothing escapes differently: the new text has apostrophes in "work's" and
   "package's", as the old text did, and `_q` handles them.
3. Frontend: `npm run typecheck` and `npm run lint` (no frontend unit tests exist). Optional
   visual check from the Vite dev server (`npm run dev`): `/about#linked-papers` shows a match-method table with four rows.

## Risks

- **The "loaded" wording leaks an implementation detail.** Readers of `mart_work.alias_dois` now
  learn that the list depends on what a run fetched. Accepted: the issue asks for the definition
  to match the code, and the alternative (a stricter guard that asks OpenAlex whether each alias
  DOI resolves to its own work) is a behaviour change out of #109's scope.
- **Views-file comments lag.** The published views file and `datapackage.json` keep the old text
  until the next monthly `sync-marts.sh`. They are only descriptions, so no client breaks.

## Verification (2026-10-23)

- `GET https://api.openalex.org/works/doi:10.7717/peerj.7557?select=id,doi,locations` (HiLDA):
  `W2970457274`, `doi` `https://doi.org/10.7717/peerj.7557`. Its locations include
  `https://doi.org/10.1101/577452` (the bioRxiv preprint).
- `GET https://api.openalex.org/works/doi:10.1101/577452?select=id,doi` returns the same
  `W2970457274` with the journal DOI. The preprint is merged, not live, so it is the case the
  current alias text describes. The live-preprint case in data-r0-1 is the one the narrowed text
  covers.
- No other upstream call is involved. #109 adds no fetch.
