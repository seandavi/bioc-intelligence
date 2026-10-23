# International grants and impact, with a European focus: opportunities, sources, recommendations

*Research note, 2026-10-23. Every number below came from a live probe on that date (keyless
OpenAlex, the local store at `data/biocintel.duckdb`). Claims about a source cite its own docs.
Anything I did not check is marked **unverified**.*

## Question

Today the grant layer is NIH-only. `enrich_from_lake --steps grants` joins PMIDs through
RePORTER `publink`, so `dim_grant` and `bridge_work_grant` (794 grants, 1,092 edges, 339 works)
can't see a European funder. What would it take to report funders and impact beyond NIH,
especially in Europe?

**Scope decision (2026-10-23): international by default, with Europe as a view.** The sources
below are funder-agnostic, so collecting every funder and country costs nothing extra.
Restricting collection to Europe would mean extra code to throw data away. "Europe" becomes one
set of region groupings applied at the mart/dashboard layer, not a collection boundary. The
Europe-specific numbers below motivated the work; the recommendations apply to every funder.

## What our own data already says

**The corpus is majority-European, but the grant layer is US-only.** "Europe" here means
EU27 + UK, CH, NO and IS. That list is a choice, and the code should make it explicit.

| Measure (linked primary works) | Count |
|---|---|
| Works with any institution in `bridge_work_institution` | 1,161 |
| …with a European affiliation | **640** (487 with no US affiliation) |
| …with a US affiliation | 519 |
| Works with an NIH grant in `bridge_work_grant` | 339 |

Country breakdown of affiliations: US 519, DE 180, GB 176, AU 117, CH 92, ES 67, IT 67, FR 57,
BE 54, DK 33, NL 28, SE 27.

**The funding metadata is already in OpenAlex.** I pulled `funders` and `awards` from live
OpenAlex for the 1,178 linked works. 1,026 resolved; the other 152 ids presumably merged, which
is worth a separate look. Of those 1,026:

- 904 list at least one funder and 769 list at least one award (3,063 distinct awards).
- **499 have a European funder** (a European funder country, or EC/ERC/Horizon/EMBL). 343 of
  those have no US funder. NIH-only reporting misses these works entirely.
- Top European funders by works: MRC 95, European Commission 84, BMBF 40, SNSF 37, Wellcome 36,
  CRUK 35, DFG 34, ANR 25, BBSRC 23, ERC (H2020) 21, ISCIII 20, EMBL 17, Academy of Finland 12.

## Sources

### 1. OpenAlex awards: the recommended spine (verified)

OpenAlex now has a first-class **award** entity (`G…` ids, `/awards`). Its legacy
`works.grants` field is deprecated and replaced by `works.awards` / `works.funders`
([awards docs](https://help.openalex.org/data/awards/),
[deprecations](https://help.openalex.org/api/deprecations/)). A full award record carries
`funder_award_id`, title, `amount`/`currency`/`amount_usd`, `funder_scheme` (e.g. `ERC-STG`),
start/end dates, recipient institutions with ROR and country, lead investigator, the grant DOI
(CORDIS's `10.3030/<id>`) and `provenance`. Example: `/awards/G2186373841` is ERC 949029.

OpenAlex ingests funder grant databases directly. Its public ingestion tracker
([openalex-walden `funder-ingestion-tracker.md`](https://github.com/ourresearch/openalex-walden/blob/main/plans/awards/funder-ingestion-tracker.md))
lists these as **Complete**: EC/CORDIS (H2020 + Horizon Europe + FP7), ERC, UKRI Gateway to
Research, DFG (144k grants), SNSF, ANR, Wellcome, NWO, FWF, FWO, Swedish Research Council,
Vinnova, Academy of Finland, Research Council of Norway, Research Ireland/SFI, Carlsbergfondet,
FCT, INCa and BELSPO. It lists INSERM, CNRS and the Italian ministry as blocked or not
applicable.

How complete the records are for *our* 3,063 awards, by `provenance`:

| provenance | awards | meaning |
|---|---|---|
| `crossref_work_funders` | 1,611 | stub from a publisher's funding acknowledgement: id string only |
| `europepmc_work_funders` | 452 | stub from Europe PMC's grant tagging |
| `nih_exporter` | 359 | full record |
| `nhmrc`, `nsf_award_search`, `gtr_legacy`, `gateway_to_research`, `cordis`, `snsf`, `foerderkatalog`, `anr_opendata`, `erc`, … | ~450 | full record from the funder's own database |

About two-thirds are stubs (no dates or amount). The funders with the most complete records are
EC (47/74 have dates), Wellcome 44/69, SNSF 34/49, ANR 28/50, BMBF 29/46 and ERC 12/20. CRUK is
0/48, DFG 10/52 and MRC 13/58. Stubs still give funder + award number, which is enough for
"funded by" reporting. The `funder_award_id` strings are messy (`"251217 and 255847"`,
`"HORIZON2020"`), so treat a stub's id as display text, not a join key.

Funder country comes from the `/funders` entity. **EC, ERC and Horizon programmes have no
`country_code`**, so supranational funders need an explicit mapping.

### 2. Citing-work geography and funders: the bigger impact story (verified)

The grant-reporting question is "who funded Bioconductor". The impact question is "how much
European-funded research *uses* Bioconductor", and OpenAlex answers it in one call per paper:

```
/works?filter=cites:W2179438025&group_by=authorships.countries   # DESeq2: 91,675 citing works; DE 10,106, GB 8,512, FR 5,386, ES 3,695, IT 3,490
/works?filter=cites:W2179438025&group_by=funders.id              # DFG 4,296 citing works, …
/works?filter=cites:W2179438025,funders.country_code:DE|GB|FR    # 16,495
```

Each call costs $0.0001. Doing all ~1.2k primary works × 2–3 groupings is about $0.40 and a few
thousand calls, so it needs `OPENALEX_API_KEY` (keyless allows $0.10/day). Caveats:
`group_by` returns at most 200 groups, which is fine for countries but truncates the funder long
tail. Per-paper counts can't be summed across papers, because a work citing two Bioconductor
papers would count twice. Ecosystem-level distinct counts need the citing works' funders joined
to the existing `fact_citation_edge` (365k citing works). Pulling those is about 7k
`filter=id:…` calls at 50 ids each, roughly $0.75.

### 3. Download geography from bioc-traffic (verified in code, not data)

`bioc-traffic` already rolls up by `country` × `package` (`sql/rollup_tier.sql`, `cf_country`).
Only the Cloudflare era has country, so history starts when bioconductor.org moved behind
Cloudflare (production since 2026-09-28). That makes it a forward-looking series, not a
historical one. Only de-identified aggregates leave bioc-traffic, and per-country package counts
fit that rule. bioconductor.org's legacy stats tabs have no geography.

### 4. ELIXIR Research Software Ecosystem / bio.tools (verified)

Bioconductor metadata syncs weekly into the ELIXIR RSEc. The
[`research-software-ecosystem/content`](https://github.com/research-software-ecosystem/content)
repo's `imports/bioconductor/` folder holds 4,932 files, about 2,466 packages × (json +
citation.html), from the [BioHackEU24 work](https://doi.org/10.37044/osf.io/dsgnw_v1). That gives
each package a bio.tools / EDAM identity in the European infrastructure. It's a cheap "listed in
ELIXIR" flag and a link that European reviewers recognise. bio.tools' own API returned 403 from
onclappc02, so I couldn't check its counts.

### 5. Sources considered and not recommended as primary

| Source | Verdict |
|---|---|
| **CORDIS** bulk / [Datalab](https://cordis.europa.eu/datalab) | OpenAlex ingests it (`cordis` provenance). `cordis.europa.eu/project/id/<id>?format=json` works for spot checks. Use it only if we need CORDIS-only fields (participants' EU contribution per partner, deliverables). |
| **OpenAIRE Graph API** ([docs](https://graph.openaire.eu/docs/apis/graph-api/)) | Has project↔product links and funder streams (`relProjectCode=949029` returns 5 products; project records have `fundingStream` such as `EC::H2020::ERC::ERC-STG`). But the DESeq2 record had `projects: null`, and its links mostly duplicate CORDIS, which OpenAlex already has. Keep it as a cross-check or regression source. |
| **Europe PMC** `grantsList` / GRIST (`ebi.ac.uk/europepmc/GristAPI/rest/get/query=…`) | Per-paper grant tags for the Europe PMC funders (scater has MRC, CRUK, EMBL, NHMRC). OpenAlex already ingests these (`europepmc_work_funders`), so it's redundant for linkage. GRIST is useful only for PI/ORCID detail on UK-heavy funders. |
| **Crossref** funding / [Grant Linking System](https://www.crossref.org/services/grant-linking-system/) | Upstream of OpenAlex's `crossref_work_funders`. Funder IDs are moving to ROR ([ROR, 2025-03-05](https://ror.org/blog/2025-03-05-using-ror-ids-in-place-of-funder-ids/)), so key `dim_funder` on ROR. |
| **UKRI GtR** software outcomes ([API](https://gtr.ukri.org/resources/gtrapi2-outcome-api.html)) | Researchfish-reported software outputs. `q=Bioconductor` returns **8** (casper, seqPattern, rHVDM, …). Low yield. Revisit only if UK-specific grant evidence is needed. |
| SNSF [data portal](https://data.snf.ch/datasets), DFG GEPRIS, national portals | Covered by OpenAlex awards. GEPRIS has no bulk export (scraping only). **Unverified**: whether SNSF's output CSVs carry DOIs we could match directly. |
| Dimensions, Overton (policy citations), Lens | Commercial or licensed. Overton is the usual source for EU policy-document citations. Out of scope unless someone pays for it. |

### 6. Framing for European reviewers

- **CoARA** ([agreement](https://www.coara.org/agreement/the-agreement-full-text/)) commits
  signatories (including many European funders and universities) to recognise outputs beyond
  papers, software among them, and to move away from journal-based metrics. Our download, reuse
  and dependency marts are exactly the qualitative-plus-usage evidence this asks for. Present
  them as such, not as citation counts.
- **Horizon Europe Key Impact Pathways**
  ([EC monitoring page](https://research-and-innovation.ec.europa.eu/strategy/support-policy-making/shaping-eu-research-and-innovation-policy/monitoring-evaluation-and-impact-assessment-horizon-europe_en))
  track short/medium/long-term indicators per pathway, such as uptake of research outputs and
  diffusion of knowledge. "EU-funded projects whose outputs cite or use package X" maps onto the
  scientific-impact KIP. **Unverified**: the exact indicator names in the KIP methodology
  handbook; check before quoting them in a proposal.

## Recommendations

In priority order. 1–3 are a small diff, entirely through the existing `biocintel.sources` API
path, with no lake and no new credentials beyond `OPENALEX_API_KEY`.

1. **Make OpenAlex awards the funder-agnostic grant spine; keep RePORTER as NIH detail.**
   #85 / PR #87 already does the linkage: `works.funders`/`works.awards` → `bridge_work_funder`
   (with `award_id`, `funder_award_id`), `dim_funder` re-keyed on the OpenAlex `F…` id with
   `ror` and `country_code`, and NIH awards joined to `dim_grant` by core project number. What's
   left is the award *detail* from `/awards`: scheme, start/end, amount/currency, award DOI,
   recipients and `provenance` (`dim_award`), plus flagging stub awards as stubs (#90).
   Together these light up the 499 European-funded works, along with every other funder: on
   our papers, NHMRC (86 awards), JSPS (24), NSFC (41), FAPESP (17), CIHR/NSERC and the long tail.
   *Caveat to put in the mart definitions:* an acknowledged award means "this paper credits that
   grant", **not** "that grant's amount funded the software". Never sum `amount` as Bioconductor
   funding.

2. **Add a region-grouping table; groupings are views, not scope.** A small checked-in table
   maps country → membership in named groupings, and one country can belong to several:
   `eu27`, `horizon_associated` (UK, CH, NO, IL, …), `europe_geographic`, and UN M49 world
   regions. Supranational funders that have no `country_code` in OpenAlex (EC, ERC, Horizon,
   MSCA, EMBL, ERDF, IMI, WHO, Gates, …) get a hand-mapped grouping. Marts carry country codes;
   the frontend filters by grouping. Which Europe a reviewer means is then a dashboard choice,
   not a pipeline change. (#91)

3. **Citing-work geography and funders per package** (§2). Add a `mart_package_reach` with
   citing-work counts by country and by top funders, from `group_by` calls on each primary work,
   stamped with `_snapshot` like the other facts. This is the headline reach metric ("N works
   funded by European funders cite this package", or any other grouping) and it's about
   $0.40/month.
   Do the ecosystem-level distinct version off `fact_citation_edge` only once someone needs that
   number. (#92)

4. **Reconcile Authors@R funders (`dim_funder`) with OpenAlex funders.** Done in PR #87:
   each `funder_aliases.yaml` entry gets an `openalex:` id, so the 3 DFG, 3 MCIU-Spain, …
   declarations join the same funder rows as paper acknowledgements. Unaliased declarations
   (de.NBI, Stichting tegen Kanker, …) still stay name-keyed; add aliases as they come up.

5. **ELIXIR flag.** Add a `biotools_id` / in-RSEc boolean on `dim_package` from the RSEc
   `imports/bioconductor` folder (one git tree listing, no API). It's cheap, and European
   reviewers recognise it. (#93)

6. **Download-by-country, later.** Consume bioc-traffic's country × package rollup once it has
   a few months of Cloudflare-era data. Don't backfill; the legacy era has no geography. (#94)

**Skip for now:** direct CORDIS/OpenAIRE/GRIST/GtR/SNSF integrations, since OpenAlex covers them
(keep them as spot-check tools), and commercial sources. Revisit OpenAIRE only if OpenAlex
awards turn out to miss EC project↔publication links we know exist.

## Caveats of going international

These apply to a Europe-only scope too; going international just makes them visible.

- **Grant-record completeness varies a lot by funder.** Of the awards on our papers that have a
  full record: SNSF 34/49, Wellcome 44/69, NSFC 8/41, CRUK 0/48, NIH institute awards well under
  half. So "share of papers with a funded grant, by region" mostly measures funder metadata
  quality. Report "papers crediting funder X"; never compare totals or rates across regions.
  This is also why RePORTER stays as the NIH source.
- **Money doesn't compare across countries.** `amount_usd` uses the exchange rate on the day
  (`amount_usd_basis: daily_rate`). We don't sum amounts anyway (recommendation 1), so this only
  affects how a single award is displayed.
- **`group_by` returns at most 200 groups.** That's fine for countries (DESeq2's citing works
  span 180) but drops the funder long tail. The full funder list needs the bulk pull of citing
  works off `fact_citation_edge` (§2, about $0.75).
- **China is large in the citing-work numbers.** It's second for DESeq2 (26,500 citing works).
  That's real reach, but it changes the story, so present it deliberately.
- **Supranational funders have no country** in OpenAlex, whatever the scope (recommendation 2).

## Side finding: stored OpenAlex ids drift

152 of the 1,178 `dim_work.openalex_id` values (stamped 2026-10-07) 404 on live OpenAlex two
weeks later. 140 of them are bioRxiv DOIs (`10.1101/…`). Looking up the DOI now returns the
journal version under a different `W…` id (e.g. `10.1101/577452` → `W2970457274`, PeerJ).
Anything keyed on the stored id silently loses those works: funders, awards, cited-by and the
reach calls in recommendation 3. That's about 13% of the corpus. (#95)
