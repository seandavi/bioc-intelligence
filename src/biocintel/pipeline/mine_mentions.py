"""mine_mentions — full-text package mentions from the lake → fact_mention_candidate.

The corpus is already in the lake (`lake.pmc.passages`, ~974M passages with
`section_type` + `text`), so mining is an FTS-style scan there rather than a
rate-limited Europe PMC crawl. Per spec §6 we **store raw mention text now and
judge later** (see `judge_mentions`): mining is the expensive step, so materialize
candidates once.

Cost reality: any scan of `pmc.passages` reads ~974M rows / ~360 GB on R2. This is
the expensive batch step — so:
- callers must pass an explicit package set (no accidental whole-corpus run),
- `passage_limit` bounds the scan to the first row groups for a cheap smoke test.

Matching is word-boundary, case-insensitive on the package name. Genuineness
(`sva`/`made4`/`qpcR` collide with common words) is the judge's job, not mining's.
"""

from __future__ import annotations

import argparse
import re

from ..lake import connect_with_lake

_CAND_COLS = [
    "package_name", "repo", "citing_work_id", "source", "mention_text",
    "section", "match_offset", "_extracted_snapshot",
]


def build_pattern(name: str) -> str:
    """Word-boundary regex for a package name (offline helper/test)."""
    return rf"\b{re.escape(name)}\b"


def _mention_sql(passage_limit: int | None) -> str:
    src = "lake.pmc.passages"
    if passage_limit is not None:
        src = f"(SELECT * FROM lake.pmc.passages LIMIT {int(passage_limit)})"
    return f"""
    INSERT INTO bi.fact_mention_candidate
        ({', '.join(_CAND_COLS)})
    SELECT n.package_name, n.repo,
           COALESCE(CAST(d.pmid AS VARCHAR), d.doi, p.pmcid) AS citing_work_id,
           'epmc' AS source,
           substr(p.text, 1, 1000) AS mention_text,
           p.section_type AS section,
           p.passage_offset AS match_offset,
           current_date
    FROM {src} p
    JOIN names n ON regexp_matches(p.text, n.pattern, 'i')
    LEFT JOIN lake.pmc.documents d ON d.pmcid = p.pmcid;
    """


def run(packages: list[str], *, passage_limit: int | None = None) -> int:
    if not packages:
        raise ValueError("mine_mentions needs an explicit package list (it scans ~974M passages)")
    con = connect_with_lake()
    try:
        rows = con.execute(
            "SELECT package_name, repo FROM bi.dim_package WHERE package_name IN "
            f"({', '.join('?' for _ in packages)})",
            packages,
        ).fetchall()
        if not rows:
            print("  no matching packages in dim_package; nothing to mine")
            return 0
        con.execute(
            "CREATE OR REPLACE TEMP TABLE names "
            "(package_name VARCHAR, repo VARCHAR, pattern VARCHAR)"
        )
        con.executemany(
            "INSERT INTO names VALUES (?, ?, ?)",
            [[name, repo, build_pattern(name)] for name, repo in rows],
        )
        # Idempotent for this package set: clear prior epmc candidates, then mine.
        con.execute(
            "DELETE FROM bi.fact_mention_candidate WHERE source='epmc' "
            "AND package_name IN (SELECT package_name FROM names)"
        )
        scope = (
            f"first {passage_limit} passages (smoke)" if passage_limit else "full corpus (~974M)"
        )
        print(f"  mining {len(rows)} package(s) over {scope}…")
        con.execute(_mention_sql(passage_limit))
        n = con.execute(
            "SELECT count(*) FROM bi.fact_mention_candidate WHERE source='epmc'"
        ).fetchone()[0]
        print(f"  fact_mention_candidate (epmc): {n}")
        return n
    finally:
        con.close()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Mine full-text package mentions from the lake.")
    ap.add_argument("--packages", required=True, help="comma-separated package names to mine")
    ap.add_argument(
        "--passage-limit", type=int, default=None,
        help="bound the passage scan (smoke test); omit for the full ~974M-row corpus",
    )
    args = ap.parse_args(argv)
    pkgs = [p.strip() for p in args.packages.split(",") if p.strip()]
    print("mine_mentions:")
    run(pkgs, passage_limit=args.passage_limit)


if __name__ == "__main__":
    main()
