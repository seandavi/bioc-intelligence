"""``biocintel`` CLI — thin dispatch over the framework-free pipeline modules."""

from __future__ import annotations

import argparse

from . import db
from .pipeline import build_marts, extract_downloads, extract_packages


def _init_db(_args) -> None:
    con = db.connect()
    db.init_schema(con)
    con.close()
    print(f"initialized schema in {db.DB_PATH}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="biocintel", description="Bioconductor Intelligence pipeline."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create the DuckDB store + schema")

    p_pkg = sub.add_parser("extract-packages", help="VIEWS -> dim_package(_version)")
    p_pkg.add_argument("--repos", nargs="*", choices=list(extract_packages.REPOS))
    p_pkg.add_argument("--devel", action="store_true")

    p_dl = sub.add_parser("extract-downloads", help="stats tabs -> fact_download")
    p_dl.add_argument("--repos", nargs="*", choices=list(extract_downloads.REPOS))

    sub.add_parser("build-marts", help="derive mart_* and export Parquet")
    sub.add_parser("all", help="extract-packages + extract-downloads + build-marts")

    args = ap.parse_args(argv)

    if args.cmd == "init-db":
        _init_db(args)
    elif args.cmd == "extract-packages":
        extract_packages.run(args.repos, devel=args.devel)
    elif args.cmd == "extract-downloads":
        extract_downloads.run(args.repos)
    elif args.cmd == "build-marts":
        build_marts.run()
    elif args.cmd == "all":
        extract_packages.run(None, devel=False)
        extract_downloads.run(None)
        build_marts.run()


if __name__ == "__main__":
    main()
