"""extract_downloads — per-repo aggregate stats tabs → fact_download.

The aggregate file (``<stats_file>_pkg_stats.tab``) has one row per
(package, year, month) plus ``Month=all`` subtotals we drop. ``distinct IPs`` is
the defensible usage proxy; rows are tagged with ``methodology_era`` (spec §6).

NOTE (2026-06): every documented stats ``.tab`` URL currently 404s site-wide —
collateral damage from the BioC 3.23 site redesign. This module mirrors
``BiocPkgTools``' own ``.filter_http_error`` behaviour: a missing repo is logged
and skipped, never fatal. The parser is exercised by unit tests against a fixture
until the endpoint returns.
"""

from __future__ import annotations

import argparse
from datetime import date

import duckdb

from .. import db
from ..config import REPOS, Repo, methodology_era, stats_url
from ..http import HttpError, get_text

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

_FACT_COLS = [
    "package_name", "repo", "year", "month", "distinct_ips", "downloads",
    "methodology_era", "_snapshot",
]


def parse_stats_tab(text: str, repo_key: str, snapshot: date) -> list[dict]:
    """Parse a Bioconductor ``*_pkg_stats.tab`` into fact_download rows.

    Pure (no IO) so it is unit-testable. Drops the ``Month=all`` subtotal rows.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    header = lines[0].split()
    idx = {name: i for i, name in enumerate(header)}
    try:
        i_pkg, i_year, i_month = idx["Package"], idx["Year"], idx["Month"]
        i_ips, i_dl = idx["Nb_of_distinct_IPs"], idx["Nb_of_downloads"]
    except KeyError as exc:  # unexpected layout — fail loud, don't guess
        raise ValueError(f"unexpected stats header: {header}") from exc

    rows: list[dict] = []
    for ln in lines[1:]:
        f = ln.split()
        if len(f) < len(header):
            continue
        month = _MONTHS.get(f[i_month])
        if month is None:  # 'all' subtotal or unknown
            continue
        year = int(f[i_year])
        rows.append({
            "package_name": f[i_pkg],
            "repo": repo_key,
            "year": year,
            "month": month,
            "distinct_ips": int(f[i_ips]),
            "downloads": int(f[i_dl]),
            "methodology_era": methodology_era(year, month),
            "_snapshot": snapshot,
        })
    return rows


def _load(con: duckdb.DuckDBPyConnection, repo: Repo, snapshot: date) -> int:
    rows = parse_stats_tab(get_text(stats_url(repo)), repo.key, snapshot)
    # Idempotent within a snapshot: clear this repo's rows for today, then append.
    con.execute(
        "DELETE FROM fact_download WHERE repo = ? AND _snapshot = ?", [repo.key, snapshot]
    )
    con.executemany(
        f"INSERT INTO fact_download ({', '.join(_FACT_COLS)}) "
        f"VALUES ({', '.join('?' for _ in _FACT_COLS)})",
        [[r[c] for c in _FACT_COLS] for r in rows],
    )
    return len(rows)


def run(repos: list[str] | None = None) -> dict[str, int]:
    keys = repos or list(REPOS)
    snapshot = date.today()
    con = db.connect()
    db.init_schema(con)
    counts: dict[str, int] = {}
    try:
        for key in keys:
            repo = REPOS[key]
            try:
                n = _load(con, repo, snapshot)
                counts[key] = n
                print(f"  {key}: {n} download rows")
            except HttpError as exc:
                counts[key] = 0
                print(f"  {key}: SKIPPED — stats unavailable ({exc.status}). {stats_url(repo)}")
    finally:
        con.close()
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Extract Bioconductor download stats.")
    ap.add_argument("--repos", nargs="*", choices=list(REPOS), help="default: all four")
    args = ap.parse_args(argv)
    print("extract_downloads:")
    run(args.repos)


if __name__ == "__main__":
    main()
