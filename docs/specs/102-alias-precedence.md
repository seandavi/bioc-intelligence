# Spec #102: alias-DOI precedence, `doi_alias` match method, definition fixes (#95 follow-ups)

Issue: https://github.com/seandavi/bioc-intelligence/issues/102. These are follow-ups from the
#95 review: code-r0-2, code-r0-3, code-r0-4 and data-r0-4. Review lenses: `code`, `data`.
`docs/specs/95-openalex-id-drift.md` is the design this amends.

## Findings (verified 2026-10-23, live OpenAlex vs a copy of the 2026-10-07 store)

- **Own DOI vs alias (code-r0-3).** The working set has 1,199 DOIs: every `dim_work.doi` plus
  every DOI-shaped `bridge_package_pub.work_id`. They were fetched with
  `filter=doi:<50 DOIs>&select=id,doi,locations` and returned 1,181 works carrying **537 alias
  DOIs**. By prefix: 10.1101 362, 10.5167 29, 10.17863 26, 10.3929 22, 10.48550 17,
  10.21203 17, 10.5281 9.
  - All 537 were then looked up again with `filter=doi:<alias>`. **None** came back as a
    different live work's own DOI. No alias DOI sits on two works.
  - So the "live preprint + journal work listing it" shape does not occur today. The guard is
    defensive: it keeps OpenAlex's data from changing our counts if the shape appears. It also
    means **no real response can be recorded**, so the test record is hand-built (see *Fixtures*).
- **How `filter=doi:` behaves.** `filter=doi:10.1101/002832` (DESeq2's bioRxiv DOI) returns
  one work, `W2179438025`, with `doi https://doi.org/10.1186/s13059-014-0550-8`. Its
  `locations` hold both DOIs. `filter=doi:10.1101/060012` returns a live bioRxiv work whose
  only location DOI is its own.
- **`doi_alias` reach (data-r0-4).** 25 packages have a `dim_package.source_doi`. 22 match a
  work's own DOI and 2 match only an alias: HiLDA `10.1101/577452` and saseR
  `10.1101/2023.06.29.547014`. Those 2 `link_works` rows become `doi_alias`. Separately,
  163 `citation_file` and 3 `description_doi` bridge rows are keyed on an alias DOI. They keep
  their method, and `mart_package_work.doi` shows the journal DOI for them (definition fix
  below).
- `_WORKS_SQL` writes `alias_dois` NULL when a work has none. It is always NULL under
  `--source lake` and for iCite-fallback works (code-r0-2).

## Goal

1. **An own-DOI match always wins.** A DOI that is some loaded OpenAlex work's own `doi` is
   never an alias. One bridge DOI then links one work, and the marts never count a live
   preprint and its journal version as one paper reached twice.
2. **Citation edges move only off rows the prune will delete.** The re-key never moves edges
   off a work that is still linked.
3. **Alias-derived `link_works` rows can be counted and filtered.** They get
   `match_method = 'doi_alias'` (confidence 1.0). Every "confident links" filter (`doi`,
   `citation_file`) gains `doi_alias`, so published numbers do not change.
4. **Definitions say what NULL and `doi` do not mean.** That covers `mart_work.alias_dois`
   (code and the #95 spec), `mart_package_work.doi`, `match_method` and `confidence`.
5. The `enrich_from_lake` module docstring describes what the grants step really deletes.

## Non-goals

- No new `match_method` for `citation_file` or `description_doi` rows reconciled through an
  alias. They keep their method. Only `mart_package_work.doi`'s definition explains it.
- No DDL change and no migration. `bridge_package_pub.match_method` is free-text `VARCHAR`;
  only its comment changes. `link_works` rewrites all of its rows each run.
- No change to `_REACH_WORKS_SQL`'s join. It still misses `citation_file` rows keyed on an
  alias DOI (see Risks); that is a separate follow-up. Only its method list gains `doi_alias`.
- No change to `bioc-intelligence-spec.md`. Its `match_method` list is already stale, and
  CLAUDE.md is the maintained list.
- No new API calls, endpoints, CLI flags or `run()` signatures.

## Design

### `src/biocintel/sources/__init__.py`

- In `_load_works`, after the `works_alt_dois` insert, run this **unconditionally** (also when
  `rows` is empty, because a newly loaded work may own an earlier alias):
  ```python
  # An own DOI always wins: OpenAlex can keep a preprint live while its journal version lists
  # it in locations, and as an alias it would link both works to one bridge DOI (#102).
  con.execute("DELETE FROM works_alt_dois WHERE doi IN "
              "(SELECT doi FROM lake.openalex.works WHERE doi IS NOT NULL)")
  ```
  Every loader goes through `_load_works`: the link DOI and title fetches, the enrich PMID, DOI
  and stored-id fetches, and the citations step's citing works. The works set only grows, so
  the table holds no owned DOI after any load.
- `_UNLINKED_TITLES_SQL`: `AND b.match_method NOT IN ('doi', 'doi_alias', 'title_search'))`
  (`link_works` clears these three methods; see below).

### `src/biocintel/pipeline/link_works.py`

- `_DOI_SQL`: the union carries the method, so the alias branch writes `doi_alias`:
  ```sql
  INSERT INTO bi.bridge_package_pub (package_name, repo, work_id, role, match_method, confidence)
  SELECT p.package_name, p.repo,
         COALESCE(CAST(w.pmid AS VARCHAR), w.doi) AS work_id,
         'primary', w.match_method, 1.0
  FROM bi.dim_package p
  JOIN (
      SELECT pmid, doi, doi AS join_doi, 'doi' AS match_method FROM lake.openalex.works
      UNION ALL
      SELECT w.pmid, w.doi, a.doi, 'doi_alias' FROM lake.openalex.works w
      JOIN works_alt_dois a ON a.work_id = w.id
  ) w
    ON lower(regexp_replace(p.source_doi, '^(https?://(dx\\.)?doi\\.org/|doi:)', '', 'i'))
       = w.join_doi
  WHERE p.source_doi IS NOT NULL;
  ```
  Comment above it: append "An alias match (the package's DOI is one OpenAlex merged into the
  work, #95) is `doi_alias`, so it can be counted and filtered (#102)."
- `run()`: the delete becomes
  `"DELETE FROM bi.bridge_package_pub WHERE match_method IN ('doi', 'doi_alias', 'title_search')"`.
  The count key stays `"doi"` and counts both methods; the print is unchanged.
- Module docstring: replace "The DOI may be the work's own or an alias (a preprint merged into
  its journal version, #95)." with "The DOI may be the work's own (`doi`) or an alias, a
  preprint merged into its journal version (`doi_alias`, #95/#102)."

### `src/biocintel/pipeline/enrich_from_lake.py`

- `_REKEY_EDGES_SQL`: append `AND old.work_id NOT IN (SELECT work_id FROM linked)` to its
  `WHERE`. The result:
  ```sql
  UPDATE bi.fact_citation_edge e SET cited_work_id = l.work_id
  FROM bi.dim_work old
  JOIN linked l ON old.openalex_id = l.oa_id OR old.doi = l.doi
    OR old.doi IN (SELECT a.doi FROM works_alt_dois a WHERE a.work_id = l.oa_id)
  WHERE e.cited_work_id = old.work_id AND old.work_id <> l.work_id
    AND old.work_id NOT IN (SELECT work_id FROM linked);
  ```
  Add a sentence to the comment above it: "Only rows `_PRUNE_WORKS_SQL` deletes are re-keyed:
  a still-linked work keeps its edges (#102)."
- `_REACH_WORKS_SQL`: `AND b.match_method IN ('doi', 'doi_alias', 'citation_file')`.
- Module docstring (code-r0-4): replace
  "Idempotent per step (scoped deletes / INSERT OR REPLACE), keyed to the linked works." with
  "Idempotent per step (scoped or whole-table deletes / INSERT OR REPLACE)."

### `src/biocintel/pipeline/build_marts.py` (DEFINITIONS and the honest view)

- `DEFINITIONS["mart_work"]["columns"]["alias_dois"]` text:
  `"Other DOIs OpenAlex lists for this work, e.g. the bioRxiv preprint a package's CITATION cites after OpenAlex merged it into the journal version. NULL when OpenAlex lists none, and always NULL for works enriched under --source lake (the lake drops locations) or from iCite alone, so NULL does not mean the work has no preprint. A DOI OpenAlex also holds as a separate work is never listed. doi is the version the metrics describe."`
- `DEFINITIONS["mart_package_work"]["columns"]` becomes `{**_PKG, **_WORK, "doi": ..., ...}`
  (an override after `_WORK`, so `mart_work.doi` keeps the shared text). The `doi` text is:
  `"The work's DOI, bare and lower-case (no https://doi.org/ prefix). It may differ from the DOI the package cites: a preprint DOI OpenAlex merged into its journal version shows the journal DOI (see mart_work.alias_dois)."`
- `match_method` text:
  `"How the link was made: doi (the package's own DOI), doi_alias (the package's DOI is a preprint OpenAlex merged into this work; doi shows the journal version), citation_file (CITATION / CITATION.cff), description_doi (a DOI in Description, sometimes a dependency's paper), title_search, manual."`
- `confidence` text:
  `"Link confidence, 0-1 (doi and doi_alias 1.0, citation_file 0.9, description_doi 0.8)."`
- `DEFINITIONS["mart_package_reach"]["description"]`: "(match_method doi or citation_file)"
  becomes "(match_method doi, doi_alias or citation_file)".
- `HONEST_VIEWS["package_pubs_confident"]`: the description becomes "Package-paper links made
  by DOI (own or merged-preprint alias) or CITATION file only (drops description_doi and
  title_search). Use for grant reporting." The SQL becomes
  `"SELECT * FROM {src} WHERE match_method IN ('doi', 'doi_alias', 'citation_file')"`.
- No mart SQL or column changes.

### `src/biocintel/pipeline/export_api.py`

- `CONFIDENT_METHODS = ("doi", "doi_alias", "citation_file")`. Its comment still points at
  `HIGH_CONFIDENCE_SQL`, which changes in step.

### `src/biocintel/schema.sql`

- The `bridge_package_pub.match_method` comment becomes
  `-- 'doi' | 'doi_alias' | 'citation_file' | 'description_doi' | 'title_search' | 'manual'`.
  There is no DDL change, so no migration.

### Frontend

- `frontend/src/lib/confidence.ts`:
  `export const HIGH_CONFIDENCE_SQL = "match_method IN ('doi', 'doi_alias', 'citation_file')";`.
  `LOW_CONFIDENCE_METHODS` is unchanged (`doi_alias` is high-confidence).
- `frontend/src/pages/Package.tsx` `METHOD_LABEL`: add
  `doi_alias: "DESCRIPTION DOI (merged preprint)",` after `doi`.

### Docs

- `CLAUDE.md`:
  - In the `match_method` list ("**must** carry `match_method` (`doi` | `citation_file` | …"),
    insert `doi_alias` after `doi`.
  - In the #95 paragraph, after "A bridge DOI then links to the journal work and is kept in
    `dim_work.alias_dois`.", add "`link_works` writes such links as `doi_alias`, and a DOI that
    is still some work's own DOI is never an alias (#102)."
- `docs/specs/95-openalex-id-drift.md`: replace the quoted `alias_dois` definition text
  ("…; empty when none. …") with the new text above, and add "(amended by #102)".

### CLI / `run()`

No new entry points or flags. `link_works.run()` and `enrich_from_lake.run()` keep their
signatures and return keys.

### Upstream API calls (verified with curl 2026-10-23; no new calls)

- `GET https://api.openalex.org/works?filter=doi:10.1101/002832&select=id,doi,locations`
  - Returns `count 1`: `W2179438025`, doi `10.1186/s13059-014-0550-8`.
  - Its location DOIs are `10.1101/002832` and `10.1186/s13059-014-0550-8`.
- `GET https://api.openalex.org/works?filter=doi:10.1101/060012&select=id,doi,locations`
  - Returns `count 1`: `W3099862724`, doi `10.1101/060012`.
  - Its only location DOI is its own.
- The 1,199-DOI and 537-alias probes above used the same `filter=doi:a|b|…` shape in batches of
  50.

### Fixtures

There is no new fixture file and no recording: the shape does not exist upstream today. The
test module builds the live-preprint record in code and adds it to the existing
`openalex_works_merged.json` result:

```python
# Hand-built (#102): no live OpenAlex preprint is also another work's location DOI today
# (2026-10-23 probe), so this record pairs HiLDA's preprint DOI with its pre-merge id.
_LIVE_PREPRINT = {
    "id": "https://openalex.org/W2921099115", "doi": "https://doi.org/10.1101/577452",
    "ids": {"openalex": "https://openalex.org/W2921099115", "doi": "https://doi.org/10.1101/577452"},
    "title": "HiLDA (preprint)", "publication_year": 2019,
    "primary_location": {"source": {"display_name": "bioRxiv"}},
    "cited_by_count": 1, "is_retracted": False, "authorships": [], "funders": [], "awards": [],
    "locations": [{"doi": "https://doi.org/10.1101/577452"}],
}
```

Add one line to the module docstring of `tests/test_sources.py` saying `_LIVE_PREPRINT` is
hand-built (#102).

## Acceptance criteria

- [ ] Live preprint + journal work, API store, `dim_package` HiLDA with
  `source_doi 'https://doi.org/10.1101/577452'`, OpenAlex serving both records:
  `link_works.run(source="api")` writes exactly `[("HiLDA", "10.1101/577452", "doi", 1.0)]`.
- [ ] The same OpenAlex fake, bridge `(HiLDA, bioc, '10.1101/577452', 'primary',
  'citation_file', 0.9)` only, stored `dim_work ('10.1101/577452', doi '10.1101/577452',
  openalex_id 'W2921099115')` and an edge `('10.1101/577452', '99')`. After
  `enrich_from_lake.run(("works",), source="api")`:
  - `dim_work` is exactly
    `[("10.1101/577452", None, "10.1101/577452", "W2921099115", None)]`, selecting
    `(work_id, pmid, doi, openalex_id, alias_dois)`;
  - the journal work is not linked;
  - the edge stays on `'10.1101/577452'`.
- [ ] Merged preprint only (existing #95 fake): `link_works.run(source="api")` writes
  `[("HiLDA", "31523512", "doi_alias", 1.0)]`. A second `run()` leaves exactly that one row.
- [ ] `_enrich_works` on a hand-built connection where `works_alt_dois` holds
  `('W2', '10.1/pre')` and `linked` holds both `W1` (`work_id '10.1/pre'`) and `W2`
  (`work_id '222'`) leaves the edge `('10.1/pre', 'C1')` on `'10.1/pre'`. This is the re-key
  guard; it fails if the `NOT IN linked` clause is removed.
- [ ] Existing tests pass unchanged, apart from the `doi_alias` expectation in
  `test_link_works_links_preprint_doi_merged_into_journal_work`:
  - `test_enrich_relinks_preprint_doi_merged_into_journal_work` (#95 merged case still
    re-keys and prunes);
  - `test_works_rekeys_doi_to_pmid_and_prunes_unlinked`;
  - `test_package_work_reconciles_alias_doi`.
- [ ] `DEFINITIONS` texts:
  - `mart_work.alias_dois` contains "NULL when OpenAlex lists none" and "--source lake".
  - `mart_package_work.doi` contains "may differ from the DOI the package cites".
  - `mart_package_work.match_method` and `.confidence` mention `doi_alias`.
  - `mart_work.doi` is still the shared `_WORK` text.
- [ ] `HONEST_VIEWS["package_pubs_confident"]`, `export_api.CONFIDENT_METHODS`,
  `_REACH_WORKS_SQL`, `frontend/src/lib/confidence.ts` `HIGH_CONFIDENCE_SQL` and the
  `link_works` / `_UNLINKED_TITLES_SQL` method lists all include `doi_alias`.
  `grep -rn "'doi', 'citation_file'" src frontend/src` returns nothing.
- [ ] `schema.sql` comment, `CLAUDE.md` and `docs/specs/95-openalex-id-drift.md` are updated
  as above. The `enrich_from_lake` docstring reads "scoped or whole-table deletes".
- [ ] `uv run pytest` and `uv run ruff check src tests` pass. `npm run build` and
  `npm run lint` pass in `frontend/`.

## Test plan

All tests are offline.

- `tests/test_sources.py`
  - `_LIVE_PREPRINT` (above) and
    `_serve_live_preprint(monkeypatch)`.
    - For any filter containing `10.1101/577452`, `31523512`, `W2921099115` or `W2970457274`,
      it returns `{"meta": {"count": 2, "next_cursor": None}, "results":
      [<merged fixture result>, _LIVE_PREPRINT], "group_by": []}` as JSON text.
    - Otherwise it returns `{"meta": {"next_cursor": None}, "results": []}`.
    - It patches `openalex.get_text`, as `_serve_merged_preprint` does.
  - `test_link_works_prefers_live_preprint_own_doi_over_alias(api_store, monkeypatch)`: the
    first criterion.
  - `test_enrich_links_live_preprint_doi_to_its_own_work(api_store, monkeypatch)`: the second
    criterion.
  - `test_link_works_links_preprint_doi_merged_into_journal_work`: expect `doi_alias`. Run
    `link_works.run` twice (re-run idempotence of the new delete list).
- `tests/test_enrich_steps.py::test_rekey_leaves_edges_of_works_still_linked`: the fourth
  criterion. It follows `test_works_rekeys_doi_to_pmid_and_prunes_unlinked`'s setup: in-memory
  `lake`/`bi`, `init_schema`, `WORKS_ALT_DOIS_DDL`, the `linked` temp table from `VALUES` and
  `lake.icite.metadata`. Insert `('W2', '10.1/pre')` into `works_alt_dois`, seed `dim_work`
  with `('10.1/pre', doi '10.1/pre', openalex_id 'W1')`, then call
  `enrich_from_lake._enrich_works(con, patents=False)`.
- `tests/test_marts.py::test_definitions_explain_alias_dois_and_doi_alias`: the DEFINITIONS
  criterion, plus `"doi_alias" in HONEST_VIEWS["package_pubs_confident"][2]`.
- Run `uv run pytest`, `uv run ruff check src tests`, then `npm run build && npm run lint`
  in `frontend/`.

## Rollout (for the PR body)

- **Data run needed.** It is not required, but the next monthly refresh rewrites HiLDA's and
  saseR's `link_works` rows as `doi_alias`. No count changes: the shape the guard targets does
  not occur today (probe above).
- **Views file.** No mart schema changes. `package_pubs_confident`'s SQL and comment change,
  and the column comments change, so regenerate the views file after the next marts deploy
  (CLAUDE.md, #51).
- **Frontend redeploy.** `HIGH_CONFIDENCE_SQL` must be live before marts carrying `doi_alias`
  publish. Otherwise ByTheNumbers drops those 2 links until the frontend deploys. Merging
  deploys the frontend, and the new SQL is harmless against today's marts, so merge before the
  next refresh.

## Risks

- **Own-DOI wins can hide a real merge.** OpenAlex might keep a stale preprint record live
  next to the journal work. The bridge DOI then links the preprint (bioRxiv metrics) and not
  the journal version. This is the conservative failure: one work, never double-counted, and
  the same thing that happens under `--source lake`.
- **Reach misses alias-keyed CITATION rows.** `_REACH_WORKS_SQL` joins bridge rows to `linked`
  by PMID or own DOI only. The 163 `citation_file` rows keyed on a merged preprint DOI get no
  reach unless the package also links the journal PMID or DOI. This comes from #92/#95 and is
  out of scope here; it should be filed as a follow-up.
- **Frontend/marts ordering.** See Rollout. The frontend reads `match_method` values it does
  not know through `METHOD_LABEL[...] ?? raw`, so an older bundle shows `doi_alias` raw rather
  than breaking.
- **Delete cost.** One `DELETE … IN (SELECT …)` per `_load_works` call, over at most about 10⁵
  works in the citations step. That takes milliseconds.
