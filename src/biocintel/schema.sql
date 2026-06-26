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
    _snapshot       DATE
);

CREATE TABLE IF NOT EXISTS dim_grant (
    grant_id     VARCHAR PRIMARY KEY,
    agency       VARCHAR,
    project_num  VARCHAR,
    fy           INTEGER,
    title        VARCHAR
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
    match_method  VARCHAR,                -- 'doi' | 'citation_file' | 'title_search' | 'manual'
    confidence    DOUBLE
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
