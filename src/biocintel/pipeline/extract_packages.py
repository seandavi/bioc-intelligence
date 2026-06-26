"""extract_packages — fetch & parse VIEWS for each repo → dim_package(_version).

Bioconductor-native, no lake. A single VIEWS snapshot can't reveal a package's
*first* release, so ``first_seen_release`` is left NULL until version history
(git tags / multi-release backfill) lands; ``latest_release`` is the snapshot's
release. Dimensions are rebuilt per run via INSERT OR REPLACE (spec §5).
"""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime

import duckdb

from .. import db
from ..config import REPOS, ReleaseConfig, Repo, fetch_release_config, views_url
from ..dcf import parse_dcf, parse_maintainer, split_list
from ..http import get_text

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>,]+")
# Bioconductor mints a self-DOI for every package's landing page; it is not a
# describing manuscript, so we never record it as source_doi.
_BIOC_SELF_DOI_PREFIX = "10.18129/"


def _extract_doi(*fields: str | None) -> str | None:
    for f in fields:
        if not f:
            continue
        for m in _DOI_RE.finditer(f):
            doi = m.group(0).rstrip(".,;)")
            if not doi.startswith(_BIOC_SELF_DOI_PREFIX):
                return doi
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


def _records_for_repo(repo: Repo, *, devel: bool, cfg: ReleaseConfig):
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
        }
        ver = {
            "package_name": name,
            "repo": repo.key,
            "version": version,
            "bioc_release": bioc_release,
            "release_date": _parse_release_date(cfg.release_dates.get(bioc_release)),
            "r_version": cfg.r_versions.get(bioc_release),
            "in_devel": devel,
        }
        yield pkg, ver


_PKG_COLS = [
    "package_name", "repo", "first_seen_release", "latest_release", "maintainer",
    "maintainer_email", "maintainer_ror", "title", "description", "biocviews",
    "url", "bug_reports", "source_doi",
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


def run(repos: list[str] | None = None, *, devel: bool = False) -> dict[str, int]:
    """Extract packages for ``repos`` (default: all four) into the DuckDB store."""
    keys = repos or list(REPOS)
    cfg = fetch_release_config()
    con = db.connect()
    db.init_schema(con)
    counts: dict[str, int] = {}
    try:
        for key in keys:
            repo = REPOS[key]
            channels = [False, True] if devel else [False]
            pkgs, vers = [], []
            for ch in channels:
                for pkg, ver in _records_for_repo(repo, devel=ch, cfg=cfg):
                    pkgs.append(pkg)
                    vers.append(ver)
            con.execute("BEGIN")
            _upsert(con, "dim_package", _PKG_COLS, pkgs)
            _upsert(con, "dim_package_version", _VER_COLS, vers)
            con.execute("COMMIT")
            counts[key] = len(pkgs)
            print(f"  {key}: {len(pkgs)} packages, {len(vers)} version rows")
    finally:
        con.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Extract Bioconductor package metadata (VIEWS).")
    ap.add_argument("--repos", nargs="*", choices=list(REPOS), help="default: all four")
    ap.add_argument("--devel", action="store_true", help="also fetch the devel channel")
    args = ap.parse_args(argv)
    print("extract_packages:")
    run(args.repos, devel=args.devel)


if __name__ == "__main__":
    main()
