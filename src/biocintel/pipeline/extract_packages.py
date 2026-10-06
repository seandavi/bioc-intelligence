"""extract_packages — fetch & parse VIEWS for each repo → dim_package(_version).

Bioconductor-native, no lake. The current release (and optionally devel) fills
``dim_package``; ``--release``/``--all-releases`` add past releases' VIEWS
(``/packages/<ver>/<repo>/VIEWS``, 1.8 onwards; immutable, so force-cached) to
``dim_package_version`` only. ``first_seen_release`` is the earliest release
loaded for each package, so it means "1.8 or earlier" for packages already in
1.8. Release dates come from the release-announcements table (``dim_release``).
Dimensions are rebuilt per run via INSERT OR REPLACE (spec §5).
"""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime

import duckdb

from .. import db
from ..config import (
    RELEASE_ANNOUNCEMENTS_URL,
    REPOS,
    ReleaseConfig,
    Repo,
    fetch_release_config,
    views_url,
)
from ..dcf import parse_dcf, parse_maintainer, split_list
from ..doi import find_dois
from ..http import HttpError, get_text


def _extract_doi(*fields: str | None) -> str | None:
    for f in fields:
        if dois := find_dois(f):
            return dois[0]
    return None


def _split_urls(value: str | None) -> list[str]:
    if not value:
        return []
    return [u.strip() for u in re.split(r"[,\s]+", value) if u.strip()]


def _parse_release_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_date(raw: str | None) -> date | None:
    """First whitespace token of ``raw`` as a date (VIEWS dates may carry a time)."""
    return _parse_release_date(raw.split()[0]) if raw and raw.split() else None


def parse_release_announcements(html: str) -> dict[str, tuple[date | None, int | None]]:
    """``{release: (release_date, n_software_announced)}`` from the announcements table."""
    out: dict[str, tuple[date | None, int | None]] = {}
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        cells = [
            re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        if len(cells) < 3 or not re.fullmatch(r"\d+\.\d+", cells[0]):
            continue
        try:
            released = datetime.strptime(cells[1], "%B %d, %Y").date()
        except ValueError:
            released = None
        out[cells[0]] = (released, _parse_int(cells[2].replace(",", "")))
    return out


def _parse_bool(raw: str | None) -> bool | None:
    return {"TRUE": True, "YES": True, "FALSE": False, "NO": False}.get((raw or "").strip().upper())


def _parse_int(raw: str | None) -> int | None:
    return int(raw) if raw and raw.strip().isdigit() else None


def _dep_list(raw: str | None) -> list[str]:
    """Package names from a Depends-style field; ``R`` is the interpreter, not a package."""
    return [d for d in split_list(raw) if d != "R"]


def _views_fields(rec: dict[str, str]) -> dict:
    """The dependency, maintenance and docs fields VIEWS carries beyond DESCRIPTION basics."""
    vignettes = [v.strip() for v in rec.get("vignettes", "").split(",") if v.strip()]
    titles = [t.strip() for t in rec.get("vignetteTitles", "").split(",") if t.strip()]
    if len(titles) != len(vignettes):
        # Titles may contain commas; keep the raw string rather than guess a split.
        titles = [rec["vignetteTitles"]] if rec.get("vignetteTitles") else []
    return {
        "depends": _dep_list(rec.get("Depends")),
        "imports": _dep_list(rec.get("Imports")),
        "suggests": _dep_list(rec.get("Suggests")),
        "linking_to": _dep_list(rec.get("LinkingTo")),
        "depends_on_me": split_list(rec.get("dependsOnMe")),
        "imports_me": split_list(rec.get("importsMe")),
        "suggests_me": split_list(rec.get("suggestsMe")),
        "links_to_me": split_list(rec.get("linksToMe")),
        "dependency_count": _parse_int(rec.get("dependencyCount")),
        "git_last_commit_date": _parse_date(rec.get("git_last_commit_date")),
        "date_publication": _parse_date(rec.get("Date/Publication")),
        "package_status": rec.get("PackageStatus") or None,
        "has_readme": _parse_bool(rec.get("hasREADME")),
        "has_news": _parse_bool(rec.get("hasNEWS")),
        "has_install": _parse_bool(rec.get("hasINSTALL")),
        "has_license": _parse_bool(rec.get("hasLICENSE")),
        "n_vignettes": len(vignettes),
        "vignette_titles": titles,
        "license": rec.get("License") or None,
        "needs_compilation": _parse_bool(rec.get("NeedsCompilation")),
    }


def _records_for_repo(repo: Repo, *, devel: bool, cfg: ReleaseConfig, release_date: date | None):
    text = get_text(views_url(repo, devel=devel))
    # Release identity comes from which VIEWS we fetched, not a package's source
    # git_branch (which can be stale for un-rebuilt packages).
    bioc_release = cfg.devel_version if devel else cfg.release_version
    for rec in parse_dcf(text):
        name = rec.get("Package")
        version = rec.get("Version")
        if not name or not version:
            continue
        maint, email = parse_maintainer(rec.get("Maintainer"))
        pkg = {
            "package_name": name,
            "repo": repo.key,
            "first_seen_release": None,
            "latest_release": bioc_release,
            "maintainer": maint,
            "maintainer_email": email,
            "maintainer_ror": None,
            "title": rec.get("Title"),
            "description": rec.get("Description"),
            "biocviews": split_list(rec.get("biocViews")),
            "url": _split_urls(rec.get("URL")),
            "bug_reports": rec.get("BugReports"),
            "source_doi": _extract_doi(rec.get("URL"), rec.get("BugReports")),
            **_views_fields(rec),
        }
        ver = {
            "package_name": name,
            "repo": repo.key,
            "version": version,
            "bioc_release": bioc_release,
            "release_date": release_date,
            "r_version": cfg.r_versions.get(bioc_release),
            "in_devel": devel,
        }
        yield pkg, ver


def _past_version_rows(repo: Repo, release: str, release_date: date | None, r_version: str | None):
    """dim_package_version rows from a past release's VIEWS; [] when that repo didn't exist."""
    try:
        text = get_text(views_url(repo, release=release), force_cache=True)
    except HttpError as exc:
        if exc.status == 404:
            return []
        raise
    # Old VIEWS carry fewer fields; Package and Version are all we need here.
    return [
        {
            "package_name": rec["Package"],
            "repo": repo.key,
            "version": rec["Version"],
            "bioc_release": release,
            "release_date": release_date,
            "r_version": r_version,
            "in_devel": False,
        }
        for rec in parse_dcf(text)
        if rec.get("Package") and rec.get("Version")
    ]


_PKG_COLS = [
    "package_name", "repo", "first_seen_release", "latest_release", "maintainer",
    "maintainer_email", "maintainer_ror", "title", "description", "biocviews",
    "url", "bug_reports", "source_doi",
    "depends", "imports", "suggests", "linking_to", "depends_on_me", "imports_me",
    "suggests_me", "links_to_me", "dependency_count", "git_last_commit_date",
    "date_publication", "package_status", "has_readme", "has_news", "has_install",
    "has_license", "n_vignettes", "vignette_titles", "license", "needs_compilation",
]
_VER_COLS = [
    "package_name", "repo", "version", "bioc_release", "release_date", "r_version", "in_devel",
]


def _upsert(con: duckdb.DuckDBPyConnection, table: str, cols: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    placeholders = ", ".join("?" for _ in cols)
    con.executemany(
        f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        [[r[c] for c in cols] for r in rows],
    )


_FIRST_SEEN_SQL = """
UPDATE dim_package p SET first_seen_release = f.first_seen
FROM (
    SELECT package_name, repo,
           arg_min(bioc_release, string_split(bioc_release, '.')::INT[]) AS first_seen
    FROM dim_package_version GROUP BY package_name, repo
) f
WHERE p.package_name = f.package_name AND p.repo = f.repo
"""


def run(
    repos: list[str] | None = None,
    *,
    devel: bool = False,
    releases: list[str] | None = None,
    all_releases: bool = False,
) -> dict[str, int]:
    """Extract packages for ``repos`` (default: all four) into the DuckDB store.

    ``releases`` (or every announced release with ``all_releases``) adds those past
    releases' VIEWS to ``dim_package_version``; ``dim_package`` stays the current release.
    """
    keys = repos or list(REPOS)
    cfg = fetch_release_config()
    # Not force-cached: the table gains a row every release. Dates only, so never fatal.
    try:
        announced = parse_release_announcements(get_text(RELEASE_ANNOUNCEMENTS_URL))
    except HttpError as exc:
        print(f"  release announcements unavailable ({exc}); dates from config.yaml")
        announced = {}

    def release_date(rel: str) -> date | None:
        return (announced.get(rel) or (None, None))[0] or _parse_release_date(
            cfg.release_dates.get(rel)
        )

    past = list(announced) if all_releases else (releases or [])
    past = [r for r in past if r not in (cfg.release_version, cfg.devel_version)]
    con = db.connect()
    db.init_schema(con)
    counts: dict[str, int] = {}
    try:
        con.executemany(
            "INSERT OR REPLACE INTO dim_release VALUES (?, ?, ?)",
            [[rel, d, n] for rel, (d, n) in announced.items()],
        )
        for key in keys:
            repo = REPOS[key]
            channels = [False, True] if devel else [False]
            pkgs, vers = [], []
            for ch in channels:
                rel = cfg.devel_version if ch else cfg.release_version
                for pkg, ver in _records_for_repo(
                    repo, devel=ch, cfg=cfg, release_date=release_date(rel)
                ):
                    pkgs.append(pkg)
                    vers.append(ver)
            con.execute("BEGIN")
            _upsert(con, "dim_package", _PKG_COLS, pkgs)
            _upsert(con, "dim_package_version", _VER_COLS, vers)
            con.execute("COMMIT")
            counts[key] = len(pkgs)
            print(f"  {key}: {len(pkgs)} packages, {len(vers)} version rows")
        for rel in past:
            vers = [
                v
                for key in keys
                for v in _past_version_rows(
                    REPOS[key], rel, release_date(rel), cfg.r_versions.get(rel)
                )
            ]
            con.execute("BEGIN")
            _upsert(con, "dim_package_version", _VER_COLS, vers)
            con.execute("COMMIT")
            counts[rel] = len(vers)
            print(f"  {rel}: {len(vers)} version rows")
        con.execute(_FIRST_SEEN_SQL)
    finally:
        con.close()
    return counts


def add_release_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--release", action="extend", type=lambda s: [v for v in s.split(",") if v],
        help="past release(s) to add to dim_package_version (repeatable or comma list)",
    )
    ap.add_argument(
        "--all-releases", action="store_true",
        help="add every release on the release-announcements page (VIEWS exist from 1.8)",
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Extract Bioconductor package metadata (VIEWS).")
    ap.add_argument("--repos", nargs="*", choices=list(REPOS), help="default: all four")
    ap.add_argument("--devel", action="store_true", help="also fetch the devel channel")
    add_release_arguments(ap)
    args = ap.parse_args(argv)
    print("extract_packages:")
    run(args.repos, devel=args.devel, releases=args.release, all_releases=args.all_releases)


if __name__ == "__main__":
    main()
