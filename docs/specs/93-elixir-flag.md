# Spec #93: ELIXIR RSEc / bio.tools flag on `dim_package`

Issue: [#93](https://github.com/seandavi/bioc-intelligence/issues/93). Background:
`docs/international-impact.md` §4 and recommendation 5.

## Goal

Give every package an "is it in ELIXIR" flag and, where one exists, its bio.tools id. Both come
from the ELIXIR Research Software Ecosystem (RSEc) content repo,
[`research-software-ecosystem/content`](https://github.com/research-software-ecosystem/content).
Store them on `dim_package` and surface them in `mart_package_directory`, along with a
`https://bio.tools/<id>` link that European reviewers recognise. Fetching is best-effort: a failure
logs, skips and never fails the refresh.

## Non-goals

- No frontend change. The Package page and Explorer can show the flag and link in a follow-up
  issue (the columns arrive in the published mart and in `export_api`'s per-package JSON, which
  does `SELECT *`, without code changes).
- No bio.tools API (it returned 403 from onclappc02) and no EDAM terms, bio.tools metadata or
  per-package blob fetches. We read file paths only, never file contents.
- No history: the flag is a dimension attribute, rebuilt each run, with no `_snapshot`.
- No matching for the non-`bioc` repos. RSEc imports only the software repo. Other repos get
  FALSE/NULL through the same name join, with no special-casing.

## What upstream looks like (verified 2026-10-23)

Every number below was measured on HEAD `9a5b1f7` (commit date 2026-10-23).

1. **`imports/bioconductor/`** has 4,932 blobs: `<name>.bioconductor.json` (2,418) and
   `<name>.bioconductor.citation.html` (2,514). `<name>` is the package name **lowercased**
   (`aneufinder`, `a4base`) and may contain dots (`alabaster.base`). The json is a plain VIEWS
   record (`Package`, `Version`, `biocViews`, …) and **carries no bio.tools id**, so the issue's
   "read the bio.tools id from each json" check came back negative. The 96 names with a
   `citation.html` but no json are stale leftovers of removed packages: none is in the current
   `dim_package`. All 2,418 json names match a current `bioc` package case-insensitively. No two
   `dim_package` names collide when lowercased.
2. **bio.tools ids live in `data/<id>/`** (43,105 folders, one per bio.tools-side tool). A
   Bioconductor package's bio.tools entry is a folder with `<id>.bioconductor.json`, where `<id>`
   is either the lowercased package name (`data/limma/`) or `bioconductor-<lowercased name>`
   (`data/bioconductor-ace/`, 1,126 folders, bulk-created by the gh2biotools bot in 2026-08/09).
   Its `<id>.biotools.json` has `"biotoolsID": "<id>"`.
   - **Name matching on `data/` is wrong.** 322 lowercased package names have a same-named
     `data/` folder with no `.bioconductor.json`, i.e. an unrelated tool. Example: `data/ace/` is
     a different ACE, and the package is `data/bioconductor-ace/`.
   - **Two ids for one package (11 cases).** `scater` + `bioconductor-scater`, `isee` +
     `bioconductor-isee`, and so on. The unprefixed one is the curated, older entry (scater:
     added 2018-06-04 by a human owner; bioconductor-scater: added 2026-09-01 by gh2biotools,
     with a wrong homepage pointing at scuttle).
   - **A `.bioconductor.json` with no `.biotools.json`: 33 folders.** Examples are
     `bioconductor-derfinderplot` (the package also has a complete `data/derfinderplot/`) and
     `bioconductor-biodbhmdb`. They look like imports not yet published to bio.tools.
3. **Why a git clone and not the trees API (do not "simplify" this back).** One
   `GET /repos/research-software-ecosystem/content/git/trees/HEAD:imports/bioconductor` returns
   the import folder untruncated (1.5 MB), which is enough for the flag. Ids need to know *which
   `data/<id>/` folders hold a `.bioconductor.json`*. The non-recursive `data/` tree gives only
   the 43k folder names (12 MB), and the recursive listing is ~150k entries, above the trees
   API's 100k-entry truncation limit (`"truncated": true`). Per-folder calls would be about 2.5k
   requests against a 60/hour unauthenticated limit. A shallow, blob-less clone gets every path
   in one transfer instead: `git clone --depth 1 --filter=blob:none --no-checkout` took 4 s and
   9.3 MB. Then `git ls-tree -r --name-only HEAD data imports/bioconductor` gives 155,329 lines,
   covering both the flag and the ids. The supervisor approved this on 2026-10-23 (option B).

## Design

### Pick rule (pure, in `parse_rsec_paths`)

Input: `ls-tree` path lines. Output: `dict[str, tuple[bool, str | None]]` keyed by **lowercased
package name**, value `(in_rsec, biotools_id)`.

- `in_rsec` is TRUE iff `imports/bioconductor/<name>.bioconductor.json` is present. Strip the
  exact suffix `.bioconductor.json` to get `<name>`; dotted names stay whole. `.citation.html`
  lines are ignored.
- **Qualified id:** a `data/<id>/` folder holding both `data/<id>/<id>.bioconductor.json` and
  `data/<id>/<id>.biotools.json`. Its package key is `<id>.removeprefix("bioconductor-")`.
  - Requiring `.biotools.json` is stricter than the supervisor's rule ("an id counts only when
    its folder has `<id>.bioconductor.json`"). It is a necessary-condition tightening, so a link
    never points at a bio.tools page that may not exist. Measured effect: 2,385 packages get an
    id instead of 2,403. The 18 dropped (`biodbhmdb`, `episeeker`, `iseehex`, `lintind`, …)
    have only a `bioconductor-` folder lacking `.biotools.json`. On the current listing the pick
    for the other 2,385 is identical under both rules.
- **Two qualified ids for a key:** take the unprefixed `<name>`; otherwise the single one.
  `bioconductor-derfinderplot` is not qualified (no `.biotools.json`), so `derfinderplot`
  → `derfinderplot`. `scater` and `bioconductor-scater` are both qualified → `scater`.
- A key appears in the dict if it has a json import, a qualified id, or both. Its value is
  `(name in imports, picked id or None)`. On the full listing that is 2,441 keys: 2,418 listed, and
  23 with an id but no json import. Those 23 are removed packages with only a `citation.html`
  left, so they match no `dim_package` row.

### Files to add / change

**`src/biocintel/config.py`** — one constant next to the other source URLs:

```python
# ELIXIR Research Software Ecosystem content repo (#93): imports/bioconductor + data/<biotools id>/.
RSEC_GIT_URL = "https://github.com/research-software-ecosystem/content.git"
```

**`src/biocintel/rsec.py`** (new; a helper module like `doi.py` / `authors.py`, not a pipeline
step). Stdlib only (`subprocess`, `tempfile`, `os`). No new dependency.

```python
def fetch_rsec_paths(timeout: float = 60.0) -> list[str]:
    """Every path under data/ and imports/bioconductor/ at RSEc HEAD (no file contents)."""
```
- Uses `with tempfile.TemporaryDirectory() as tmp:` (honours `TMPDIR`; cleans itself up).
- Runs `subprocess.run([...], check=True, capture_output=True, text=True, timeout=timeout,
  env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})` twice, with list argv and no shell:
  1. `["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout",
     RSEC_GIT_URL, tmp]`
  2. `["git", "-C", tmp, "ls-tree", "-r", "--name-only", "HEAD", "data", "imports/bioconductor"]`
- Returns `stdout.splitlines()`. It lets `FileNotFoundError` (no git),
  `subprocess.CalledProcessError` and `subprocess.TimeoutExpired` propagate, and the caller
  decides they are non-fatal.

```python
def parse_rsec_paths(paths: Iterable[str]) -> dict[str, tuple[bool, str | None]]:
    """{lowercased package: (in imports/bioconductor, bio.tools id or None)} per the pick rule."""
```

```python
def update_dim_package(con: duckdb.DuckDBPyConnection, flags: dict[str, tuple[bool, str | None]]) -> int:
    """Set dim_package.in_elixir_rsec / biotools_id for every row from ``flags``; returns rows flagged."""
```
- In one transaction: load `flags` into a temp table `_rsec(name VARCHAR, in_rsec BOOLEAN,
  biotools_id VARCHAR)`, then
  ```sql
  UPDATE dim_package SET
      in_elixir_rsec = COALESCE((SELECT r.in_rsec FROM _rsec r WHERE r.name = lower(package_name)), FALSE),
      biotools_id    = (SELECT r.biotools_id FROM _rsec r WHERE r.name = lower(package_name));
  ```
  Every row is rewritten, so a package that left RSEc goes back to FALSE/NULL. Drop the temp
  table afterwards. Return `count(*) FILTER (WHERE in_elixir_rsec)`.

```python
def refresh_dim_package(con: duckdb.DuckDBPyConnection) -> int | None:
    """Best-effort fetch → parse → update; None (values untouched) when skipped."""
```
- Calls `fetch_rsec_paths()`. On `(OSError, subprocess.SubprocessError)`, it prints
  `f"  ELIXIR RSEc listing unavailable ({exc}); skipped"` and returns None. `FileNotFoundError`
  is an `OSError`; `CalledProcessError` and `TimeoutExpired` are `SubprocessError`s.
- **Empty-listing guard:** if no key has `in_rsec` TRUE (upstream renamed or emptied
  `imports/bioconductor`), it prints `"  ELIXIR RSEc listing has no Bioconductor imports; skipped"`
  and returns None. That way an upstream reorganisation can't wipe every flag to FALSE.
- Otherwise it calls `update_dim_package`, prints `f"  ELIXIR RSEc: {n} packages listed,
  {k} with a bio.tools id"` and returns `n`.
- On skip the previous run's values persist: `INSERT OR REPLACE` with an explicit column list
  keeps unlisted columns. This was verified on DuckDB 2.0.0 and is the same behaviour CLAUDE.md
  notes for patent counts. In a fresh store they stay NULL ("unknown").

**`src/biocintel/pipeline/extract_packages.py`** — in `run()`, call
`rsec.refresh_dim_package(con)` once, right after `con.execute(_FIRST_SEEN_SQL)`, inside the
existing `try`. If it returns non-None, put the result in `counts["elixir_rsec"]`. Add one
sentence to the module docstring: "Then flags packages listed in the ELIXIR RSEc
(``in_elixir_rsec``, ``biotools_id``; best-effort, see ``biocintel.rsec``)." No new CLI flag or
subcommand. `biocintel extract-packages`, `biocintel all` and the systemd unit already call
`run()`, so **`systemd/biocintel-refresh.service` is unchanged**. git is `/usr/bin/git`, on
systemd's minimal PATH.

### DDL

`src/biocintel/schema.sql`, in `dim_package` after `needs_compilation BOOLEAN,`:

```sql
    in_elixir_rsec      BOOLEAN,          -- in ELIXIR RSEc imports/bioconductor (#93); NULL = never fetched
    biotools_id         VARCHAR,          -- bio.tools id from RSEc data/<id>/ (#93)
```

Migration in `src/biocintel/db.py`, following the per-issue column-list pattern:

```python
# dim_package columns added with the ELIXIR RSEc flag (#93).
_DIM_PACKAGE_RSEC_COLUMNS = [
    ("in_elixir_rsec", "BOOLEAN"),
    ("biotools_id", "VARCHAR"),
]
```
and in `init_schema`, a loop like the others:
`ALTER TABLE dim_package ADD COLUMN IF NOT EXISTS {name} {typ}`.

`_PKG_COLS` in `extract_packages.py` is **not** changed: the VIEWS upsert must not touch these
columns.

### Mart

`mart_package_directory` in `build_marts._MART_SQL`: append three columns after `bioc_url`:

```sql
       'https://bioconductor.org/packages/' || package_name || '/' AS bioc_url,
       in_elixir_rsec, biotools_id,
       'https://bio.tools/' || biotools_id AS biotools_url
```
(`||` with NULL yields NULL, so `biotools_url` is NULL exactly when `biotools_id` is.)

`DEFINITIONS["mart_package_directory"]["columns"]` additions, verbatim:

```python
"in_elixir_rsec": "Listed in the ELIXIR Research Software Ecosystem's weekly Bioconductor "
                  "import (research-software-ecosystem/content, imports/bioconductor). The "
                  "import covers the software (bioc) repo only, so other repos are FALSE. "
                  "FALSE means not in that import, not absent from bio.tools; NULL means the "
                  "listing has never been fetched.",
"biotools_id": "bio.tools identifier: the RSEc data/<id>/ folder holding both this package's "
               "Bioconductor record and a bio.tools record. When bio.tools has two entries, "
               "the curated id without the bioconductor- prefix wins. NULL when there is none "
               "or the listing has never been fetched.",
"biotools_url": "The package's bio.tools page (https://bio.tools/<biotools_id>).",
```

A mart schema change means the views file (`frontend/public/data/bioc-intelligence.duckdb`) must be
regenerated after the new marts deploy (CLAUDE.md, #51). The PR must say so. Agents don't run it.

### Upstream calls and fixtures

- Runtime: only the two git commands above. There are no HTTP API calls and no `http.py` cache.
  This is a ~9 MB transfer per `extract_packages.run()`.
- Checked once for this spec (not used at runtime):
  - `curl https://api.github.com/repos/research-software-ecosystem/content/git/trees/HEAD:imports/bioconductor`
    → 200, 4,932 entries, `truncated: false`.
  - `curl https://raw.githubusercontent.com/research-software-ecosystem/content/HEAD/data/scater/scater.biotools.json`
    → `biotoolsID: "scater"`.
  - `curl https://bio.tools/api/tool/scater?format=json` → 403 from onclappc02.
- **Fixture `tests/fixtures/rsec_ls_tree.txt`**: a hand-trimmed excerpt of the real
  `git ls-tree -r --name-only HEAD data imports/bioconductor` output (2026-10-23), exactly these
  lines:

```text
data/ace/ace.bioschemas.jsonld
data/ace/ace.biotools.json
data/alabaster.base/README.md
data/bioconductor-ace/bioconductor-ace.bioconductor.json
data/bioconductor-ace/bioconductor-ace.biotools.json
data/bioconductor-alabaster.base/bioconductor-alabaster.base.bioconductor.json
data/bioconductor-alabaster.base/bioconductor-alabaster.base.biotools.json
data/bioconductor-biodbhmdb/bioconductor-biodbhmdb.bioconductor.json
data/bioconductor-biodbhmdb/bioconductor-biodbhmdb.oeb.metrics.json
data/bioconductor-derfinderplot/bioconductor-derfinderplot.bioconductor.json
data/bioconductor-derfinderplot/bioconductor-derfinderplot.oeb.metrics.json
data/bioconductor-scater/bioconductor-scater.bioconductor.json
data/bioconductor-scater/bioconductor-scater.biotools.json
data/derfinderplot/derfinderplot.bioconductor.json
data/derfinderplot/derfinderplot.biotools.json
data/limma/limma.bioconductor.json
data/limma/limma.biotools.json
data/limma/r-bioc-limma.debian.yaml
data/scater/scater.bioconductor.json
data/scater/scater.biotools.json
imports/bioconductor/ace.bioconductor.citation.html
imports/bioconductor/ace.bioconductor.json
imports/bioconductor/alabaster.base.bioconductor.json
imports/bioconductor/aneufinder.bioconductor.citation.html
imports/bioconductor/biodbhmdb.bioconductor.citation.html
imports/bioconductor/derfinderplot.bioconductor.json
imports/bioconductor/limma.bioconductor.citation.html
imports/bioconductor/limma.bioconductor.json
imports/bioconductor/scater.bioconductor.json
```
  `data/alabaster.base/README.md` is synthetic: it's a same-name folder with no
  `.bioconductor.json`, which proves a dotted name isn't matched by folder name. Every other line
  is verbatim upstream. Expected parse result:

| key | value | case |
|---|---|---|
| `ace` | `(True, "bioconductor-ace")` | `data/ace/` is an unrelated tool (no `.bioconductor.json`) |
| `alabaster.base` | `(True, "bioconductor-alabaster.base")` | dotted name; same-name folder ignored |
| `derfinderplot` | `(True, "derfinderplot")` | prefixed folder lacks `.biotools.json` |
| `limma` | `(True, "limma")` | plain case |
| `scater` | `(True, "scater")` | two qualified ids → unprefixed |

  `aneufinder` (citation.html only) and `biodbhmdb` (citation.html only; folder lacks
  `.biotools.json`) are **absent** from the dict.

## Acceptance criteria

- [ ] `parse_rsec_paths(open(fixture).read().splitlines())` returns exactly the 5-key dict above.
- [ ] `init_schema` on a store created before #93 adds `dim_package.in_elixir_rsec BOOLEAN` and
      `biotools_id VARCHAR`. A fresh schema has them too.
- [ ] `update_dim_package` on a store with `limma`/bioc, `ACE`/bioc, `scater`/bioc,
      `org.Hs.eg.db`/data-annotation, and `gone`/bioc pre-set to `(TRUE, 'gone')`, given the
      fixture's flags, yields limma `(TRUE,'limma')`, ACE `(TRUE,'bioconductor-ace')`, scater
      `(TRUE,'scater')`, org.Hs.eg.db `(FALSE,NULL)`, gone `(FALSE,NULL)`, and returns 3.
- [ ] `refresh_dim_package` with `rsec.fetch_rsec_paths` monkeypatched to raise
      `subprocess.TimeoutExpired`, `FileNotFoundError` or `subprocess.CalledProcessError` returns
      None, raises nothing and leaves pre-set values unchanged. The same holds when the fetch
      returns only `data/...` lines (empty-import guard).
- [ ] A VIEWS re-upsert through `extract_packages._upsert(con, "dim_package", _PKG_COLS, …)` keeps
      existing `in_elixir_rsec` / `biotools_id` values.
- [ ] `mart_package_directory` has `in_elixir_rsec`, `biotools_id` and `biotools_url`.
      `biotools_url = 'https://bio.tools/limma'` for limma and NULL when `biotools_id` is NULL.
      All three have `DEFINITIONS` entries, so the build's definitions check passes.
- [ ] No test runs git or touches the network.
- [ ] `uv run pytest` and `uv run ruff check src tests` pass.
- [ ] `bioc-intelligence-spec.md` §5 `dim_package` lists `in_elixir_rsec?, biotools_id?` with a
      one-line comment ("ELIXIR RSEc, best-effort (#93)"). CLAUDE.md's `extract-packages`
      command comment mentions the RSEc flag.

## Test plan

New `tests/test_rsec.py` (offline, fixture-based):

1. `test_parse_rsec_paths_fixture`: the 5-key expectation table, including the ace trap, the
   dotted name and the scater two-id case.
2. `test_update_dim_package_sets_and_resets`: the in-memory store case from the acceptance
   criteria (`db.connect(":memory:")` + `db.init_schema`).
3. `test_refresh_skips_on_fetch_failure` (parametrised over the three exceptions) and
   `test_refresh_skips_empty_import_listing`: use `monkeypatch.setattr(rsec, "fetch_rsec_paths",
   ...)`, pre-set values unchanged, return None.
4. `test_views_upsert_keeps_rsec_columns`: pre-set the flag, re-upsert a VIEWS row via `_upsert`,
   assert the flag survives.

`tests/test_marts.py`: extend `test_directory_mart_has_description_not_email` (or add
`test_directory_mart_biotools_columns`) to set `biotools_id='limma', in_elixir_rsec=TRUE` on the
fixture row, then assert the three columns and the URL. The existing DEFINITIONS-coverage check in
the build covers the definitions.

Manual (not CI; optional smoke by the implementer, read-only, no store writes): `uv run python -c
"from biocintel import rsec; f=rsec.parse_rsec_paths(rsec.fetch_rsec_paths()); print(sum(v[0]
for v in f.values()), sum(v[1] is not None for v in f.values()))"` → about `2418 2385`.

## Risks

- **The flag is nearly `repo = 'bioc'` today.** All 2,418 current bioc packages are listed. The
  `biotools_id` (2,385) and the link are the useful parts, and the flag catches packages that
  drop out between syncs. The DEFINITIONS text says what FALSE does not mean.
- **Upstream layout is not a contract.** RSEc can rename folders or change the `bioconductor-`
  convention, and the gh2biotools bot is still creating duplicates. The empty-import guard covers
  a vanished import folder. A changed id convention would silently yield fewer ids (NULL, not
  wrong ids), because an id must name its own `.bioconductor.json`.
- **Duplicate bio.tools entries.** The unprefixed preference is a heuristic checked on 11 pairs
  (scater, isee, …). Upstream may later merge them, after which the id changes on the next run.
- **Stricter-than-approved id rule.** Requiring `.biotools.json` drops 18 ids whose bio.tools
  page may not exist yet. They'll appear once RSEc adds the file. A reviewer may relax it to the
  supervisor's bioconductor.json-only rule; that changes no other pick today.
- **Clone cost and environment.** It's 9 MB / ~4 s per `extract_packages.run()`, with no cache.
  Dev re-runs pay it too. Under systemd, `TMPDIR` is unset, so the clone lands in `/tmp` (small
  and noexec on onclappc02). 9 MB is fine, and git executes nothing from the clone. A git or
  GitHub outage only means a month of stale flags.
- **Data run.** No backfill is needed. The next monthly refresh fills the columns. After the
  new marts deploy, a human must regenerate the views file (mart schema change).
