"""Render the static JSON API and shields.io badges from the published Parquet marts (#52).

Runs at Pages deploy against ``frontend/public/data``; the output lives only in ``dist`` and is
never committed. Reads Parquet with DuckDB, nothing else (no lake, no store):

- ``<out>/v1/index.json``: snapshot, counts, URL patterns, every package name and grant id.
- ``<out>/v1/package/<name>.json``: directory + impact row, papers, grants, people, funders,
  dependencies (null until ``mart_package_dependency`` is published) and the last 36 months of
  downloads.
- ``<out>/v1/grant/<grant_id>.json``: the grant row and its packages with their impact.
- ``<badges>/<name>/{downloads,citations}.json`` in the shields.io endpoint schema.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path

import duckdb

# R package names: letters, digits and dots, starting with a letter. Anything else is skipped
# rather than written, since the name becomes a file path.
_SAFE_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9.]*")
_SAFE_GRANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# The paper links the site counts by default (frontend lib/confidence.ts HIGH_CONFIDENCE_SQL).
CONFIDENT_METHODS = ("doi", "citation_file")
MONTHS_OF_DOWNLOADS = 36

URL_PATTERNS = {
    "index": "api/v1/index.json",
    "package": "api/v1/package/{package_name}.json",
    "grant": "api/v1/grant/{grant_id}.json",
    "badge_downloads": "badges/{package_name}/downloads.json",
    "badge_citations": "badges/{package_name}/citations.json",
}


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _src(marts: Path, mart: str) -> str:
    return "read_parquet('{}')".format(str(marts / f"{mart}.parquet").replace("'", "''"))


def _write(path: Path, obj) -> int:
    data = json.dumps(obj, separators=(",", ":"), sort_keys=True, default=str).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


def humanize(n: float) -> str:
    """12345 -> '12.3k'; 999 -> '999'; 2_500_000 -> '2.5M'."""
    if n >= 999_950:
        return f"{n / 1e6:.1f}M"
    if n >= 999.5:
        return f"{n / 1e3:.1f}k"
    return str(round(n))


def badges(impact: dict | None, citations: int) -> dict[str, dict]:
    """shields.io endpoint payloads: monthly-average distinct IPs and confident citations."""
    ips = (impact or {}).get("distinct_ips_trailing_12mo") or 0
    # ponytail: a package younger than 12 months is averaged over 12 too (understates it).
    per_month = ips / 12
    return {
        "downloads": {
            "schemaVersion": 1,
            "label": "distinct IPs",
            "message": f"{humanize(per_month)}/mo avg",
            "color": "blue" if per_month else "lightgrey",
        },
        "citations": {
            "schemaVersion": 1,
            "label": "citations",
            "message": humanize(citations),
            "color": "blue" if citations else "lightgrey",
        },
    }


def _strip_key(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in ("package_name", "repo")}


def run(marts: Path, out: Path, badges_dir: Path) -> dict:
    t0 = time.monotonic()
    manifest_path = marts / "manifest.json"
    snapshot = (
        json.loads(manifest_path.read_text()).get("snapshot") if manifest_path.exists() else None
    )
    con = duckdb.connect()

    def by_package(mart: str, where: str = "") -> dict[tuple, list[dict]]:
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in _rows(con, f"SELECT * FROM {_src(marts, mart)} {where}"):
            groups[(r["package_name"], r["repo"])].append(_strip_key(r))
        return groups

    directory = _rows(
        con, f"SELECT * FROM {_src(marts, 'mart_package_directory')} ORDER BY package_name, repo"
    )
    impact = {
        (r["package_name"], r["repo"]): r
        for r in _rows(con, f"SELECT * FROM {_src(marts, 'mart_package_impact')}")
    }
    papers = by_package("mart_package_work", "ORDER BY confidence DESC, year DESC, work_id")
    people = by_package("mart_package_person", "ORDER BY NOT is_maintainer, name")
    funders = by_package("mart_package_funder", "ORDER BY funder_name, grant_number")
    deps = None
    if (marts / "mart_package_dependency.parquet").exists():
        deps = defaultdict(lambda: defaultdict(list))
        for r in _rows(
            con, f"SELECT * FROM {_src(marts, 'mart_package_dependency')} ORDER BY kind, dep"
        ):
            deps[(r["package_name"], r["repo"])][r["kind"]].append(r["dep"])
    monthly = by_package(
        "mart_package_downloads_monthly",
        f"""WHERE year * 12 + month > (
                SELECT MAX(year * 12 + month) - {MONTHS_OF_DOWNLOADS}
                FROM {_src(marts, 'mart_package_downloads_monthly')})
            ORDER BY year, month""",
    )
    grants = _rows(con, f"SELECT * FROM {_src(marts, 'mart_grant_attribution')} ORDER BY grant_id")
    skipped = [str(g["grant_id"]) for g in grants if not _SAFE_GRANT.fullmatch(g["grant_id"] or "")]
    grants = [g for g in grants if str(g["grant_id"]) not in skipped]
    grants_of: dict[str, list[dict]] = defaultdict(list)
    for g in grants:
        for name in g["package_names"] or []:
            grants_of[name].append({k: g[k] for k in ("grant_id", "agency", "title")})
    con.close()

    n_files = n_bytes = 0
    written: list[str] = []
    seen: set[str] = set()
    for d in directory:
        name, key = d["package_name"], (d["package_name"], d["repo"])
        # A name in two repos would collide on disk; keep the first (none do today).
        if not _SAFE_PACKAGE.fullmatch(name or "") or name in seen:
            skipped.append(str(name))
            continue
        seen.add(name)
        pkg_papers = papers.get(key, [])
        confident = {
            p["work_id"]: p["citation_count"] or 0
            for p in pkg_papers
            if p["match_method"] in CONFIDENT_METHODS
        }
        imp = impact.get(key)
        payload = {
            "snapshot": snapshot,
            "package": d,
            "impact": _strip_key(imp) if imp else None,
            "confident_citations": sum(confident.values()),
            "papers": pkg_papers,
            "grants": grants_of.get(name, []),
            "people": people.get(key, []),
            "funders": funders.get(key, []),
            "dependencies": dict(deps[key]) if deps is not None else None,
            "downloads_monthly": monthly.get(key, []),
        }
        n_bytes += _write(out / "v1" / "package" / f"{name}.json", payload)
        for kind, badge in badges(imp, payload["confident_citations"]).items():
            n_bytes += _write(badges_dir / name / f"{kind}.json", badge)
        n_files += 3
        written.append(name)

    impact_by_name = {k[0]: v for k, v in impact.items()}
    grant_ids: list[str] = []
    for g in grants:
        gid = g["grant_id"]
        payload = {
            "snapshot": snapshot,
            "grant": g,
            "packages": [
                impact_by_name.get(n, {"package_name": n}) for n in g["package_names"] or []
            ],
        }
        n_bytes += _write(out / "v1" / "grant" / f"{gid}.json", payload)
        n_files += 1
        grant_ids.append(gid)

    index = {
        "snapshot": snapshot,
        "counts": {"packages": len(written), "grants": len(grant_ids)},
        "urls": URL_PATTERNS,
        "confident_methods": list(CONFIDENT_METHODS),
        "packages": written,
        "grants": grant_ids,
    }
    n_bytes += _write(out / "v1" / "index.json", index)
    n_files += 1
    summary = {
        "files": n_files,
        "bytes": n_bytes,
        "skipped": skipped,
        "seconds": round(time.monotonic() - t0, 1),
    }
    print(
        f"export-api: {n_files} files, {n_bytes / 1e6:.1f} MB in {summary['seconds']}s "
        f"({len(written)} packages, {len(grant_ids)} grants, {len(skipped)} skipped)"
    )
    return summary


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--marts", type=Path, default=Path("frontend/public/data"))
    p.add_argument("--out", type=Path, default=Path("frontend/dist/api"))
    p.add_argument("--badges", type=Path, default=Path("frontend/dist/badges"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(ap)
    a = ap.parse_args()
    run(a.marts, a.out, a.badges)
