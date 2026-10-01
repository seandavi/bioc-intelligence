"""extract_citation_files — package CITATION → bridge_package_pub (spec §6).

The authoritative description of a package's manuscript(s) is its CITATION file.
We read it from package *source* on the ``bioconductor-source`` GitHub org (the
git.bioconductor.org replacement; repo = package name, branch ``devel``) via
unauthenticated raw fetches — no API, no token:

- ``inst/CITATION`` — every DOI in the file, including ones only in a bibentry's
  ``textVersion``/``url``/free text, which the rendered page drops.
- ``CITATION.cff`` — only the top-level ``doi`` and ``preferred-citation.doi``;
  its ``references:`` list cites dependencies, not the package's own paper.

When ``inst/CITATION`` isn't on the org (package absent, no file, or a non-``devel``
default branch) we fall back to Bioconductor's rendered
``/packages/release/<repo>/citations/<pkg>/citation.html``. All three are the same
author-asserted authority → ``match_method = 'citation_file'`` (0.9).

DOIs written as ``<doi:…>`` in the DESCRIPTION ``Description:`` field (already in
``dim_package.description``; no fetch) become ``match_method = 'description_doi'``
(0.8): Description often cites related work rather than the package's own paper.

work_id is the normalised DOI; enrich_from_lake/build_marts reconcile DOI-keyed
rows to the PMID spine. A 404 anywhere is a skip, never a failure.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor

import yaml

from .. import db
from ..config import BIOC_BASE, REPOS
from ..doi import find_dois
from ..http import HttpError, get_text

SOURCE_BASE = "https://raw.githubusercontent.com/bioconductor-source"
_METHODS = {"citation_file": 0.9, "description_doi": 0.8}
_INSERT_COLS = ["package_name", "repo", "work_id", "role", "match_method", "confidence"]
# Each package costs 2-3 small GETs; serial is ~30 min for ~3.8k packages.
_WORKERS = 16


def source_url(package: str, path: str) -> str:
    return f"{SOURCE_BASE}/{package}/devel/{path}"


def citation_url(package: str, repo: str = "bioc") -> str:
    """Rendered-HTML citation page for ``package`` in ``repo`` (the fallback)."""
    return f"{BIOC_BASE}/packages/release/{repo}/citations/{package}/citation.html"


def parse_cff(text: str) -> list[str]:
    """Own-paper DOIs from a CITATION.cff: top-level ``doi`` + ``preferred-citation.doi``."""
    try:
        cff = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(cff, dict):
        return []
    pref = cff.get("preferred-citation")
    values = [cff.get("doi"), pref.get("doi") if isinstance(pref, dict) else None]
    return find_dois(" ".join(str(v) for v in values if v))


def _fetch(url: str) -> str | None:
    try:
        return get_text(url)
    except HttpError:
        return None


def _citation_dois(package: str, repo: str) -> tuple[str, list[str]]:
    """(source, DOIs) for one package; source is 'inst' | 'rendered' | 'none'."""
    text = _fetch(source_url(package, "inst/CITATION"))
    source = "inst"
    if text is None:
        text = _fetch(citation_url(package, repo))
        source = "rendered" if text is not None else "none"
    dois = find_dois(text)
    cff = _fetch(source_url(package, "CITATION.cff"))
    if cff is not None:
        dois += [d for d in parse_cff(cff) if d not in dois]
    return source, dois


def run(repos: list[str] | None = None) -> dict[str, int]:
    """Extract CITATION + Description DOI linkages for ``repos`` (default: all four)."""
    keys = repos or list(REPOS)
    con = db.connect()
    db.init_schema(con)
    counts: dict[str, int] = {"packages": 0, "rows": 0}
    try:
        packages = con.execute(
            "SELECT package_name, repo, description FROM dim_package "
            "WHERE list_contains(?, repo) ORDER BY repo, package_name",
            [keys],
        ).fetchall()
        counts["packages"] = len(packages)
        if not packages:
            print("  no packages in dim_package — run extract-packages first")
            return counts

        with ThreadPoolExecutor(_WORKERS) as pool:
            results = list(pool.map(lambda p: _citation_dois(p[0], p[1]), packages))

        rows: list[list] = []
        for (pkg, repo, description), (source, cit_dois) in zip(packages, results, strict=True):
            counts[f"source_{source}"] = counts.get(f"source_{source}", 0) + 1
            for doi in cit_dois:
                rows.append([pkg, repo, doi, "primary", "citation_file", _METHODS["citation_file"]])
            for doi in find_dois(description):
                if doi not in cit_dois:
                    rows.append(
                        [pkg, repo, doi, "primary", "description_doi",
                         _METHODS["description_doi"]]
                    )

        con.execute("BEGIN")
        con.execute(
            "DELETE FROM bridge_package_pub "
            "WHERE list_contains(?, match_method) AND list_contains(?, repo)",
            [list(_METHODS), keys],
        )
        if rows:
            placeholders = ", ".join("?" for _ in _INSERT_COLS)
            con.executemany(
                f"INSERT INTO bridge_package_pub ({', '.join(_INSERT_COLS)}) "
                f"VALUES ({placeholders})",
                rows,
            )
        con.execute("COMMIT")

        counts["rows"] = len(rows)
        for key in keys:
            for method in _METHODS:
                linked = {r[0] for r in rows if r[1] == key and r[4] == method}
                n = sum(1 for r in rows if r[1] == key and r[4] == method)
                print(f"  {key}: {method} {len(linked)} packages, {n} rows")
        print(
            f"  {len(packages)} packages; CITATION source: "
            + ", ".join(f"{k.removeprefix('source_')}={v}" for k, v in sorted(counts.items())
                        if k.startswith("source_"))
        )
    finally:
        con.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Extract CITATION / Description DOI package→manuscript links."
    )
    ap.add_argument("--repos", nargs="*", choices=list(REPOS), help="default: all four")
    args = ap.parse_args(argv)
    print("extract_citation_files:")
    run(args.repos)


if __name__ == "__main__":
    main()
