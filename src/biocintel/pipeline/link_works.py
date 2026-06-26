"""link_works — match packages to OpenAlex works → bridge_package_pub (spec §6).

Kept simple (the settled decision): a package's DOI (from DESCRIPTION, extracted
into ``dim_package.source_doi``) is joined to ``lake.openalex.works.doi`` — the
authoritative, high-confidence path. An optional title fallback exact-matches
remaining packages by normalized title; it is **off by default and low-yield**
because a package's DESCRIPTION Title is rarely its manuscript's title (that needs
CITATION-derived titles, deferred). Every edge carries ``match_method`` +
``confidence`` so the dashboard can filter to DOI-only for grant reporting.

work_id follows the spine rule: PMID preferred, else DOI.
"""

from __future__ import annotations

import argparse
import re

import duckdb

from ..lake import connect_with_lake

_DOI_PREFIX_RE = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:)", re.IGNORECASE)

# DOI path: normalize our source_doi to the lake's bare-lowercase form and join.
_DOI_SQL = """
INSERT INTO bi.bridge_package_pub (package_name, repo, work_id, role, match_method, confidence)
SELECT p.package_name, p.repo,
       COALESCE(CAST(w.pmid AS VARCHAR), w.doi) AS work_id,
       'primary', 'doi', 1.0
FROM bi.dim_package p
JOIN lake.openalex.works w
  ON lower(regexp_replace(p.source_doi, '^(https?://(dx\\.)?doi\\.org/|doi:)', '', 'i')) = w.doi
WHERE p.source_doi IS NOT NULL;
"""

# Title fallback (opt-in): exact normalized-title match for still-unlinked packages.
_TITLE_SQL = """
INSERT INTO bi.bridge_package_pub (package_name, repo, work_id, role, match_method, confidence)
SELECT p.package_name, p.repo,
       COALESCE(CAST(w.pmid AS VARCHAR), w.doi) AS work_id,
       'primary', 'title_search', 0.4
FROM bi.dim_package p
JOIN lake.openalex.works w
  ON lower(trim(p.title)) = lower(trim(w.title))
WHERE p.title IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM bi.bridge_package_pub b
      WHERE b.package_name = p.package_name AND b.repo = p.repo
  );
"""


def normalize_doi(value: str | None) -> str | None:
    """Reduce a DOI string to the lake's bare-lowercase form (offline helper/test)."""
    if not value:
        return None
    return _DOI_PREFIX_RE.sub("", value.strip()).lower() or None


def run(*, title_fallback: bool = False) -> dict[str, int]:
    con = connect_with_lake()
    counts: dict[str, int] = {}
    try:
        # Idempotent: clear automated rows (keep any 'manual' overrides), then rebuild.
        con.execute(
            "DELETE FROM bi.bridge_package_pub WHERE match_method IN ('doi', 'title_search')"
        )
        counts["doi"] = _rowcount(con, _DOI_SQL)
        print(f"  doi matches: {counts['doi']}")
        if title_fallback:
            counts["title_search"] = _rowcount(con, _TITLE_SQL)
            print(f"  title_search matches: {counts['title_search']}")
    finally:
        con.close()
    return counts


def _rowcount(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    before = con.execute("SELECT count(*) FROM bi.bridge_package_pub").fetchone()[0]
    con.execute(sql)
    after = con.execute("SELECT count(*) FROM bi.bridge_package_pub").fetchone()[0]
    return after - before


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Link packages to OpenAlex works (lake).")
    ap.add_argument(
        "--title-fallback", action="store_true",
        help="also attempt low-confidence exact-title matches (off by default)",
    )
    args = ap.parse_args(argv)
    print("link_works:")
    run(title_fallback=args.title_fallback)


if __name__ == "__main__":
    main()
