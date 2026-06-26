"""extract_citation_files — package CITATION → bridge_package_pub (spec §6).

The authoritative description of a package's manuscript(s) is its CITATION file.
Bioconductor renders one per package as HTML at
``/packages/release/bioc/citations/<pkg>/citation.html`` (HTTP 200 when present;
many packages have none — a 404 we skip). We extract every DOI (and best-effort
PMID) from that page and record one ``bridge_package_pub`` edge per citation with
``match_method = 'citation_file'``. This expands package→manuscript linkage beyond
the handful of DOIs that happen to be embedded in DESCRIPTION ``URL``/``BugReports``.

work_id follows the spine rule: PMID preferred, else DOI.

Scope: this PR covers the ``bioc`` repo only. The other three repos
(``data-experiment``, ``data-annotation``, ``workflows``) also expose citation
pages and are future work.
"""

from __future__ import annotations

import argparse
import re

from .. import db
from ..config import BIOC_BASE
from ..http import HttpError, get_text

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>,]+")
# Bioconductor mints a self-DOI for every package landing page; it is not a
# describing manuscript, so it never becomes a linkage.
_BIOC_SELF_DOI_PREFIX = "10.18129/"
_PMID_RE = re.compile(r"(?:PMID:?\s*|pubmed/)(\d+)", re.IGNORECASE)

_INSERT_COLS = ["package_name", "repo", "work_id", "role", "match_method", "confidence"]


def citation_url(package: str, repo: str = "bioc") -> str:
    """Rendered-HTML citation page for ``package`` in ``repo`` (bioc only for now)."""
    return f"{BIOC_BASE}/packages/release/{repo}/citations/{package}/citation.html"


def _clean_doi(doi: str) -> str:
    # Trim trailing punctuation the loose char class may have swept up.
    return doi.rstrip(".,;)")


def parse_citation_html(html: str) -> list[dict[str, str | None]]:
    """Extract distinct (doi, pmid) citation records from a rendered citation page.

    Returns one record per distinct DOI (the stable per-manuscript key), each with
    a best-effort PMID if one appears anywhere on the page. Bioconductor self-DOIs
    are excluded. Order is preserved (first appearance wins).
    """
    pmid_match = _PMID_RE.search(html)
    pmid = pmid_match.group(1) if pmid_match else None

    records: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for m in _DOI_RE.finditer(html):
        doi = _clean_doi(m.group(0))
        if doi.startswith(_BIOC_SELF_DOI_PREFIX) or doi in seen:
            continue
        seen.add(doi)
        records.append({"doi": doi, "pmid": pmid})
    return records


def _rows_for_package(package: str, records: list[dict[str, str | None]]) -> list[list]:
    rows: list[list] = []
    for rec in records:
        # Spine rule: PMID preferred as work_id, else DOI.
        work_id = rec["pmid"] or rec["doi"]
        rows.append([package, "bioc", work_id, "primary", "citation_file", 0.9])
    return rows


def run(repos: list[str] | None = None) -> dict[str, int]:
    """Extract CITATION-file linkages for ``bioc`` packages into bridge_package_pub.

    ``repos`` is accepted for interface symmetry with the other extractors but only
    ``bioc`` is supported in this PR; any other value is ignored with a note.
    """
    if repos and repos != ["bioc"]:
        print(f"  note: only 'bioc' is supported; ignoring {repos}")

    con = db.connect()
    db.init_schema(con)
    counts = {"packages": 0, "linked": 0, "rows": 0, "skipped_404": 0}
    try:
        packages = [
            r[0]
            for r in con.execute(
                "SELECT package_name FROM dim_package WHERE repo = 'bioc' ORDER BY package_name"
            ).fetchall()
        ]
        counts["packages"] = len(packages)
        if not packages:
            print("  no bioc packages in dim_package — run extract-packages first")
            return counts

        all_rows: list[list] = []
        linked = 0
        for pkg in packages:
            try:
                html = get_text(citation_url(pkg))
            except HttpError:
                counts["skipped_404"] += 1
                continue
            records = parse_citation_html(html)
            if not records:
                continue
            rows = _rows_for_package(pkg, records)
            all_rows.extend(rows)
            linked += 1

        con.execute("BEGIN")
        con.execute("DELETE FROM bridge_package_pub WHERE match_method = 'citation_file'")
        if all_rows:
            placeholders = ", ".join("?" for _ in _INSERT_COLS)
            con.executemany(
                f"INSERT INTO bridge_package_pub ({', '.join(_INSERT_COLS)}) "
                f"VALUES ({placeholders})",
                all_rows,
            )
        con.execute("COMMIT")

        counts["linked"] = linked
        counts["rows"] = len(all_rows)
        print(
            f"  bioc: {len(packages)} packages, {linked} linked, "
            f"{len(all_rows)} citation_file rows, {counts['skipped_404']} skipped (404)"
        )
    finally:
        con.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Extract CITATION-file package→manuscript links (bioc repo)."
    )
    ap.add_argument(
        "--repos", nargs="*", choices=["bioc"], help="bioc only (other repos: future work)"
    )
    args = ap.parse_args(argv)
    print("extract_citation_files:")
    run(args.repos)


if __name__ == "__main__":
    main()
