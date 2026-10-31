# Spec #98: follow-ups from the #93 review (ELIXIR RSEc flag)

Issue: [#98](https://github.com/seandavi/bioc-intelligence/issues/98). Base:
[`docs/specs/93-elixir-flag.md`](93-elixir-flag.md), merged in `8ef42cb`.

*Spec stage, 2026-10-23. Upstream facts were checked that day with `gh api` against
`research-software-ecosystem/content` (default branch `master`). See "Verification".*

## Goal

Close the five findings in #98:

| Finding | What changes |
|---|---|
| code-r0-2 | `bioc-intelligence-spec.md` §4 Data Sources table gets an RSEc row |
| data-r0-1 | `in_elixir_rsec` and `biotools_id` DEFINITIONS: NULL means "not yet checked against the listing" (new package, or the fetch was skipped), and values carry over from the last successful fetch |
| data-r0-2 | doc-only (supervisor decision, option (a)): `in_elixir_rsec` DEFINITIONS says the match is by package name in any repo, so a stale row for a package that moved repos can also read TRUE |
| data-r0-3 | keep "weekly" and cite the upstream workflow that sets the cadence |
| data-r0-4 | sanity floor in `rsec.refresh_dim_package` (supervisor decision, option (b)): skip the update when the parsed listing shrank below half of what the store already holds |

## Non-goals

- No `AND repo = 'bioc'` in `update_dim_package`. The supervisor chose the doc-only fix: the
  root cause is that `dim_package` never drops the row of a package that moved repos. That
  affects every column, and a repo guard here would patch one symptom. #93's "no special-casing"
  non-goal stands.
- No change to `parse_rsec_paths`, `fetch_rsec_paths`, `update_dim_package`, the schema, or the
  migration. No DDL change and no new mart column. A comment-only edit to `schema.sql` (the
  `in_elixir_rsec` NULL wording, #121) is allowed.
- No "stale since" or last-fetched timestamp column. The DEFINITIONS text says values carry over.
- No configurable floor (env var or CLI flag). It is a fixed one half.
- `docs/specs/93-elixir-flag.md` and `docs/international-impact.md` are not edited. The first
  records what #93 specified; the second already says "weekly", which is now verified.
- No frontend change. No new HTTP calls, no new fixture files.
- No data run is needed. The DEFINITIONS text reaches the published `definitions.json` on the
  next monthly refresh; the floor first acts on the refresh after that.

## Design

### Files

| File | Change |
|---|---|
| `bioc-intelligence-spec.md` | §4 table: one new row |
| `src/biocintel/pipeline/build_marts.py` | `in_elixir_rsec` and `biotools_id` DEFINITIONS text in `mart_package_directory` (lines 572-581) |
| `src/biocintel/rsec.py` | module docstring cites the weekly cadence; `refresh_dim_package` gets the shrink floor and a new docstring |
| `tests/test_rsec.py` | three new tests for the floor |

`CLAUDE.md` needs no change: its RSEc line (line 27) stays true.

### `bioc-intelligence-spec.md` §4

Append this row as the last row of the Data Sources table, after the `Version/release history`
row (keep the column padding of the surrounding rows):

```
| ELIXIR RSEc flag / bio.tools id | `research-software-ecosystem/content` (`imports/bioconductor`, `data/<id>/` paths) | git (blob-less shallow clone) | monthly, best-effort (#93); upstream imports weekly |
```

### `build_marts.py` DEFINITIONS

Replace the two entries in `DEFINITIONS["mart_package_directory"]["columns"]` with exactly this
text (wrap the Python string literals the way the surrounding entries do; the rendered strings
must match):

- `in_elixir_rsec`: "Listed in the ELIXIR Research Software Ecosystem's weekly Bioconductor
  import (research-software-ecosystem/content, imports/bioconductor). Matched by package name in
  any repo. The import covers the software (bioc) repo, so other repos normally read FALSE, but a
  stale row for a package that moved repos can also read TRUE. FALSE means not in that import,
  not absent from bio.tools. NULL means the package has not yet been checked against the listing
  (new package, or the fetch was skipped). Values carry over from the last successful fetch."
- `biotools_id`: "bio.tools identifier: the RSEc data/<id>/ folder holding both this package's
  Bioconductor record and a bio.tools record. When bio.tools has two entries, the curated id
  without the bioconductor- prefix wins. NULL when there is none, or when the package has not yet
  been checked against the listing (new package, or the fetch was skipped). Values carry over
  from the last successful fetch."

`biotools_url` is unchanged.

### `rsec.py`

Module docstring: append one sentence to the existing paragraph:

```
RSEc re-imports Bioconductor weekly (cron ``0 0 * * 0``, the ``bioconductor`` job in the
content repo's ``.github/workflows/import.yaml``).
```

`refresh_dim_package(con: duckdb.DuckDBPyConnection) -> int | None` keeps its signature and
return contract (flagged-row count, or `None` with values untouched when skipped). New body:

```python
def refresh_dim_package(con: duckdb.DuckDBPyConnection) -> int | None:
    """Best-effort fetch → parse → update; None (values untouched) when skipped.

    Skips on a fetch failure, a listing with no Bioconductor imports, or a listing that shrank
    below half of the stored counts (likely an upstream reorganisation, not real removals).
    """
    try:
        paths = fetch_rsec_paths()
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  ELIXIR RSEc listing unavailable ({exc}); skipped")
        return None
    flags = parse_rsec_paths(paths)
    n_listed = sum(in_rsec for in_rsec, _ in flags.values())
    n_ids = sum(biotools_id is not None for _, biotools_id in flags.values())
    if not n_listed:
        print("  ELIXIR RSEc listing has no Bioconductor imports; skipped")
        return None
    stored_listed, stored_ids = con.execute(
        "SELECT count(*) FILTER (WHERE in_elixir_rsec), count(biotools_id) FROM dim_package"
    ).fetchone()
    # ponytail: parsed counts include names not in dim_package, so this floor only errs lenient.
    if n_listed < stored_listed / 2 or n_ids < stored_ids / 2:
        print(f"  ELIXIR RSEc listing shrank: {n_listed} listed / {n_ids} bio.tools ids, "
              f"store has {stored_listed} / {stored_ids}; skipped")
        return None
    n = update_dim_package(con, flags)
    k = con.execute("SELECT count(*) FROM dim_package WHERE biotools_id IS NOT NULL").fetchone()[0]
    print(f"  ELIXIR RSEc: {n} packages listed, {k} with a bio.tools id")
    return n
```

Rules this encodes:

- The floor compares the parsed listing (`flags`) with the store **before** the update. Strict
  `<`: exactly half passes.
- A first run (stored counts 0) always passes the floor. The empty-listing guard stays and runs
  first, so a total wipe still prints its own message.
- The skip line prints both the parsed and the stored counts (supervisor requirement), so a
  reorganisation (one count drops) reads differently from an outage (fetch failure line).
- The caller in `extract_packages.run()` (line 291) is unchanged: `None` already means "no
  `elixir_rsec` count".

## Acceptance criteria

- [ ] `bioc-intelligence-spec.md` §4 table has the RSEc row above as its last row.
- [ ] `DEFINITIONS["mart_package_directory"]["columns"]["in_elixir_rsec"]` and `["biotools_id"]`
      equal the text above, character for character once the literals are joined.
- [ ] `in_elixir_rsec` text contains "weekly", "Matched by package name in any repo", "moved
      repos can also read TRUE" and "Values carry over from the last successful fetch"; it no
      longer contains "never been fetched" or "so other repos are FALSE".
- [ ] `biotools_id` text no longer contains "never been fetched" and contains "Values carry over
      from the last successful fetch".
- [ ] `rsec.py` module docstring cites `0 0 * * 0` and `.github/workflows/import.yaml`.
- [ ] `refresh_dim_package` returns `None` and leaves `in_elixir_rsec`/`biotools_id` untouched
      when the parsed listed count is below half the stored TRUE count, or the parsed id count is
      below half the stored non-NULL `biotools_id` count; the printed line contains both pairs of
      counts.
- [ ] A shrink to exactly half or more still updates.
- [ ] Existing `tests/test_rsec.py` tests pass unchanged.
- [ ] `uv run pytest` and `uv run ruff check src tests` pass.
- [ ] No change under `data/` or `frontend/public/data/`; no schema or migration change.

## Test plan

All in `tests/test_rsec.py`, offline, built from the existing fixture
`tests/fixtures/rsec_ls_tree.txt` with `_store()`, `_flags()` and `_paths()`. With that fixture
the parse gives 5 listed names and 5 ids; after a full update the store holds 3 TRUE (`limma`,
`ACE`, `scater`) and 3 ids.

A shared helper:

```python
def _primed(monkeypatch):
    """Store after one good refresh: 3 listed, 3 ids."""
    con = _store()
    monkeypatch.setattr(rsec, "fetch_rsec_paths", _paths)
    assert rsec.refresh_dim_package(con) == 3
    return con
```

1. `test_refresh_skips_shrunken_import_listing(monkeypatch, capsys)`: `_primed`, then
   `fetch_rsec_paths` returns `_paths()` minus every `imports/bioconductor/` line except
   `imports/bioconductor/limma.bioconductor.json` (parsed listed 1 < 3/2). Assert the return is
   `None`, `_flags(con)` equals its value right after priming, and the captured stdout contains
   `"1 listed"` and `"store has 3 / 3"`.
2. `test_refresh_skips_shrunken_biotools_ids(monkeypatch)`: `_primed`, then drop every path
   ending in `.biotools.json` (parsed ids 0 < 3/2, listed still 5). Assert `None` and flags
   unchanged.
3. `test_refresh_updates_on_modest_shrink(monkeypatch)`: `_primed`, then keep only the
   `limma` and `ace` `.bioconductor.json` import lines (parsed listed 2, not < 1.5). Assert the
   return is 2 and `scater` now reads `(False, "scater")`: the update ran, and `biotools_id` is
   still set because the id join does not depend on the import listing.

No DEFINITIONS-text test: the acceptance check is a read of the literal.

## Risks

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
- **The floor misses a moderate reorganisation** (under half moved). Accepted: it is a sanity
  check, not a diff.
- **Stale moved-repo rows** still read TRUE, now documented. The root fix (pruning `dim_package`
  rows for packages that left a repo) is out of scope and affects every column.

## Verification (2026-10-23)

- `gh api repos/research-software-ecosystem/content/contents/.github/workflows/import.yaml`:
  `on.schedule.cron: "0 0 * * 0"` (Sundays 00:00 UTC) and a `bioconductor` job using
  `research-software-ecosystem/utils/bioconductor-import@main`. Last change to that file:
  `64fdc3e`, 2026-09-29.
- `gh api 'repos/research-software-ecosystem/content/commits?path=imports/bioconductor'`:
  "import BioConductor tools data" commits on 2026-09-06, 09-13, 09-20, 09-27, 10-04, 10-11,
  10-18 (each ~00:50 UTC), plus manual runs on 09-29, 09-30 and 10-02. Weekly holds.
- The production store (`data/biocintel.duckdb`, read-only) has no `in_elixir_rsec` column yet:
  no refresh has run since #93 merged, so there are no stored counts to calibrate against. #93's
  verified upstream counts (2,418 bioc listed, 2,385 ids) put the floor at about 1,200.
