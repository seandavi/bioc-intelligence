# Spec #95: stored OpenAlex work ids drift (preprints merged into journal versions)

Issue: https://github.com/seandavi/bioc-intelligence/issues/95. Labels: bug, backend,
data-quality. Review lenses: `code`, `data`.

## Findings (verified 2026-10-23, live OpenAlex vs a copy of the 2026-10-07 store)

- Of the 1,178 stored `dim_work.openalex_id` values, 152 no longer resolve:
  `filter=openalex_id:<W>` returns 0 results for them. OpenAlex does not redirect merged ids
  inside a filter.
- Looking each stale row's `doi` up again gives two cases:
  - **148: merged into a different work.** `filter=doi:<preprint doi>` returns the journal
    work. Its `doi` is the *journal* DOI. The requested DOI survives only in
    `locations[].doi`. By prefix: 10.1101 140, 10.21203 2, 10.12688 2, 10.64898 2,
    10.48550 1, 10.5281 1.
  - **4: same DOI, new `W…`.** The existing DOI fetch already heals these.
  - **0 deleted outright.**
- **The next refresh does not self-heal. It loses data.** `enrich_from_lake._LINKED_SQL` (and
  `sources._LINKED_KEYS_SQL`, `link_works._DOI_SQL`) join a bridge `work_id` to
  `works.pmid` or `works.doi` only. For 147 of the 148 merged works the bridge key is the
  preprint DOI, so nothing matches. `_PRUNE_WORKS_SQL` would then delete the `dim_work` row,
  and the package would keep only a NULL-metadata row in `mart_package_work`. (The other one
  relinks through an unchanged PMID.) For 92 of the 148, the journal work is already its own
  `dim_work` row because the package cites both versions. Those must collapse into one work.
- Example. HiLDA's CITATION cites `10.1101/577452`, stored as `W2921099115`. Today that DOI
  resolves to `W2970457274`, with doi `10.7717/peerj.7557` and PMID 31523512 (PeerJ). Its
  `locations` hold `doi:10.1101/577452`. `dim_package.source_doi` also carries two of the
  stale DOIs (`10.1101/577452`, `10.1101/2023.06.29.547014`), so `link_works`' `doi` rows
  break the same way.
- Orphans in the current store: 5 `bridge_work_grant` rows and 6 `fact_citation_edge` rows
  are keyed on a `work_id` that is no longer in `dim_work`. Grants are fixed here; edges are
  out of scope (see Non-goals). `bridge_work_institution` and `bridge_work_funder` are rebuilt
  whole from `dim_work.openalex_id` on every run, so they heal once `dim_work` carries the
  journal id.
- cdsci-lake's OpenAlex ingest drops the full `locations` array
  (`cdsci-lake/src/cdsci/lake/sources/openalex/ingest.py`). Alias DOIs are therefore
  available only under `--source api`. The lake's older snapshot still holds the preprints as
  their own works, so `--source lake` keeps working through the existing `doi` join.

## Goal

1. When a bridge DOI resolves to a work whose own DOI differs (preprint merged into the
   journal version, and the other merges above), link the bridge row to that work and
   enrich it with the journal `W…`, PMID and DOI. Keep the cited DOI on the work as an
   alias.
2. On re-keying, carry or rebuild everything keyed on the old spine id so nothing is
   orphaned: citation edges are re-keyed; reporter grant rows are rebuilt whole. The bridge
   row keeps the DOI the package cites. It is the provenance and is reconciled through the
   alias.
3. Every API enrich run logs how many stored OpenAlex ids no longer resolve.

## Non-goals

- No change to `bridge_package_pub` contents or `extract_citation_files`. The CITATION's DOI
  stays the bridge key.
- No alias DOIs under `--source lake`: the lake has no `locations`, and the alias table is
  empty there.
- No new column in `mart_package_work`. Only `mart_work` gains `alias_dois`.
- No cleanup of the 6 pre-existing orphan `fact_citation_edge` rows. The opt-in citations
  step rebuilds edges per linked work, and facts are append-only.
- No Crossref "is-preprint-of" lookups. No one-off backfill script: the next refresh heals
  the data.

## Design

### `src/biocintel/sources/openalex.py`

- `WORK_FIELDS`: append `,locations`. The full value becomes
  `"id,doi,ids,title,publication_year,primary_location,cited_by_count,is_retracted,authorships,funders,awards,locations"`.
  `CITING_FIELDS` is unchanged.
- Add `def bare_doi(url: str | None) -> str | None`. It returns
  `url.replace("https://doi.org/", "").lower()` if `url` is set, else `None`. Use it in
  `work_row` for the `doi` field instead of the inline expression.
- Add `def alt_doi_rows(r: dict) -> list[tuple]`, with the docstring
  `"(work_id, doi) per distinct location DOI other than the work's own doi (e.g. the bioRxiv
  preprint OpenAlex merged into its journal version)."`
  - It returns
    `[(bare_id(r["id"]), d) for d in sorted({bare_doi(l.get("doi")) for l in r.get("locations") or []} - {None, bare_doi(r.get("doi"))})]`.
  - Records without `locations`, such as citing works and the existing fixtures, yield `[]`.

### `src/biocintel/lake.py`

- Add a module constant, with a comment saying it holds other DOIs OpenAlex lists for a work
  (its locations). It is a temp table so the enrichment SQL stays source-agnostic. The lake
  drops `locations`, so it is empty under `--source lake`; `biocintel.sources` fills it:
  ```python
  WORKS_ALT_DOIS_DDL = "CREATE TEMP TABLE works_alt_dois (work_id VARCHAR, doi VARCHAR)"
  ```
- `connect_with_lake` runs `con.execute(WORKS_ALT_DOIS_DDL)` after attaching `bi`.

### `src/biocintel/sources/__init__.py`

- Import `WORKS_ALT_DOIS_DDL` from `..lake`. `connect_with_sources` executes it right after
  the `_DDL` loop.
- In `_load_works`, after the `works_awards` insert, add:
  `rows = [row for r in works.values() for row in openalex.alt_doi_rows(r)]`, then
  `con.executemany("INSERT INTO works_alt_dois VALUES (?, ?)", rows)` if `rows`. The table is
  temp, not under `lake.`, so `_insert` does not apply.
- `_LINKED_KEYS_SQL` becomes:
  ```sql
  SELECT DISTINCT w.id, w.pmid FROM lake.openalex.works w
  LEFT JOIN works_alt_dois a ON a.work_id = w.id
  JOIN bi.bridge_package_pub b
    ON b.work_id = CAST(w.pmid AS VARCHAR) OR b.work_id = w.doi OR b.work_id = a.doi
  ```
  This makes iCite fetch the journal PMID.
- `_fill_for_enrich`: run the by-`openalex_id` fetch unconditionally, not only when
  `institutions`/`funders` are in `steps`. Keep the existing query and its comment, reworded
  as "These steps read every dim_work row; it also finds stored ids that no longer resolve".
  Right after it, add:
  ```python
  stored = _column(con, "SELECT DISTINCT openalex_id FROM bi.dim_work WHERE openalex_id IS NOT NULL")
  stale = sorted(set(stored) - set(_column(con, "SELECT id FROM lake.openalex.works")))
  print(f"  openalex: {len(stale)} of {len(stored)} stored work ids no longer resolve "
        f"(merged or deleted upstream)" + (f"; e.g. {', '.join(stale[:5])}" if stale else ""))
  ```
  This needs no extra calls. An id loaded by PMID or DOI is alive, and the fetch requests
  every other id. A requested id that is absent from the results is a 404 (verified: merged
  ids return 0 results in a filter). The line prints every API run, `0 of N` included.

### `src/biocintel/pipeline/link_works.py`

`_DOI_SQL` joins the work's own DOI *or* an alias DOI. It uses `UNION ALL` of equality keys,
not `OR`, so the lake path keeps a hash join over 114M works:

```sql
INSERT INTO bi.bridge_package_pub (package_name, repo, work_id, role, match_method, confidence)
SELECT p.package_name, p.repo,
       COALESCE(CAST(w.pmid AS VARCHAR), w.doi) AS work_id,
       'primary', 'doi', 1.0
FROM bi.dim_package p
JOIN (
    SELECT pmid, doi, doi AS join_doi FROM lake.openalex.works
    UNION ALL
    SELECT w.pmid, w.doi, a.doi FROM lake.openalex.works w
    JOIN works_alt_dois a ON a.work_id = w.id
) w
  ON lower(regexp_replace(p.source_doi, '^(https?://(dx\\.)?doi\\.org/|doi:)', '', 'i')) = w.join_doi
WHERE p.source_doi IS NOT NULL;
```

Update the module docstring: one sentence saying the DOI may be the work's own DOI or an
alias (a preprint merged into its journal version).

### `src/biocintel/pipeline/enrich_from_lake.py`

- `_LINKED_SQL`: add `LEFT JOIN works_alt_dois a ON a.work_id = w.id` before the bridge join.
  Extend its condition to
  `ON b.work_id = CAST(w.pmid AS VARCHAR) OR b.work_id = w.doi OR b.work_id = a.doi`. The
  `SELECT DISTINCT` list and the `QUALIFY` are unchanged; `a.doi` is not selected. Extend the
  comment: "or a DOI OpenAlex merged into the work (alias, e.g. its bioRxiv preprint)".
- `_WORKS_SQL`: add `alias_dois` to the column list and select
  `(SELECT list(DISTINCT a.doi ORDER BY a.doi) FROM works_alt_dois a WHERE a.work_id = l.oa_id)`.
  The result is NULL when the work has none, including iCite-fallback rows with a NULL
  `oa_id`.
- `_REKEY_EDGES_SQL`: extend the join to
  `ON old.openalex_id = l.oa_id OR old.doi = l.doi OR old.doi IN (SELECT a.doi FROM works_alt_dois a WHERE a.work_id = l.oa_id)`.
  Add one sentence to the comment above it: a merged preprint row is matched by its DOI
  appearing among the journal work's aliases.
- `_enrich_grants`: replace the scoped delete with
  `DELETE FROM bi.bridge_work_grant WHERE source = 'reporter'`. Add a comment: `linked`
  covers every bridged work, so a whole rebuild equals the scoped one for live works and
  drops rows keyed on a superseded spine id.
- Update the module docstring: note that a bridge DOI may match a work through its alias DOIs
  (API only).

### `src/biocintel/schema.sql` and migration

- `dim_work`: append as the last column:
  `alias_dois VARCHAR[]  -- other DOIs OpenAlex lists for the work (e.g. a merged preprint); #95`
- `db.init_schema`: append `("alias_dois", "VARCHAR[]")` to `db._DIM_WORK_COLUMNS` (the #47
  migration list); do not add a one-off `ALTER`. The column is last in `schema.sql`, so fresh
  and migrated column order match (covered by `test_init_schema_adds_work_columns_to_old_store`).

### `src/biocintel/pipeline/build_marts.py`

- The three bridge→`dim_work` reconciliation joins (`pw`, `pkg_work` in
  `mart_grant_attribution`, `mart_package_work`) become
  `ON b.work_id = w.work_id OR b.work_id = w.doi OR b.work_id = w.pmid OR list_contains(w.alias_dois, b.work_id)`.
- In `mart_package_impact`, `pw` is `SELECT DISTINCT` and a new `impact_work` CTE
  (`SELECT DISTINCT package_name, repo, work_id FROM pw`) feeds `wm`, `citing` and `grants`.
  Alias reconciliation maps several bridge rows (preprint DOI + PMID) onto one `dim_work`
  row; without this, `SUM(citation_count)` and `median(icite_rcr)` count that work twice.
  `test_package_work_reconciles_alias_doi` asserts `total_citations` and `median_rcr`.
- `mart_work`: append `alias_dois` after `n_patent_citations`.
- `DEFINITIONS["mart_work"]["columns"]` becomes `{**_WORK, "alias_dois": ...}`, with the
  text:
  `"Other DOIs OpenAlex lists for this work, e.g. the bioRxiv preprint a package's CITATION cites after OpenAlex merged it into the journal version. NULL when OpenAlex lists none, and always NULL for works enriched under --source lake (the lake drops locations) or from iCite alone, so NULL does not mean the work has no preprint. A DOI that is another loaded OpenAlex work's own DOI is never listed; a preprint OpenAlex still keeps as its own work can be listed if this run did not load it. doi is the version the metrics describe."` (amended by #102, narrowed by #109)
  `_WORK` itself is unchanged, so `mart_package_work` is unchanged.

### `CLAUDE.md`

Replace the sentence "Live OpenAlex is newer than the lake's snapshot… (e.g. preprint DOIs
merged into their journal versions)." with two sentences:

- Live OpenAlex merges preprints into their journal versions: the preprint's `W…` 404s, and
  its DOI survives only in `locations[].doi`.
- Under `api`, those location DOIs fill a temp `works_alt_dois`. A bridge DOI then links to
  the journal work and is kept in `dim_work.alias_dois`. Each run logs how many stored ids
  no longer resolve. (#95)

### CLI / `run()`

No new entry points or flags. `link_works.run()` and `enrich_from_lake.run()` keep their
signatures. The stale-id line prints from `connect_with_sources(steps=…)`.

### Upstream API calls (verified with curl 2026-10-23)

- `GET https://api.openalex.org/works?filter=doi:10.1101/577452&select=id,doi,ids,title,publication_year,primary_location,cited_by_count,is_retracted,authorships,funders,awards,locations`
  - Returns `count: 1`, `id: https://openalex.org/W2970457274`,
    `doi: https://doi.org/10.7717/peerj.7557`, `ids.pmid: https://pubmed.ncbi.nlm.nih.gov/31523512`.
  - `locations[]` has six entries. Two carry a DOI: `doi:10.7717/peerj.7557` (PeerJ,
    publishedVersion) and `doi:10.1101/577452` (bioRxiv, acceptedVersion). The others have
    `doi: null`.
- `GET https://api.openalex.org/works?filter=openalex_id:W2921099115&select=id` returns
  `meta.count: 0`, `results: []`. A merged id is not redirected inside a filter.
  `GET /works/W2921099115` is a 404 but is not used.
- iCite and RePORTER calls are unchanged.

### Fixture to record

`tests/fixtures/api/openalex_works_merged.json`: the first URL above, recorded once with curl
and trimmed by hand to:

```json
{"meta": {"count": 1, "next_cursor": null},
 "results": [{
   "id": "https://openalex.org/W2970457274",
   "doi": "https://doi.org/10.7717/peerj.7557",
   "ids": {"openalex": "https://openalex.org/W2970457274", "doi": "https://doi.org/10.7717/peerj.7557",
           "pmid": "https://pubmed.ncbi.nlm.nih.gov/31523512"},
   "title": "HiLDA: a statistical approach to investigate differences in mutational signatures",
   "publication_year": 2019,
   "primary_location": {"source": {"display_name": "PeerJ"}},
   "cited_by_count": 6, "is_retracted": false,
   "authorships": [], "funders": [], "awards": [],
   "locations": [
     {"id": "doi:10.7717/peerj.7557", "doi": "https://doi.org/10.7717/peerj.7557", "version": "publishedVersion"},
     {"id": "doi:10.1101/577452", "doi": "https://doi.org/10.1101/577452", "version": "acceptedVersion"},
     {"id": "pmid:31523512", "doi": null, "version": "publishedVersion"}]}],
 "group_by": []}
```

Keep the recorded values (`cited_by_count` may differ on re-record; the tests below don't
assert it). Add the fixture to the "recorded … and trimmed" note at the top of
`tests/test_sources.py`, with the date 2026-10-23.

## Acceptance criteria

- [ ] `openalex.alt_doi_rows(merged)` returns `[("W2970457274", "10.1101/577452")]`, and
  `[]` for both records in `openalex_works.json` (they have no `locations`).
- [ ] `openalex.WORK_FIELDS` ends with `,locations`. `work_row` output is unchanged for the
  existing fixtures.
- [ ] `connect_with_lake` and `connect_with_sources` both create the temp table
  `works_alt_dois`. Under API, `_load_works` fills it.
- [ ] `link_works.run(source="api")` for a package with
  `source_doi = 'https://doi.org/10.1101/577452'` writes one bridge row
  `(pkg, '31523512', 'doi', 1.0)`.
- [ ] `enrich_from_lake.run(("works", "grants"), source="api")` against this store:
  - bridge `(HiLDA, bioc, '10.1101/577452', citation_file)`;
  - stale `dim_work` row `('10.1101/577452', doi '10.1101/577452', openalex_id 'W2921099115')`;
  - a `fact_citation_edge` with `cited_work_id '10.1101/577452'`;
  - a `bridge_work_grant` row `('10.1101/577452', 'X01', 'reporter')`.

  It leaves:
  - exactly one `dim_work` row, `work_id '31523512'`, with pmid `'31523512'`, doi
    `'10.7717/peerj.7557'`, openalex_id `'W2970457274'`, journal `'PeerJ'` and
    `alias_dois ['10.1101/577452']`;
  - the edge re-keyed to `'31523512'`;
  - no `bridge_work_grant` row with `work_id '10.1101/577452'`;
  - stdout containing `1 of 1 stored work ids no longer resolve` and `W2921099115`.
- [ ] The existing `test_enrich_all_steps_from_api` still passes. Its output also prints
  `1 of 1 stored work ids no longer resolve` for `W999`.
- [ ] `build_marts`: with a `dim_work` row `('31523512', pmid '31523512', doi '10.7717/peerj.7557', title 'HiLDA', alias_dois ['10.1101/577452'])`
  and bridge rows `(HiLDA, '10.1101/577452', citation_file, 0.9)` and
  `(HiLDA, '31523512', doi, 1.0)`:
  - `mart_package_work` has one HiLDA row: work_id `'31523512'`, doi `'10.7717/peerj.7557'`,
    title `'HiLDA'`, match_method `'doi'`;
  - `mart_package_impact.n_primary_pubs` for HiLDA is 1;
  - `mart_work.alias_dois` for it is `['10.1101/577452']`.
- [ ] `DESCRIBE mart_work` ends in `…, is_retracted, n_patent_citations, alias_dois`.
  `mart_package_work` columns are unchanged (the existing column-list assertion passes).
- [ ] `DEFINITIONS["mart_work"]["columns"]` has `alias_dois`, and the views-file test passes.
- [ ] `init_schema` on a store created before this change adds `dim_work.alias_dois`. It is
  idempotent.
- [ ] `uv run pytest` and `uv run ruff check src tests` pass.

## Test plan

All tests are offline and fixture-based.

- `tests/test_sources.py`
  - `test_openalex_alt_doi_rows_lists_other_location_dois`: the first criterion.
  - `test_link_works_links_preprint_doi_merged_into_journal_work(api_store, monkeypatch)`.
    Override `openalex.get_text` with a fake. For any filter (`doi:`/`pmid:`) containing
    `10.1101/577452` or `31523512` it returns `openalex_works_merged.json`; otherwise it
    returns `{"meta": {"next_cursor": null}, "results": []}`. Assert the bridge row.
  - `test_enrich_relinks_preprint_doi_merged_into_journal_work(api_store, monkeypatch, capsys)`:
    the same fake, seeded as in the enrich criterion. Assert `dim_work`, the edge, the grant
    rows and the stdout line.
  - `test_enrich_all_steps_from_api`: add the `capsys` assertion for `W999`.
- `tests/test_enrich_steps.py::test_icite_fallback_resolves_dois_missing_from_openalex`:
  the hand-built connection must now `con.execute(lake.WORKS_ALT_DOIS_DDL)` (import
  `from biocintel import lake`) before running `_LINKED_SQL`. The assertions are unchanged;
  the iCite-fallback row has `alias_dois` NULL.
- `tests/test_marts.py::test_package_work_reconciles_alias_doi`: the `build_marts` criterion.
  Also assert the `DESCRIBE mart_work` tail.
- `tests/test_views_db.py`: unchanged (it does not list `mart_work` columns); it must still
  pass, which checks that every mart column has a definition.
- Run `uv run pytest`, then `uv run ruff check src tests`.

## Rollout (for the PR body)

- **Data run needed.** The next monthly refresh (link_works → enrich_from_lake →
  build-marts) heals the store. It logs `152 of 1178 stored work ids no longer resolve` once,
  then about 0.
- **Views file.** `mart_work` gains a column, so regenerate the views file after the new
  marts deploy (CLAUDE.md, #51).
- **Expected metric shifts, all correct:**
  - About 147 works move from bioRxiv to their journal version: `is_preprint` false, plus
    the journal's PMID, RCR and grants.
  - About 92 packages that cite both versions collapse to one work, so `n_primary_pubs`
    drops.
  - The ByTheNumbers preprint share falls.

## Risks

- **Over-matching on location DOIs.** A location DOI that is not truly the same work (a
  Zenodo or F1000 version DOI, for example) would link a bridge DOI to that work. In the
  2026-10-23 probe every stale DOI matched exactly one work; no DOI hit several. We accept
  OpenAlex's merge as authoritative, as we already do for its `doi` field.
- **Lake-path planning.** `_LINKED_SQL` gains a `LEFT JOIN` to an empty temp table and a
  third `OR` term over the 114M-row works scan. The existing `OR` join already runs about
  80 s; the empty build side should keep that, but it is not re-timed here (lake runs are
  optional). `link_works` uses `UNION ALL` equality keys to stay a hash join.
- **Duplicate edges.** When a preprint row's edges are re-keyed onto a journal work that
  already had edges, `fact_citation_edge` can hold duplicate rows until the opt-in citations
  step rebuilds them. Marts count `DISTINCT citing_work_id`, so metrics are unaffected.
- **Payload.** `locations` makes each work record larger (about 16 KB for HiLDA with full
  authorships). At about 1.2k works over about 24 batch calls this is negligible.
  `cited_by` uses `CITING_FIELDS` and is unaffected.
