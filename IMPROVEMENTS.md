# Improvements: UI/UX and content review

Review of the live dashboard (<https://seandavi.github.io/bioc-intelligence/>, snapshot
2026-10-01) carried out 2026-10-06. Everything below was checked against the deployed site
(screenshots at 1280 px and 390 px, DOM and performance probes), the bundled marts (identical to
the deployed ones), the local DuckDB store, the cached VIEWS files, and a handful of read-only
cdsci-lake queries. Where a statement was not verified it is marked *(unverified)*.

The report is organised as: the short list, what works, findings per view, statistics to keep
honest, what each audience asks and how the site answers today, the consolidated backlog, and a
suggested order. The five frontend proposals reviewed earlier are folded into the backlog with
updated verdicts (section 6.1).

---

## 1. The short list

Ranked by user value per unit of work. "FE" = frontend only, data already published; "BE" = a
small pipeline/mart change first; "Lake" = needs an enrichment run against cdsci-lake.

| # | Change | Why it matters | Scope |
|---|---|---|---|
| 1 | **Explorer: show the real publication links.** The DOI column and the "Has describing DOI" filter read `mart_package_directory.source_doi`, which is set for **25** packages. The CITATION-derived links cover **961**. Join the bridge into the directory (or publish a `mart_package_work`) and show paper title, year, citations, RCR and a match-method badge in the drawer. | The site's headline claim (961 linked packages) is invisible where people look for it. | BE (one mart) + FE |
| 2 | **Fix search.** A search for `differential expression` returns zero rows ("Page 1 of 0"). Search only covers the rendered columns (name, repo, maintainer, `|`-joined biocViews, DOI), not the title, and cannot match `DifferentialExpression`. Add `description` to the directory mart, search name + title + description + biocViews with CamelCase/space normalisation, and show an explicit empty state. | Topic search is the first thing a community visitor tries. Today it fails silently. | BE (one column) + FE |
| 3 | **Download trends view.** `fact_download` holds 668,842 package-months (2009-01 to 2026-09) but no view shows a time series. Ship a yearly ecosystem mart plus a monthly per-package mart and draw: ecosystem distinct IPs per year with the 2015-10 methodology band, per-package sparklines, compare mode. | The strongest growth story the project has (1.6M distinct IPs in 2009 to 36.0M in 2025 for the software repo) is unpublished. Every audience asks for it. | BE (two marts) + FE |
| 4 | **Routing and permalinks.** The URL never changes; browser Back leaves the site; nothing is shareable. Hash routing (`#/explorer?view=RNASeq`, `#/package/limma`, `#/grant/U24CA180996`). | Prerequisite for the package profile, clickable biocViews, "cite this impact", and any link a developer or PI can paste into a document. | FE |
| 5 | **Package profile page** (`#/package/<name>`): header with the bioconductor.org link and install snippet, usage sparkline, papers with method badges, grants and declared funders, reverse-dependency count, people. | The unit every audience reasons about. Today the drawer shows title, maintainer, links and chips. | FE after 1, 3, 4 |
| 6 | **Grants: make rows useful.** Show the grant title (already in the mart, not rendered), expand the IC code (`CA` is NCI), link to RePORTER, and expand a row into a mini-report: packages with their trailing-12-month usage, papers, citations. | This is the grant-renewal use case the platform exists for. Today a row is an ID and a list of package names. | FE (join in the browser) |
| 7 | **Growth: backfill from historic VIEWS, not git tags.** `bioconductor.org/packages/<ver>/bioc/VIEWS` exists for every release (verified 1.8, 2.0, 3.0, 3.12). The release-announcements page lists all 49 releases with dates and software-package counts (15 in 1.0, 2,418 in 3.23). Diffing VIEWS across releases gives new/removed packages per release and a real `first_seen_release`. | The Growth page currently shows one point and a banner blaming git tags. The cheaper source has been there all along. | BE (loop extract over releases) + FE |
| 8 | **Parse the VIEWS fields the pipeline already downloads but ignores**: `dependsOnMe`/`importsMe`/`suggestsMe`/`linksToMe` (reverse dependencies), `dependencyCount`, `git_last_commit_date`, `Date/Publication`, `PackageStatus` (deprecated), `hasNEWS`, `vignettes`, `License`, `NeedsCompilation`. | Unlocks "is this package alive", "what depends on it", "load-bearing infrastructure", and deprecation analytics with no new network calls. | BE (DCF fields to `dim_package`) |
| 9 | **Confidence-aware impact.** Leaderboard and By-the-Numbers default to `doi` + `citation_file` links; `description_doi` (0.8) opt-in. Flag works shared by several packages (76 works appear under 176 package rows). | Today's #8-#10 by RCR are three packages sharing one DeepMind paper via a 0.8-confidence link. | FE (needs `match_method` in a mart) |
| 10 | **An About/Methods page on the site.** Definitions, sources with dates, the caveats now only in the README, how to cite the dashboard, and a correction path. | Funders and leadership will not trust numbers whose provenance lives in a GitHub README they never open. | FE (static) |

Three cross-cutting items belong in the first PR regardless: drop `maintainer_email` from the
published mart and the `mailto:` link (3,808 addresses are currently published as a Parquet file;
the people work in #23 deliberately stores none); label NIH Institutes/Centers correctly (the
"25 agencies" card counts ICs of one agency); and publish a small DuckDB file of **views over the marts** plus a **Data** page, so the
whole public API is one `ATTACH` line with the data dictionary inside the database (section 8.2).
That item would rank near the top of this list on value per hour.

---

## 2. What already works

- The zero-backend model holds up: 830 KB over 8 requests plus the DuckDB-WASM runtime from
  jsDelivr; warm DOMContentLoaded in 435 ms; every view recomputes from Parquet in the browser.
- Honest empty states and the snapshot stamp in the header. The "pending" pattern is right.
- Info markers on every metric, with correct aggregation choices (median RCR with p10-p90, summed
  citations). The tooltips read well.
- Consistent visual language: stat cards, bordered white panels, one accent colour, tabular
  numerals. It looks like one product.
- The grant CSV export exists and exports the filtered rows.
- Precision-first linkage with method and confidence stored on every edge, even if the UI does not
  yet expose them.

---

## 3. Findings by view (verified on the live site)

### 3.1 Shell (header, nav, footer)

- No routing. Six views, no URLs, no Back, no deep links. Reload returns to By the Numbers.
- No landing narrative. A first-time visitor sees stat cards with no sentence about what the site
  is, who it serves, or where to start. One strip of three audience entry points ("I am writing a
  grant", "I maintain a package", "I am choosing a tool") would fix this.
- Footer copy is developer-facing ("Zero-backend SPA, DuckDB-WASM over prebuilt Parquet marts").
  Fine as a footer; the audiences need plain language elsewhere.
- No About/Methods page, no "how to cite", no license statement, no contact or correction path.
- `index.html` has a description meta tag but no Open Graph/Twitter tags, so shared links render
  without a preview *(unverified in a client, inferred from the markup)*. No GA4 tag; the usual
  property for this account is `G-KLLV1GCF4E`.
- Repo naming is inconsistent: charts use `bioc`/`data-annotation`, tables use Software/Annotation.

### 3.2 By the Numbers

- "Packages per repository" appears here and again on Growth. It carries little information twice.
- "Top biocViews terms" is topped by `AnnotationData` and `Software`, which are the root terms of
  the taxonomy and apply to whole repositories. Exclude the four roots (Software, AnnotationData,
  ExperimentData, Workflow) or use the hierarchy.
- "NIH grants 613 / 25 agencies": these are Institutes and Centers of one agency. Label as ICs.
- "Distinct-IP downloads 259.6M all-time" sums monthly distinct IPs over 17 years and two
  methodology eras. The tooltip says so, but the headline invites misreading. The defensible
  headline is the trailing-12-month figure (57.0M distinct IP-months) with "all-time" secondary.
- "Citations by publication year" is a cohort chart (citations received by papers published in
  year Y), dominated by 2014 (DESeq2) and 2004 (MUSCLE). It reads as a trend but is confounded by
  paper age. Either retitle ("Citations to describing papers, by the paper's publication year")
  and pair it with "Describing papers published per year", or replace with citations accrued per
  year, which needs per-year counts the lake does not currently carry.
- "Top packages by median RCR" shows `AlphaMissenseR`, `AlphaMissense.v2023.hg19` and `.hg38` at
  the same 165.7: one DeepMind *Science* paper linked to three packages (see 4.2). `muscle` at
  786 is the MUSCLE algorithm paper (Edgar 2004), which the R wrapper's CITATION asks users to
  cite. Both are correct extractions and misleading rankings.
- Nothing on the page says "last 12 months". Every number is cumulative.

### 3.3 Explorer

- **DOI column is empty for almost every row** (25 of 3,810 have `source_doi`), while 961
  packages have CITATION-derived links in `bridge_package_pub`. The filter "Has describing DOI"
  therefore returns 25 packages on a site whose Impact page counts 961. This is the single most
  visible content bug.
- **Search misses titles and cannot match biocViews terms written as words.** Verified:
  `differential expression` returns 0 rows; the table shows "Page 1 of 0" and no message.
  `title` is in the mart but is not a table column, so TanStack's global filter never sees it;
  `description` is not in the mart at all.
- Drawer content is thin: title, maintainer (as a `mailto:`), DESCRIPTION URLs, chips. Missing:
  link to the package's bioconductor.org page, install snippet, downloads, papers, grants,
  dependencies, people. biocViews chips are not clickable.
- Opening the drawer squeezes the table: biocViews chips wrap to three lines and the DOI column
  leaves the viewport (confirmed at 1280 px).
- Maintainer column shows 547 packages under "Bioconductor Package Maintainer" and 44 under
  "Biocore Package Maintainer"; the facet and the "1,671 maintainers" card treat these as people.
- Pagination has no page-size control and no "showing 1-50 of 3,810". Sortable headers give no
  affordance until clicked.
- `maintainer_email` is published for 3,808 packages and rendered as `mailto:`. Addresses are in
  DESCRIPTION files, but publishing them as one downloadable Parquet with no rate limit is a
  different thing. Drop the column from the mart.

### 3.4 biocViews

- Flat ranking only. Organism terms (`Homo_sapiens`), technology terms (`AffymetrixChip`) and
  root terms (`Software`) are ranked together. The chart and the list are the same data twice.
- Terms are not clickable; there is no path from a term to its packages.
- The true hierarchy is published: `bioconductor.org/packages/json/3.23/tree.json` (326 KB; four
  roots; Software has 179 nodes, depth 3; each leaf carries `packageList`). A treemap or
  collapsible tree is unblocked and cheap.

### 3.5 Impact leaderboard

- Default sort (median RCR) surfaces the attribution problems in 3.2 at positions 4 and 8-10.
- Downloads column is the all-time sum. No trailing-12-month column, no download preset button,
  no era note.
- Download rankings are dominated by infrastructure (BiocVersion, BiocGenerics, S4Vectors,
  IRanges) that everything depends on. 258 software packages carry the `Infrastructure` term;
  offer "exclude Infrastructure" and a reverse-dependency count so the dominance is explained
  rather than hidden.
- No biocViews facet, so "top single-cell packages" is not answerable.
- Rows are not clickable; there is no way to get from a rank to the evidence behind it.
- `edgeR` shows 1 publication and 441 citations because its current CITATION lists only the 2025
  v4 paper. Its 2010 and 2012 papers appear in the citation pages of earlier releases (see 4.1).

### 3.6 Grants

- Grant title is selected by the SQL and never rendered. The table is ID, IC code, count, names.
- IC codes are not expanded (`CA`, `GM`, `HG`); a 27-entry map fixes this.
- Grant IDs do not link to RePORTER (`https://reporter.nih.gov/project-details/<core number>`
  pattern *(unverified)*; the core project number is the join key the pipeline already uses).
- Package names are plain text, not links. No per-grant rollup of usage or citations even though
  every number needed is in `mart_package_impact`.
- Four grants in the mart have no `dim_grant` row (null title and agency).
- `U41HG004059` is titled "Project-002", a RePORTER sub-project artifact. Prefer the parent
  award's title when `subproject_id` is set.
- Only NIH. By senior-author country, the linked papers come from the US (340), Germany (100),
  the UK (92), Australia (70), Switzerland (48), Spain (39), Italy (34), China (32), France (29)
  and Belgium (21), so a large share of the ecosystem's funding is invisible here. See 6.4 for
  the two feasible non-NIH paths.

### 3.7 Growth

- One data point, a third copy of the repository bar chart, and a banner that says history waits
  on git tags. It does not: historic VIEWS and the release-announcements table exist (section 1,
  item 7), and `fact_download` already provides usage by year since 2009.
- Nothing about maintainers, new/deprecated packages, or usage over time.

### 3.8 Mobile (390 px)

- Nav wraps to three lines plus the snapshot line; it takes 140 px before content. A compact
  select or a scrollable tab strip would do.
- Explorer stacks the facet column above the table, so the table starts a full screen down. Tables
  scroll horizontally, which is acceptable.
- Stat cards and charts behave well.

### 3.9 Accessibility (DOM probe)

- Sorting is on `<th onClick>` with no `aria-sort` and no button, so it is not keyboard-operable.
- Info tooltips are hover-only (`group-hover`) and the "?" is not focusable, so keyboard and touch
  users never see the definitions the site is proud of.
- No skip link. One search input without a label.
- Colour contrast: secondary text in `slate-400` on white is about 2.9:1 (AA requires 4.5:1 for
  body text); "pending" values in `slate-300` are about 1.5:1. Chip text in `bioc-700` on
  `bioc-50` passes.

### 3.10 Performance

- 403 KB JavaScript bundle (Vega + Vega-Lite + React), 274 KB directory mart, 91 KB impact mart.
  DuckDB-WASM runtime loads in a worker from jsDelivr (not in the main-thread resource list).
  Cold start shows "Booting DuckDB-WASM…". Acceptable for the audience; the only thing to watch
  is bundle growth when monthly download series ship (see 6.2 for the range-read option).
- Each view re-runs its SQL on every mount. Results are small; a tiny cache keyed by SQL would
  make tab switching feel instant.

---

## 4. Content and statistics to keep honest

### 4.1 What "linked publication" means

The links are **the papers a package asks users to cite today** (CITATION on the `devel` branch,
plus DESCRIPTION DOIs). Three consequences, all verified:

- **CITATION rotates.** edgeR's CITATION lists only the 2025 v4 paper; the release 3.16 citation
  page listed three DOIs including the 2010 *Bioinformatics* paper. Long-lived packages are
  under-counted. Fix: union CITATION DOIs across every past release's citation page
  (`bioconductor.org/packages/<ver>/<repo>/citations/<pkg>/citation.html`, verified 200 for 3.10
  and 3.16; the 3.0 page carries no DOIs). This is a bounded, high-precision recall fix, unlike
  name-based title search.
- **Some cited papers describe the method or data, not the package.** `muscle` cites Edgar 2004;
  the two AlphaMissense annotation packages cite the DeepMind *Science* paper (RCR 165.7) with
  method `citation_file`; `AlphaMissenseR` reaches the same paper via `description_doi` while its
  own paper (2024, *Bioinformatics Advances*) has no citations yet. This is faithful extraction.
  The UI should say "papers the package asks you to cite" and badge the method.
- **Shared works double-count in sums.** 76 works are linked to more than one package (176
  package rows). Package-level sums are fine; ecosystem-level sums must be over distinct works
  (the By-the-Numbers cards already query `mart_work`, so they are correct; a per-package table
  summed by a reader is not).

### 4.2 Coverage facts worth stating on the site

- 955 linked works; 812 have an iCite row; 775 have an RCR; 94 are preprints (bioRxiv/medRxiv) and
  will never have one. The median RCR is over 775 works, not 955.
- 821 packages link one paper, 140 link two or more.
- Linked packages by repository: software 882 of 2,418; experiment data 62 of 436; annotation 10
  of 928; workflows 7 of 28.

### 4.3 Downloads

- Distinct IPs per month, summed, is a usage proxy. One IP active in 12 months counts 12 times. Use
  trailing-12-month totals for headlines and ranks, keep all-time as context, and never draw a
  line across 2015-10 without the band.
- Concentration: in the software repo the top 74 packages account for half of trailing-12-month
  distinct IPs and 1,699 packages for 90%. 176 software packages average under 100 distinct IPs a
  month and 16 under 10. Say this; it is the leadership question.
- "Fastest growing" by raw ratio is dominated by newly split infrastructure (`Seqinfo` went from
  15k to 520k when it was factored out of GenomeInfoDb). Any "trending" list needs a minimum
  history and an infrastructure exclusion.

### 4.4 Grants and money

- The mart direction is "grants acknowledged by the package's describing paper", not "grants whose
  research used the package". The second (the bigger funder story) needs `fact_citation_edge`,
  which has 0 rows until the opt-in references scan runs.
- RePORTER `total_cost` over the 609 linked core projects (parent awards, all fiscal years) is
  $7.44B. That is the size of the portfolio that acknowledged a Bioconductor paper, not money
  spent on Bioconductor. If shown at all, frame it exactly that way.
- OpenAlex `grants[]` is empty for all 955 linked works and for a lake-wide sample (0 of 769
  *Bioinformatics* 2021 works), so the non-NIH funder path through OpenAlex is closed until the
  lake carries it. Note for upstream.

### 4.5 Labels

- "agencies" are NIH Institutes/Centers. "Maintainers" includes two shared mailbox identities
  covering 591 packages. "Describing paper" should read "paper the package asks you to cite".
- Preprint versus published version of the same paper is not de-duplicated *(not measured)*.

---

## 5. What each audience asks, and how the site answers today

Legend for "Data": **ready** = in published marts; **store** = in the DuckDB store, needs a mart;
**source** = in a source the pipeline already fetches, needs parsing; **lake** = needs an
enrichment run; **blocked** = needs the opt-in cited-by scan or a new source.

### 5.1 Funders and program officers

| Question | Today | What answers it | Data |
|---|---|---|---|
| What did award X produce, and is it used? | Package names per grant, CSV | Grant page: packages with trailing-12-mo usage, papers, citations, RCR; RePORTER link; printable/PNG | ready (join in FE) |
| Which of my Institute's awards touch this ecosystem? | Filter by IC code | IC rollup view: awards, packages, usage, papers by IC with names | ready |
| Are the impact numbers defensible? | Median RCR, tooltips | Confidence filter (DOI/CITATION only), method badges, NIH percentile (238 of 812 iCite works in the top decile, 86 in the top 1%), link to source record | ready + store (`nih_percentile` is in iCite) |
| Translational signals? | None | iCite APT (340 works at or above 0.5), clinical citations (1 today), patent citations (209 works cited by 3,239 patents, Reliance on Science) | lake |
| Who else funds this work? | None | Declared funders from Authors@R (`mart_package_funder`, lands at next refresh); senior-author country mix | store (next refresh) |
| How much NIH-funded research *used* Bioconductor? | None | Citing works joined to RePORTER publink | blocked (`fact_citation_edge`) |
| Can I put this in a report? | Grants CSV | Permalinks, chart PNG/SVG export (Vega actions menu), "copy summary" text, methods page to cite | FE |

### 5.2 Community (analysts, students, people choosing a tool)

| Question | Today | What answers it | Data |
|---|---|---|---|
| Which package does X? | Search by name/maintainer/term; topic search fails | Search over title + description + biocViews with word/CamelCase normalisation; clickable terms; hierarchy browser | store (`description`) + source (`tree.json`) |
| Is it alive and trustworthy? | Nothing | Last commit date, deprecation flag, NEWS/vignette presence, reverse dependencies, usage sparkline, linked paper | source (VIEWS fields) + ready |
| What is popular in my area? | Global leaderboard | biocViews facet on the leaderboard; per-term top-10 on the term page | ready |
| What is new this release? | Nothing | New/removed per release from historic VIEWS | source |
| How do I install it and read the docs? | DESCRIPTION URL only | bioconductor.org link, `BiocManager::install()` snippet, vignette titles | ready + source |

### 5.3 Package developers

| Question | Today | What answers it | Data |
|---|---|---|---|
| How is my package doing over time? | All-time distinct IP sum | Monthly distinct-IP series with era band, trailing-12-mo, rank and percentile within repo, compare with peers | store (`fact_download`) |
| Who depends on me? | Nothing | Reverse-dependency list and count | source (`dependsOnMe`, `importsMe`) |
| Is my paper linked correctly? | Only if `source_doi` is set | Papers list with method and confidence; "how to fix: add a DOI to CITATION"; correction path (manual override table) | store |
| Does the site see my funding? | No | Declared funders and matched NIH grants on the profile | store (next refresh) |
| Can I cite this in a biosketch or README? | No | Permalink; copyable one-line summary; optional static badge JSON per package for shields.io endpoint badges | FE (+ build step for badges) |

bioconductor.org already offers a per-package download chart and a downloads badge (both
verified live). The differentiator here is the cross-package context (percentile, peers,
citations, grants), not another download chart.

### 5.4 Bioconductor leadership (core team, boards, renewal writers)

| Question | Today | What answers it | Data |
|---|---|---|---|
| How has the project grown? | One release | Packages per release since 2002 (49 releases), new/removed per release, usage per year since 2009 | source + store |
| Who maintains it, and how concentrated is that? | Count of maintainer strings | Packages per person (`mart_person`), share maintained by the core mailbox (591 packages), distribution of packages per maintainer | store (next refresh) |
| What is the long tail? | Nothing | Distribution of trailing-12-mo usage; count under thresholds; deprecated packages per release | store + source |
| What is load-bearing? | Nothing | Reverse-dependency fan-in; dependency depth; "infrastructure" share of downloads | source |
| Where is the community? | Nothing | Senior-author country and institution of linked papers (1,214 RORs across 940 works via OpenAlex authorships) | lake |
| What is the publication record? | Cohort chart, median RCR | Papers per year, journal mix, preprint share, RCR distribution, top-decile share, zero retractions | ready + store |
| Which funders underpin the ecosystem? | NIH ICs | IC rollup; declared funders; the $7.44B portfolio figure framed as "awards that acknowledged a Bioconductor paper" | ready + store + lake |
| Can we drop figures into the renewal? | CSV | PNG/SVG export, permalinks, a methods page to cite | FE |

---

## 6. Consolidated backlog

### 6.1 The five earlier proposals, updated

| # | Proposal | Verdict | Notes |
|---|---|---|---|
| 2 | Slide-out metrics grid, link anchors, active row | **Ready** | `mart_package_impact` already has downloads, citations, median RCR and grant counts. Add the trailing-12-month figures too; they are in the mart and unused. |
| 3 | Table occlusion when the drawer opens | **Ready** | Confirmed at 1280 px. Hide the DOI column first (and replace it with a "Papers" count once item 1 of section 1 lands), keep Package and Repo pinned. |
| 5 | CSV export on Explorer and Impact | **Ready** | `frontend/src/lib/csv.ts` exists; pass the filtered rows. |
| 4 | Clickable biocViews pills | **Ready once routing exists** | `Chip` is defined twice (`components/ui.tsx`, `pages/Explorer.tsx`). Filter state belongs in the URL hash. |
| 1 | Full-page package profile | **Mostly unblocked** | See below. |

Item 1 dependencies, re-checked:

- **Routing:** none today. Hash routing suits GitHub Pages; a `hashchange` listener and a small
  parser is enough for six views and a few parameters. `react-router` is optional.
- **Ecosystem fit (Depends/Imports/Suggests and reverse deps):** the cached VIEWS files carry
  `Depends`, `Imports`, `Suggests`, `LinkingTo`, `dependsOnMe`, `importsMe`, `suggestsMe`,
  `linksToMe`, `dependencyCount`. The DCF parser already reads the file; this is a column
  addition, not a new source.
- **Citation velocity:** still blocked on `fact_citation_edge` (0 rows). iCite's
  `citations_per_year` and `expected_citations_per_year` are a usable proxy per paper until then.
- **Usage sparkline:** needs the monthly mart (6.2).
- **People and declared funders:** marts exist in code since #23/#28; they appear in
  `data/marts` and `public/data` after the next refresh run, and `frontend/src/db/duckdb.ts` must
  register them.

### 6.2 Backend: small mart changes that unblock most of the frontend work

| Mart change | Unlocks | Size note |
|---|---|---|
| `mart_package_work` (package, repo, work_id, doi, pmid, title, year, journal, citation_count, rcr, nih_percentile, match_method, confidence) | Explorer links, profile papers list, confidence filter | ~1.2k rows |
| `mart_package_directory`: add `description`, `bioc_url`, `n_reverse_deps`, `n_deps`, `git_last_commit_date`, `package_status`, `has_news`, `n_vignettes`, `license`; drop `maintainer_email` | Search, health signals, drawer links | description adds a few hundred KB compressed |
| `mart_ecosystem_downloads_yearly` (year, repo, era, distinct_ips, downloads, n_packages) | Growth and By-the-Numbers trend charts | tiny |
| `mart_package_downloads_monthly` (package, repo, year, month, distinct_ips, downloads, era), sorted by package with one row group per package | Profile sparkline, trends view, compare | ~670k rows; register by URL and let DuckDB-WASM range-read row groups instead of bundling the whole file in `boot()` |
| `mart_release_history` (release, date, repo, n_packages, n_new, n_removed) from historic VIEWS plus the release-announcements dates | Growth | 49 rows per repo |
| `mart_grant_attribution`: add `ic_name`, parent-award title, fiscal-year span; keep `total_cost` out unless framed | Grants page | small |
| `mart_work`: add `title`, `nih_percentile`, `apt`, `is_clinical`, `is_preprint`, later `n_patent_citations` | Impact honesty, translational signals | small |
| `mart_person`, `mart_package_person`, `mart_package_funder` | People view, profile people and funders | exist; need the refresh and FE registration |
| Dedicated `--release` loop in `extract_packages` (historic VIEWS) and `extract_citations` (historic citation pages) | Growth history; recall for rotated CITATIONs | one-time backfill, then per release |

### 6.3 New and reworked views

- **Package profile** (`#/package/<name>`): header (title, repo, release, maintainer, bioconductor.org
  link, install snippet), usage (monthly sparkline with era band, trailing-12-mo, percentile within
  repo), papers (method badge, year, citations, RCR, percentile), funding (NIH grants with RePORTER
  links, declared funders), ecosystem (reverse-dependency count and list, dependencies, biocViews
  chips linking to the filtered explorer), people (roles, ORCID), "cite this" (copy a one-sentence
  summary with the snapshot date; PNG of the sparkline).
- **Trends**: ecosystem distinct IPs per year by repo with the methodology band; "packages with any
  downloads" per year; per-package compare (up to five, log scale option); a "trending" list with
  a 24-month minimum history and infrastructure excluded.
- **Grants**: titles and IC names in the table; expandable rows with the mini-report; an IC rollup
  chart; a confidence toggle; RePORTER links.
- **biocViews**: treemap or collapsible tree from `tree.json`; term page with top packages by usage
  and by RCR; root terms excluded from the flat ranking.
- **Impact**: trailing-12-mo column and preset; infrastructure toggle; biocViews facet; confidence
  toggle; row click to profile; shared-work indicator.
- **Growth**: packages per release since 2002, new/removed per release, usage per year, maintainer
  distribution, long-tail histogram, deprecated per release.
- **People**: packages per person, ORCID coverage, the core-mailbox share. Built on marts that ship
  at the next refresh.
- **About/Methods**: sources and dates, definitions (RCR, distinct IPs, match methods, eras), the
  README caveats, how to cite, how to request a correction, the data-flow figure.

### 6.4 Deeper enrichment (lake runs, each opt-in and deliberate)

- **Cited-by edges** (`enrich_from_lake --steps citations`, 1.29B-row scan): lights up citing works,
  citation velocity, and the "NIH-funded research that used Bioconductor" direction.
- **Historic CITATION union** (bounded recall fix, no lake needed): see 4.1.
- **Translational signals**: iCite `apt`, `is_clinical`, `nih_percentile` (already in the table the
  pipeline reads); Reliance on Science patent citations by OpenAlex ID (209 works, 3,239 patents).
- **Institutions and countries** via `openalex.works_authorships` and `openalex.institutions`
  (1,214 RORs over 940 works). This satisfies the spec's best-effort institution attribution
  without parsing maintainers.
- **Retraction check**: zero today across both OpenAlex and Retraction Watch; cheap to keep as a
  standing integrity statement.
- **Non-NIH funders**: Authors@R `fnd` (ships next refresh). OpenAlex `grants[]` is empty
  lake-wide; raise upstream. Crossref funder metadata is not in the lake.
- **Full-text mentions and the judge**: unchanged from the roadmap; still the largest recall gain
  and the largest cost.

### 6.5 Trust and polish

- Accessibility basics: `<button>` inside sortable headers with `aria-sort`; focusable info
  markers with `aria-describedby`; a skip link; secondary text at `slate-500` or darker; a
  visible empty state on every table.
- Consistent repo labels everywhere; the four root biocViews excluded from term rankings; IC names.
- Open Graph tags and a favicon; the GA4 property used across this account.
- Vega `actions` enabled for export (one option in `VegaChart`), with a consistent chart title
  that includes the snapshot date so exported figures are self-describing.
- A small query-result cache keyed by SQL so tab switches do not re-run identical queries.
- Deduplicate `Chip`/`RepoBadge` and the repeated facet sidebar into `components/ui.tsx`.

---

## 7. Suggested order

1. **Honesty and search PR (BE + FE).** `mart_package_work`; `description` and the VIEWS health
   fields into the directory mart; drop `maintainer_email`; Explorer uses the bridge for links and
   searches title + description + normalised biocViews; empty state; IC labels; root terms
   excluded; trailing-12-mo headline; the published DuckDB views file and the Data page (8.2,
   tier 1a). Items 2, 3 and 5 from 6.1 ride along.
2. **Routing PR (FE).** Hash routes for all views and filter state; clickable chips (item 4);
   row click targets reserved for the profile.
3. **Downloads PR (BE + FE).** Yearly and monthly download marts (range-read registration); Trends
   view; sparkline component; trailing-12-mo column and preset on Impact with the infrastructure
   toggle.
4. **Profile PR (FE).** The package page, composed from the marts above; "cite this" copy and
   PNG export; About/Methods page in the same PR since the profile links to definitions.
5. **Grants PR (FE, small BE).** Titles, IC names, RePORTER links, expandable mini-report, IC
   rollup; `ic_name` and parent titles in the mart.
6. **Growth PR (BE + FE).** Historic VIEWS loop, `mart_release_history`, historic CITATION union;
   Growth view rebuilt; People view once the refresh has published the people marts.
7. **Enrichment runs (Lake), each its own PR:** iCite percentile/APT and patents into `mart_work`;
   authorship institutions and countries; then the cited-by scan when a full refresh is scheduled.
8. **Static API PR (FE build step).** Per-package and per-grant JSON, badge JSON, CSV mirrors,
   `datapackage.json` and Dataset JSON-LD, all rendered from the marts during the Pages deploy
   (8.2, tier 1b). A server is not in this list; section 8.3 names the triggers that would add one.

Each step leaves the site more honest than before it; none depends on the judge or on the
1.29B-row scan.

---

## 8. Programmatic access: is a Hono backend worth it?

People are asking for the data. The question is whether that calls for a frontend/backend split
with an API server (Hono was the candidate), or for something smaller. Re-priced on the merits,
not on the spec's "zero-backend" decision.

### 8.1 What exists today (verified 2026-10-06)

The marts on GitHub Pages already behave like a read-only API:

- Response headers on `data/mart_package_impact.parquet`: `accept-ranges: bytes`,
  `access-control-allow-origin: *`, `cache-control: max-age=600`. A `Range: bytes=0-1023`
  request returns 206. So any Parquet reader can range-read the files, and browser apps on other
  origins (Observable, Quarto, a lab's own dashboard) can fetch them.
- DuckDB queried the live URL in 0.3 s with no download step:

```sql
SELECT package_name, median_rcr, total_citations
FROM 'https://seandavi.github.io/bioc-intelligence/data/mart_package_impact.parquet'
WHERE repo = 'bioc' ORDER BY median_rcr DESC NULLS LAST LIMIT 3;
-- DESeq2 2562.18 97164 | limma 1099.84 41828 | dada2 1078.98 34738
```

```r
library(duckdb); con <- dbConnect(duckdb())
dbExecute(con, "INSTALL httpfs; LOAD httpfs")
dbGetQuery(con, "SELECT * FROM 'https://seandavi.github.io/bioc-intelligence/data/mart_package_impact.parquet' WHERE package_name = 'limma'")
```

```python
import duckdb
duckdb.sql("INSTALL httpfs; LOAD httpfs")
duckdb.sql("SELECT * FROM 'https://seandavi.github.io/bioc-intelligence/data/mart_package_impact.parquet' WHERE package_name = 'limma'").show()
```

Nobody knows this because the site never says it. The spec (section 2) always intended the
Parquet marts for "the WASM frontend and any external consumers"; the missing piece is the
documentation and a few friendlier shapes, not a server. The audience is also overwhelmingly R
users, for whom a Parquet URL plus `duckdb` is more natural than a REST endpoint.

### 8.2 Recommendation: a published DuckDB views file first, then static JSON

**Tier 1a: publish a DuckDB file of views over the marts, and a Data page (first PR, hours).**

The file holds no data: one view per mart, each reading the published Parquet URL, plus
`COMMENT ON` for every view and column. The data dictionary therefore ships inside the database
and is introspectable (`duckdb_views()`, `duckdb_columns()`), and the methodology is readable as
SQL (`SELECT sql FROM duckdb_views()`). Using it is one line:

```sql
ATTACH 'https://seandavi.github.io/bioc-intelligence/data/bioc-intelligence.duckdb' AS bi (READ_ONLY);
SELECT * FROM bi.package_impact WHERE package_name = 'limma';
```

```r
dbExecute(con, "ATTACH 'https://seandavi.github.io/bioc-intelligence/data/bioc-intelligence.duckdb' AS bi (READ_ONLY)")
dbGetQuery(con, "SELECT * FROM bi.package_impact WHERE package_name = 'limma'")
# dbplyr users: tbl(con, I("bi.package_impact"))
```

Prototyped and verified 2026-10-06 against the live marts:

- The views-only file is 274 KB (one storage block). Written with `STORAGE_VERSION 'v1.0.0'`, it
  attaches read-only over HTTP from DuckDB 1.5.4 **and** DuckDB 1.0.0; the first query through a
  view fetched the Pages Parquet in about 0.05 s. Views that reference sibling views work.
  `COMMENT ON VIEW` and `COMMENT ON COLUMN` round-trip. DuckDB 1.5.4 autoloads `httpfs` for the
  `ATTACH` without an explicit `LOAD`.
- It depends on Range requests, which GitHub Pages supports (206 verified). A server without
  Range support fails on DuckDB 1.0 clients.

Gotchas found in the prototype, all cheap to design around:

1. **Table macros must inline `read_parquet(url)`.** A macro that referred to a sibling view by
   bare name failed once the file was attached under a client-chosen alias ("Did you mean
   `bi.package_impact_ranked`"). Views resolve siblings fine; macros do not.
2. **Catalog-qualified macro calls need a recent client.** `bi.package('DESeq2')` worked on 1.5.4
   and failed on 1.0.0. Views are the portable contract; macros are sugar.
3. **Absolute URLs are baked in**, so the file is regenerated per snapshot location
   (`data/latest/` and `data/2026-10-01/` each get their own).
4. **Write with `STORAGE_VERSION 'v1.0.0'`** or older clients cannot open it. The R `duckdb`
   package often trails the C++ release, so this matters for the main audience.
5. Not tested here: the R `duckdb` client (not installed on this host) and `ATTACH` of a remote
   `.duckdb` from DuckDB-WASM. The SPA can keep registering Parquet buffers either way.

What goes in the file: one plain view per mart; "honest default" views that encode the
methodology (`package_pubs_confident` limited to `doi` and `citation_file` links,
`downloads_modern_era`, `ecosystem_yearly`, `package_impact_ranked` with rank within repo);
`grant_report(grant_id)` and `package(name)` macros for recent clients; the snapshot date and the
InfoDot definitions as comments. Generate it in `build_marts` (with a `--public-base` URL) or in
`sync-marts.sh`, so the SPA, the file and the marts can never disagree. One seam, three readers.

The **Data** page then shows the `ATTACH` line first, the Parquet URLs second (section 8.1), a
CSV download per mart third, the column dictionary rendered from the same comments, a "How to
cite" block, and the README caveats. Add `datapackage.json` (Frictionless) generated from the
same comments and a schema.org `Dataset` JSON-LD block in `index.html` for Google Dataset Search.

**Tier 1b: shape the data for people who do not want SQL (one PR, days).** Rendered during the
Pages deploy from the same marts, never committed to git:

- `api/v1/package/<name>.json`: the profile payload (impact, papers, grants, funders, people,
  monthly usage). `api/v1/grant/<id>.json` likewise. `api/v1/index.json` lists them.
- `badges/<name>.json` in shields.io endpoint format, so a README can show usage or citation
  badges without any server.
- Dated snapshot directories (or R2 per the roadmap) so a number cited in a grant can be
  reproduced: `data/2026-10-01/…` alongside `data/latest/…`. Optionally a Zenodo DOI per
  snapshot via the GitHub release integration, which makes the dataset itself citable.
- An R accessor: three documented lines today; later a small package, or a function in
  BiocPkgTools, which already wraps the package list and download stats for this audience.

Size is not a concern: 3,810 package JSONs at 10 to 20 KB each is roughly 40 to 80 MB, inside
GitHub Pages' documented limits (1 GB site, 100 GB per month soft bandwidth; *unverified today*).
Versioning stays the rule the project already has: mart columns are additive, never renamed.

### 8.3 When a real server becomes worth it

Add one when a concrete trigger fires, not before:

| Trigger | Why static cannot do it |
|---|---|
| Write paths: user-submitted link corrections, saved reports, accounts | Needs state and auth. (Corrections can start as a GitHub issue template feeding the `manual` override table.) |
| Ad hoc SQL for people who cannot run DuckDB, at a volume that needs rate limits | Static files cannot throttle or log per client. |
| Request-level telemetry on who uses the data | Pages has no access logs. A Cloudflare proxy in front of Pages, or serving from R2, gives analytics with no application code and is the cheaper fix. |
| Remote MCP or agent access with auth and logging | A local stdio MCP server over the Parquet URLs needs no backend; a remote one does. |
| Data fresher than monthly | Not applicable; the sources are monthly. |

If a trigger fires, keep **one seam**: the server is a thin read-only projection of the same
marts, generated from the same `build_marts` definitions, so the SPA, the static JSON and the
server can never disagree.

| Option | Fit | Cost |
|---|---|---|
| **Hono on Cloudflare Workers** | Zero ops, same provider as R2 and the Clef models. Workers cannot run DuckDB, so the marts would be loaded into D1 (SQLite) at each refresh or read with a pure-JS Parquet reader. | A second data representation to keep in sync; a new runtime in a project whose backend is Python. |
| **FastAPI + DuckDB** (the default stack in this account) | Reads the same Parquet files directly; no second representation. | Needs a host. onclappc02 is tailnet-only, so public exposure means a tunnel or a small cloud VM, plus TLS, uptime and schema stability obligations. |
| **DuckDB views file + static JSON on Pages** (8.2) | Covers every read-only question seen so far; SQL users get names, docs and methodology in one `ATTACH`. | None beyond a build step. |

Publishing an HTTP API is a promise: people build on it and uptime and schema stability become
your problem. Static files on Pages inherit GitHub's uptime for free. The lazy path is also the
robust one here.

### 8.4 One thing to collect first

Write down the actual questions the few people asked, three to five of them, and sort each into:
answered by a Parquet URL plus a snippet; needs a per-entity JSON; needs a server. If none lands
in the third column, the Data page is the whole answer. If any does, that question is the design
brief for the server, and this section has the design.

---

## 9. Verification notes

- Live site viewed 2026-10-06 at 1280x900 and 390x844 through a terminal browser; DOM probes for
  landmarks, `aria-sort`, focusable controls, resource sizes and timings.
- Bundled marts in `frontend/public/data` match the deployed files (manifest and byte sizes).
  All counts in this document come from those marts or from `data/biocintel.duckdb`
  (snapshot 2026-10-01).
- Lake figures (iCite, patents, authorships, RePORTER cost, OpenAlex `grants[]`) come from
  read-only cdsci-lake queries joined to the local store on 2026-10-06; they describe what an
  enrichment run would find, not what the site shows.
- Historic VIEWS, `tree.json`, release-announcements table, bioconductor.org stats page and shields
  badge were checked with HTTP requests (all 200). Historic citation pages checked for edgeR
  (3.0, 3.10, 3.16).
- Programmatic access (section 8): response headers and a Range request against the live
  `mart_package_impact.parquet` were inspected with curl; the DuckDB queries over the live URLs
  were run from this machine (Python `duckdb` with `httpfs`) and timed at 0.3 s.
- Views-file prototype (8.2): built with DuckDB 1.5.4 (`STORAGE_VERSION 'v1.0.0'`), served from a
  local Range-capable HTTP server, attached read-only from DuckDB 1.5.4 and from DuckDB 1.0.0 in a
  clean virtualenv with an isolated `secret_directory`. Views read the live Pages Parquet. A first
  attempt with Python's plain `http.server` (no Range support) failed on the 1.0 client, which is
  why the Pages Range support matters. R and DuckDB-WASM clients were not tested.
- Not verified: Open Graph rendering in a client, the exact RePORTER URL pattern, preprint/published
  duplication among linked works, and the extent of CITATION rotation beyond the edgeR example.
