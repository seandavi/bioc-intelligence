-- Canonical schema for the bioc-intelligence DuckDB store (spec §5).
-- Dimensions are rebuilt per release; facts are append-only and snapshot-stamped.

-- ── Dimensions ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_package (
    package_name        VARCHAR NOT NULL,
    repo                VARCHAR NOT NULL,
    first_seen_release  VARCHAR,
    latest_release      VARCHAR,
    maintainer          VARCHAR,
    maintainer_email    VARCHAR,
    maintainer_ror      VARCHAR,          -- best-effort, often null (spec §3)
    title               VARCHAR,
    description         VARCHAR,
    biocviews           VARCHAR[],
    url                 VARCHAR[],
    bug_reports         VARCHAR,
    source_doi          VARCHAR,          -- DOI of describing manuscript, if known
    -- VIEWS dependency / maintenance / docs fields (#39), deps are bare names with R excluded
    depends             VARCHAR[],
    imports             VARCHAR[],
    suggests            VARCHAR[],
    linking_to          VARCHAR[],
    depends_on_me       VARCHAR[],
    imports_me          VARCHAR[],
    suggests_me         VARCHAR[],
    links_to_me         VARCHAR[],
    dependency_count    INTEGER,
    git_last_commit_date DATE,
    date_publication    DATE,
    package_status      VARCHAR,
    has_readme          BOOLEAN,
    has_news            BOOLEAN,
    has_install         BOOLEAN,
    has_license         BOOLEAN,
    n_vignettes         INTEGER,
    vignette_titles     VARCHAR[],
    license             VARCHAR,
    needs_compilation   BOOLEAN,
    PRIMARY KEY (package_name, repo)
);

CREATE TABLE IF NOT EXISTS dim_package_version (
    package_name   VARCHAR NOT NULL,
    repo           VARCHAR NOT NULL,
    version        VARCHAR NOT NULL,
    bioc_release   VARCHAR NOT NULL,
    release_date   DATE,
    r_version      VARCHAR,
    in_devel       BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (package_name, repo, version, bioc_release)
);

-- One row per release from the release-announcements page (1.0 onwards).
CREATE TABLE IF NOT EXISTS dim_release (
    bioc_release          VARCHAR PRIMARY KEY,
    release_date          DATE,
    n_software_announced  INTEGER
);

CREATE TABLE IF NOT EXISTS dim_work (
    work_id         VARCHAR PRIMARY KEY,  -- PMID preferred, else DOI
    pmid            VARCHAR,
    doi             VARCHAR,
    openalex_id     VARCHAR,
    title           VARCHAR,
    year            INTEGER,
    journal         VARCHAR,
    icite_rcr       DOUBLE,
    citation_count  BIGINT,
    _snapshot       DATE,
    nih_percentile      DOUBLE,   -- iCite
    apt                 DOUBLE,   -- iCite Approximate Potential to Translate
    is_clinical         BOOLEAN,  -- iCite
    citations_per_year  DOUBLE,   -- iCite
    is_retracted        BOOLEAN,  -- OpenAlex
    n_patent_citations  INTEGER   -- distinct citing patents (reliance.patent_citations)
);

CREATE TABLE IF NOT EXISTS dim_grant (
    grant_id     VARCHAR PRIMARY KEY,
    agency       VARCHAR,
    project_num  VARCHAR,
    fy           INTEGER,
    title        VARCHAR,
    ic_name      VARCHAR,
    fy_first     INTEGER,
    fy_last      INTEGER,
    org_name     VARCHAR,
    org_country  VARCHAR,
    pi_names     VARCHAR
);

-- ── Facts & bridges ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_download (
    package_name    VARCHAR NOT NULL,
    repo            VARCHAR NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,     -- 1..12; the source "all" rows are dropped
    distinct_ips    BIGINT,
    downloads       BIGINT,
    methodology_era VARCHAR NOT NULL,
    _snapshot       DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS bridge_package_pub (
    package_name  VARCHAR NOT NULL,
    repo          VARCHAR NOT NULL,
    work_id       VARCHAR NOT NULL,
    role          VARCHAR,                -- 'primary' | 'companion'
    match_method  VARCHAR,                -- 'doi' | 'citation_file' | 'description_doi' | 'title_search' | 'manual'
    confidence    DOUBLE,
    source_release VARCHAR                -- citation_file: 'devel' | 'release' | past release e.g. '3.16'
);

CREATE TABLE IF NOT EXISTS fact_citation_edge (
    cited_work_id   VARCHAR NOT NULL,
    citing_work_id  VARCHAR NOT NULL,
    source          VARCHAR,              -- 'openalex' | 'epmc'
    mention_type    VARCHAR,              -- 'formal' | 'fulltext'
    _snapshot       DATE
);

CREATE TABLE IF NOT EXISTS bridge_work_grant (
    work_id   VARCHAR NOT NULL,
    grant_id  VARCHAR NOT NULL,
    source    VARCHAR
);

-- ── Mention candidates (store raw, judge later) (spec §6) ────────────────────
CREATE TABLE IF NOT EXISTS fact_mention_candidate (
    package_name             VARCHAR NOT NULL,
    repo                     VARCHAR NOT NULL,
    citing_work_id           VARCHAR NOT NULL,
    source                   VARCHAR,
    mention_text             VARCHAR,
    section                  VARCHAR,
    match_offset             BIGINT,
    _extracted_snapshot      DATE,
    -- judge columns, nullable, filled by a later independent pass:
    judged_at                TIMESTAMP,
    is_genuine_mention       BOOLEAN,
    package_confidence       DOUBLE,
    usage_vs_passing_reference VARCHAR
);

-- ── People & funders from Authors@R (#23). No emails are stored, by design. ──
CREATE TABLE IF NOT EXISTS dim_person (
    person_id  VARCHAR PRIMARY KEY,       -- 'orcid:0000-…' or 'name:<normalized name>'
    name       VARCHAR NOT NULL,
    orcid      VARCHAR,
    ror        VARCHAR                    -- declared affiliation ROR; best-effort, often null
);

CREATE TABLE IF NOT EXISTS bridge_package_person (
    package_name  VARCHAR NOT NULL,
    repo          VARCHAR NOT NULL,
    person_id     VARCHAR NOT NULL,
    roles         VARCHAR[] NOT NULL,     -- MARC-style codes as declared: aut, cre, ctb, ...
    source        VARCHAR NOT NULL        -- 'authors_r' | 'description_author' | 'views_author' | 'maintainer'
);

CREATE TABLE IF NOT EXISTS dim_funder (
    funder_id  VARCHAR PRIMARY KEY,       -- alias-table id (e.g. 'czi') or 'name:<normalized>'
    name       VARCHAR NOT NULL,
    curated    BOOLEAN NOT NULL           -- true when funder_aliases.yaml recognised it
);

CREATE TABLE IF NOT EXISTS bridge_package_funder (
    package_name   VARCHAR NOT NULL,
    repo           VARCHAR NOT NULL,
    funder_id      VARCHAR NOT NULL,
    declared_name  VARCHAR NOT NULL,      -- as written in Authors@R
    grant_number   VARCHAR,               -- NIH core project number → dim_grant.grant_id
    source         VARCHAR NOT NULL
);

-- ── Institutions of linked works, from OpenAlex authorships (#48). Best-effort. ──
CREATE TABLE IF NOT EXISTS dim_institution (
    ror           VARCHAR PRIMARY KEY,    -- as OpenAlex writes it: 'https://ror.org/…'
    openalex_id   VARCHAR,
    name          VARCHAR,
    country_code  VARCHAR,
    country       VARCHAR,
    type          VARCHAR,
    city          VARCHAR,
    region        VARCHAR,
    latitude      DOUBLE,
    longitude     DOUBLE
);

CREATE TABLE IF NOT EXISTS bridge_work_institution (
    work_id           VARCHAR NOT NULL,
    ror               VARCHAR NOT NULL,
    author_position   VARCHAR,            -- 'first' | 'middle' | 'last'
    is_corresponding  BOOLEAN,
    source            VARCHAR
);
