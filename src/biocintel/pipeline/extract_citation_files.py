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

CITATION files rotate (edgeR's devel CITATION lists only its 2025 paper; 3.16 listed
the 2010 and 2012 ones), so we also union the DOIs on every past release's rendered
``/packages/<ver>/<repo>/citations/<pkg>/citation.html``. Those pages are immutable,
so they're always cached (404s included). ``source_release`` records where each DOI
came from: ``'devel'``, ``'release'`` (fallback page) or the newest past release.

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
from ..config import BIOC_BASE, REPOS, fetch_release_config
from ..doi import find_dois
from ..http import HttpError, get_text

SOURCE_BASE = "https://raw.githubusercontent.com/bioconductor-source"
_METHODS = {"citation_file": 0.9, "description_doi": 0.8}
_INSERT_COLS = [
    "package_name", "repo", "work_id", "role", "match_method", "confidence", "source_release",
]
# Each package costs 2-3 small GETs plus one per past release (cached forever after the
# first run); serial is ~30 min for ~3.8k packages without the past-release pass.
_WORKERS = 16


def source_url(package: str, path: str) -> str:
    return f"{SOURCE_BASE}/{package}/devel/{path}"


def citation_url(package: str, repo: str = "bioc", release: str = "release") -> str:
    """Rendered-HTML citation page for ``package`` in ``repo`` at ``release``."""
    path = REPOS[repo].views_path  # 'data/experiment', not the 'data-experiment' key
    return f"{BIOC_BASE}/packages/{release}/{path}/citations/{package}/citation.html"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def past_releases(since: str = "3.0") -> list[str]:
    """Every release from ``since`` up to (excluding) the current one, newest first."""
    cfg = fetch_release_config()
    current = _version_key(cfg.release_version)
    # ponytail: the range fallback assumes the 3.x line; config.yaml has release_dates today
    versions = cfg.release_dates or [f"3.{i}" for i in range(current[1])]
    return sorted(
        (v for v in versions if _version_key(since) <= _version_key(v) < current),
        key=_version_key, reverse=True,
    )


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


def _fetch(url: str, *, force_cache: bool = False) -> str | None:
    try:
        return get_text(url, force_cache=force_cache)
    except HttpError:
        return None


def _citation_dois(
    package: str, repo: str, releases: list[str]
) -> tuple[str, list[tuple[str, str]]]:
    """(source, [(DOI, source_release)]) for one package; source is 'inst' | 'rendered' |
    'none' (the current CITATION). Each DOI is kept once, from its first source:
    devel, then the release fallback, then ``releases`` in the order given."""
    text = _fetch(source_url(package, "inst/CITATION"))
    source, release = "inst", "devel"
    if text is None:
        text = _fetch(citation_url(package, repo))
        source, release = ("rendered" if text is not None else "none"), "release"
    found = [(d, release) for d in find_dois(text)]
    cff = _fetch(source_url(package, "CITATION.cff"))
    if cff is not None:
        found += [(d, "devel") for d in parse_cff(cff)]
    for ver in releases:
        page = _fetch(citation_url(package, repo, ver), force_cache=True)
        found += [(d, ver) for d in find_dois(page)]
    first: dict[str, str] = {}
    for doi, rel in found:
        first.setdefault(doi, rel)
    return source, list(first.items())


def build_rows(packages: list[tuple], results: list[tuple[str, list[tuple[str, str]]]]):
    """bridge_package_pub rows (``_INSERT_COLS`` order) from ``_citation_dois`` results."""
    rows: list[list] = []
    for (pkg, repo, description), (_, cit) in zip(packages, results, strict=True):
        for doi, rel in cit:
            rows.append(
                [pkg, repo, doi, "primary", "citation_file", _METHODS["citation_file"], rel]
            )
        cit_dois = {d for d, _ in cit}
        for doi in find_dois(description):
            if doi not in cit_dois:
                rows.append(
                    [pkg, repo, doi, "primary", "description_doi",
                     _METHODS["description_doi"], None]
                )
    return rows


def run(
    repos: list[str] | None = None,
    packages: list[str] | None = None,
    releases: list[str] | None = None,
) -> dict[str, int]:
    """Extract CITATION + Description DOI linkages for ``repos`` (default: all four).

    ``packages`` bounds the run (only their rows are replaced); ``releases`` is the
    past-release list to union (default: :func:`past_releases`; ``[]`` skips it).
    """
    keys = repos or list(REPOS)
    releases = past_releases() if releases is None else sorted(
        releases, key=_version_key, reverse=True
    )
    con = db.connect()
    db.init_schema(con)
    counts: dict[str, int] = {"packages": 0, "rows": 0}
    try:
        pkgs = con.execute(
            "SELECT package_name, repo, description FROM dim_package "
            "WHERE list_contains(?, repo) "
            "AND (?::VARCHAR[] IS NULL OR list_contains(?, package_name)) "
            "ORDER BY repo, package_name",
            [keys, packages, packages],
        ).fetchall()
        counts["packages"] = len(pkgs)
        if not pkgs:
            print("  no packages in dim_package — run extract-packages first")
            return counts

        with ThreadPoolExecutor(_WORKERS) as pool:
            results = list(pool.map(lambda p: _citation_dois(p[0], p[1], releases), pkgs))
        for source, _ in results:
            counts[f"source_{source}"] = counts.get(f"source_{source}", 0) + 1
        rows = build_rows(pkgs, results)

        con.execute("BEGIN")
        con.execute(
            "DELETE FROM bridge_package_pub "
            "WHERE list_contains(?, match_method) AND list_contains(?, repo) "
            "AND (?::VARCHAR[] IS NULL OR list_contains(?, package_name))",
            [list(_METHODS), keys, packages, packages],
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
        past = [r for r in rows if r[6] in releases]
        counts["past_release_rows"] = len(past)
        print(
            f"  past releases ({len(releases)}): {len(past)} extra DOIs on "
            f"{len({(r[0], r[1]) for r in past})} packages"
        )
        print(
            f"  {len(pkgs)} packages; CITATION source: "
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
    add_arguments(ap)
    args = ap.parse_args(argv)
    print("extract_citation_files:")
    run(args.repos, args.packages, args.releases)


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--repos", nargs="*", choices=list(REPOS), help="default: all four")
    ap.add_argument("--packages", type=_csv, help="comma-separated; default: all")
    ap.add_argument(
        "--releases", type=_csv,
        help="comma-separated past releases to union; default: 3.0..current-1; '' skips",
    )


if __name__ == "__main__":
    main()
