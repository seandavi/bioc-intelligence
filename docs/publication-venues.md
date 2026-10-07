# Research: Where to publish the Bioconductor impact dashboard, its dataset, and the metaresearch findings

Checked 2026-10-06. "Verified" means I read the figure on the venue's own page during this run. "Snippet" means I saw it only in a search-engine excerpt of the venue's own page; the page itself was not fetched (OUP pages return 403 to the fetcher). "Unverified" means it came from a secondary or AI-summary source, or from memory. Re-check every fee before you submit.

## Summary

Three outputs, three venues. The site and software fit the **F1000Research Bioconductor gateway** (Software Tool Article, $1,268) or **JOSS** (free), with a caveat about JOSS's scope for web tools. The dataset should get a **Zenodo DOI** now, with a **Scientific Data** Data Descriptor ($2,690) as the peer-reviewed home. For the metaresearch paper, **PLOS Computational Biology** is the strongest fit: in May 2026 it published a closely comparable study of PyPI, CRAN and Bioconductor dependencies. Post a bioRxiv preprint first and present at BioC2027 or EuroBioC2027 while the paper is in review.

## Venue table

| Venue | Type | Fits which output | Format / length | OA cost (USD unless noted) | Time to decision | Bioconductor / research-software precedent | Notes |
|---|---|---|---|---|---|---|---|
| **Bioinformatics** (OUP) Application Note | Journal, short software paper | Site/software | ≤4 pages, about 2,600 words, or 2,000 words plus 1 figure (snippet, [author guidelines](https://academic.oup.com/bioinformatics/pages/author-guidelines)) | Now fully OA, with a per-article APC. Amount **unverified**: about $3,798, ISCB discount 15% (AI summary). [OA page](https://academic.oup.com/bioinformatics/pages/open-access) returned 403 | Unverified | Many Bioconductor Application Notes exist; none checked in this run | The 4-page limit is too short for ecosystem findings. Fine for "the dashboard exists." Expensive for what it gives you. |
| **Genome Biology** Software / Brief Report | Journal | Software (Software article). Metaresearch is a stretch | Software articles must show a novel, broadly useful tool | **$5,690**. Brief Report **$4,280** (snippet, [submission guidelines](https://link.springer.com/journal/13059/submission-guidelines)) | Unverified | Gentleman et al. 2004, the founding Bioconductor paper ([link](https://genomebiology.biomedcentral.com/articles/10.1186/gb-2004-5-10-r80)), verified | Historical home of Bioconductor. A dashboard is probably not "novel software" enough for them, and it is the most expensive option. |
| **PLOS Computational Biology** Research / Software / Education | Journal | **Metaresearch (Research Article)**. Also Software | No length limit ([guidelines](https://journals.plos.org/ploscompbiol/s/submission-guidelines), verified). Software must be "widely adopted or promise wide adoption" | **$3,165** Research Article ([PLOS fees](https://plos.org/fees/), verified) | Unverified | Brown, Druskat, Howison et al., "Biomedical open source software: Crucial packages and hidden heroes," PLOS CB, 13 May 2026, analyzes PyPI, CRAN and **Bioconductor** ([link](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1014260)), verified. Also Bioconductor "Eleven quick tips" / teaching papers in 2025 (unverified) | Best topical fit. It has recently published both ecosystem-dependency metaresearch and Bioconductor community papers. |
| **F1000Research Bioconductor gateway** | Post-publication-review journal | **Site/software** (Software Tool Article). A Research Article could carry the metaresearch | Article guidelines not fetched. Open review, versioned | **$1,268** Software Tool, **$1,758** Research, **$1,003** Data Note ([APC page](https://f1000research.com/for-authors/article-processing-charges), verified). Updates $500 | Published within days of passing checks. Indexing waits on reviews (general model; timing unverified) | BiocPkgTools (Su, Carey, Shepherd, Ritchie, Morgan, Davis 2019), the closest predecessor tool ([link](https://f1000research.com/articles/8-752)), verified. Gateway still active, with articles dated Aug 2025 ([gateway](https://f1000research.com/gateways/bioconductor)) | Natural community home. Versioning suits a monthly-refreshed product. Some reviewers in metaresearch give it less weight than a traditional journal. |
| **JOSS** | Software paper (short, about 1,000 words, unverified) | Site/software, but only if packaged as a library | Short paper. The software itself is reviewed on GitHub | **Free** (diamond OA, [about](https://joss.theoj.org/about), verified) | Unverified. JOSS publishes analytics | basilisk, a Bioconductor package ([10.21105/joss.04742](https://joss.theoj.org/papers/10.21105/joss.04742)), verified | **Risk:** "Many web-based research tools are out of scope." They are allowed only if the site exposes a core library. Requires 6+ months of public history. The 2026 scope update raised the impact bar. The `biocintel` Python pipeline is the part that could qualify. |
| **Journal of Open Research Software** | Software metapaper / "Issues in Research Software" | Software. The Issues section explicitly covers "research software ecosystems and measuring the impact of software" | Issues articles 3,000–4,000 words ([submissions](https://openresearchsoftware.metajnl.com/about/submissions), verified) | **£824** metapaper, **£891** Issues (verified). The Ubiquity APC table and older DOAJ entry show slightly different figures | DOAJ says about 21 weeks from submission to publication (snippet) | None found | Low visibility in biomedicine. The Issues track fits a short metaresearch commentary. |
| **Scientific Data** Data Descriptor | Data paper | **Dataset** (marts plus DuckDB views) | Data Descriptor format | **$2,690** ([OA page](https://www.nature.com/sdata/open-access), snippet) | Unverified | SciSciNet, a science-of-science data lake, published as a Data Descriptor ([link](https://www.nature.com/articles/s41597-023-02198-9)), verified | Expects a static, versioned deposit (Zenodo snapshot) plus technical validation. Monthly refresh is fine if you cite a frozen version. |
| **Nature Methods** Brief Communication / Correspondence | Journal | Short findings or an announcement | Brief Communication: 1,200 words (up to 1,600), ≤2 display items. Correspondence: ≤800 words, 1 figure, **no new data** ([content types](https://www.nature.com/nmeth/content), verified) | Hybrid. APC not checked | Unverified | Huber et al. 2015, "Orchestrating high-throughput genomic analysis with Bioconductor" (Perspective) ([link](https://www.nature.com/articles/nmeth.3252)), verified | A Correspondence can't carry the analysis. A Brief Communication needs a striking single finding. Long shot. |
| **PLOS Biology** Meta-Research Article | Journal | Metaresearch, if it is framed around research evaluation and reward | Meta-Research article type exists ([what we publish](https://journals.plos.org/plosbiology/s/what-we-publish)) | **$5,500** non-member under Community Action Publishing ([PLOS fees](https://plos.org/fees/), verified) | Unverified | No Bioconductor example found | High bar. Fits only if the paper argues something general about software credit or funding ROI, not "Bioconductor grew." |
| **Quantitative Science Studies** (ISSI / MIT Press) | Journal | Metaresearch (bibliometrics angle) | Not fetched (403) | **$1,200** non-member / **$750** ISSI member, from 2023 ([ISSI post](https://www.issi-society.org/blog/posts/2022/november/open-access-publishing-in-quantitative-science-studies-an-update/), verified, dated 2022). Waivers "less generous" after 2022 | Unverified | None verified | Cheap and well respected in scientometrics. Weak reach to Bioconductor and NIH readers. |
| **Research Evaluation** (OUP) | Journal | Metaresearch (grant ROI, impact evidence angle) | 8,000–10,000 words (snippet, [author guidelines](http://academic.oup.com/rev/pages/author-guidelines)) | Hybrid. APC not verified | Unverified | None found | Fits the "evidence for grant reporting" story. |
| **Scientometrics** (Springer) | Journal | Metaresearch | Not checked | Hybrid. OA APC **$3,290** (verified, [how to publish](https://link.springer.com/journal/11192/how-to-publish-with-us)) | Unverified | None verified | Subscription route is free but isn't compliant with the NIH public-access policy unless you use green OA. |
| **PeerJ Computer Science** | Journal | Metaresearch (software-engineering / MSR angle), software | Accepts Application Notes ([FAQ](https://peerj.com/computer-science/faq-cs/), verified) | **$2,155** (verified) | Unverified | None verified | The audience is software engineering, not biology. |
| **GigaScience / GigaByte** | Journal / data and software journal | Dataset (GigaByte Data Release) or software (Technical Release) | Short articles, "release then review" | GigaByte **$535** for 2025 submissions ([APC page](https://gigabytejournal.com/open-access-and-apc), verified; the 2026 figure isn't shown), includes 1 TB of GigaDB hosting. GigaScience APC **unverified** (about $2,400–2,600, AI summary) | Unverified | None verified | GigaByte is a cheap, fast home for the data. Low profile. |
| **bioRxiv** | Preprint | Metaresearch (Scientific Communication and Education category); also software | No limit | Free | About 1–3 days (general knowledge, unverified) | Bioconductor papers routinely preprinted, e.g. 2025 OSTA/OMA (unverified) | Do this first. medRxiv is out of scope (clinical). |
| **Zenodo** | Data/software archive | **Dataset and software DOI** | Any. Versioned concept DOI | Free | Immediate | n/a | Mint a concept DOI per monthly mart snapshot (or per release). Required for Scientific Data/GigaByte anyway. |
| **Bioconductor blog** | Community outlet | Site launch plus headline findings | Blog post | Free | Editorial (process unverified) | Blog has a "bioconductor-evolution" category and 2026 posts (verified, [blog](https://blog.bioconductor.org/)) | Highest-value audience for adoption. |
| **BioC2027 / EuroBioC2027** | Conference talk or poster (abstracts can go to the F1000 gateway) | Software demo plus findings | Abstract | Registration | CFP dates TBD | EuroBioC2027: **Sept 8–10, 2027, Basel** ([site](https://eurobioc2027.bioconductor.org/), verified). BioC2027 dates and location **unverified**; BioC2026 recap posted 2026-09-30 | Best venue for community feedback before the paper goes final. |
| **rOpenSci blog** | Community outlet | Possibly a tech note (DuckDB-WASM marts) | Blog | Free | Unverified | Has written on package citation ([2021 post](https://ropensci.org/blog/2021/02/16/package-citation/), from search results) | Guest-post policy not verified. Mostly covers rOpenSci-affiliated work. Low priority. |
| **The R Journal** | Journal | Weak fit: the pipeline is Python, and R Journal articles must be "primarily about R packages and R programming" ([overview](https://journal.r-project.org/), verified) | ≤20 pages (verified) | Free (unverified; fee not stated on the fetched pages) | Unverified | Bioconductor package papers appear there (not checked) | Out of scope unless you ship an R client package. |
| *Patterns* (Cell Press), extra | Journal | Metaresearch, data science | — | Not checked | — | Carey 2025, "Bioconductor: Planning a third decade…" (unverified, AI summary) | Worth a look if confirmed. |

## Findings

1. **Claim:** A May 2026 PLOS Computational Biology research article analyzed PyPI, CRAN and Bioconductor dependency centrality using the CZ Software Mentions dataset. **Sources:** [Brown et al. 2026](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1014260). **Support:** direct. **Confidence:** high. *Inference:* this is your closest prior work and a reviewer pool. Cite it, and position your paper as adding the longitudinal, downloads, grants and geography layer it lacks.
2. **Claim:** The foundational ecosystem papers are confirmed: Gentleman et al. 2004 (Genome Biology) and Huber et al. 2015 (a Nature Methods *Perspective*, not a research article; Sean Davis is a co-author). BiocPkgTools (F1000Research 2019) is a direct tooling predecessor by overlapping authors. **Support:** direct. **Confidence:** high.
3. **Claim:** JOSS treats most web-based tools as out of scope unless they expose a core library, and it raised its impact and design bar in 2026. **Source:** [JOSS about](https://joss.theoj.org/about). **Support:** direct. **Confidence:** high. *Inference:* submit the `biocintel` pipeline, not the SPA.
4. **Claim:** Science-of-science data lakes have been published as Scientific Data Descriptors (SciSciNet). **Support:** direct. **Confidence:** high.
5. **Claim:** The F1000 Bioconductor gateway is still publishing (2025 articles) and costs less than the traditional journals here. **Support:** direct. **Confidence:** high.

## Contradictions

- JORS fees: the journal page lists £824 / £891. The search snippet and the Ubiquity APC table showed £800 / £865 and £824, and Europub showed £350. I used the journal page.
- GigaByte APC: an AI summary said $350. The journal page says $535 for 2025 submissions.

## Missing evidence

- The Bioinformatics, GigaScience, Nature Methods and Research Evaluation APCs could not be fetched (403 or not attempted).
- Time to first decision for almost every venue. None of the per-journal metrics pages were fetched.
- BioC2027 dates and location, and the Bioconductor blog and rOpenSci guest-post submission processes.
- A verified metaresearch-on-software-ecosystems example in QSS, Scientometrics or PeerJ CS. The empirical R-ecosystem studies I found (Decan et al.; Bommarito & Bommarito, arXiv 2102.09904) are in software-engineering venues or preprints, and their venues weren't verified.
- Whether a CRAN- or Bioconductor-specific downloads × citations × grants study already exists. None turned up, but the search was not exhaustive.

## Sources

- Kept: PLOS fees; F1000 APC page; JOSS about; JORS submissions; Scientometrics how-to-publish; Nature Methods content types; PLOS CB submission guidelines; ISSI QSS APC post; PeerJ CS FAQ; GigaByte APC page; EuroBioC2027 site; F1000 Bioconductor gateway; the Huber 2015, Gentleman 2004, BiocPkgTools, Brown 2026 and SciSciNet articles.
- Deprioritized: manusights.com APC blogs (SEO and secondary); the Gemini AI summaries (used only as leads and marked unverified).

## Recommendation

- **Site/software → F1000Research Bioconductor gateway, Software Tool Article** ($1,268). It continues the BiocPkgTools lineage, publishes as soon as it passes checks, and its versioning matches the monthly refresh. Fallback: JOSS for the `biocintel` pipeline (free), which needs packaging and a library framing.
- **Dataset → Zenodo concept DOI now, then a Scientific Data Data Descriptor** ($2,690) on a frozen snapshot. Cheaper fallback: GigaByte Data Release (about $535).
- **Metaresearch → PLOS Computational Biology Research Article** ($3,165). It has direct topical precedent from 2026 and no length cap. Escalate to PLOS Biology Meta-Research only if the framing becomes general (software credit, funding ROI). QSS (~$1,200) is the low-cost scientometrics alternative.
- **Sequencing:**
  1. Zenodo snapshot plus a bioRxiv preprint of the metaresearch paper. This gives you a citable date and lets you use the work in grants right away.
  2. A Bioconductor blog post announcing the site and headline figures, linking the preprint.
  3. Submit the BioC2027 or EuroBioC2027 abstract (CFP TBD) and gather community corrections, for example on package-to-paper linkage errors.
  4. Submit to PLOS CB in parallel, with the F1000 software article and the Scientific Data descriptor cross-citing the same Zenodo DOI.

  Community-first is cheap and catches linkage errors before reviewers do. Preprint-first protects priority given the 2026 Brown et al. paper.

```acceptance-report
{
  "criteriaSatisfied": [
    {"id": "criterion-1", "status": "satisfied", "evidence": "Brief written to /data/davsean/tmp/venues-research.md with venue table, findings, contradictions, missing evidence, and recommendation; fees verified on primary pages where marked"}
  ],
  "changedFiles": ["/data/davsean/tmp/venues-research.md"],
  "testsAddedOrUpdated": [],
  "commandsRun": [],
  "validationOutput": ["Primary-page verification for PLOS, F1000, JOSS, JORS, Scientometrics, Nature Methods, PeerJ CS, GigaByte, QSS (ISSI), EuroBioC2027, and the precedent articles"],
  "residualRisks": [
    "Bioinformatics, GigaScience, Research Evaluation and Nature Methods APCs unverified (403 or not fetched)",
    "Times to decision largely unverified",
    "BioC2027 dates/location and blog guest-post processes unverified",
    "Genome Biology and Scientific Data APCs taken from search snippets of the primary pages, not full fetches"
  ],
  "noStagedFiles": true,
  "diffSummary": "New research brief file only",
  "reviewFindings": ["no blockers"],
  "manualNotes": "Exa search was rate-limited partway through and Brave had no API key, so the Gemini summaries were used only to find leads; every claim that depends on them is marked unverified. Prices were checked on 2026-10-06."
}
```
