"""ELIXIR Research Software Ecosystem (RSEc) flag + bio.tools id for ``dim_package`` (#93).

Reads file paths only, from a blob-less shallow clone of the RSEc content repo: the
``imports/bioconductor`` folder says which packages RSEc lists, and ``data/<id>/`` folders
holding both ``<id>.bioconductor.json`` and ``<id>.biotools.json`` give the bio.tools id.
RSEc re-imports Bioconductor weekly (cron ``0 0 * * 0``, the ``bioconductor`` job in the
content repo's ``.github/workflows/import.yaml``).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Iterable

import duckdb

from .config import RSEC_GIT_URL

_IMPORT_DIR = "imports/bioconductor/"
_IMPORT_SUFFIX = ".bioconductor.json"
_ID_PREFIX = "bioconductor-"


def fetch_rsec_paths(timeout: float = 60.0) -> list[str]:
    """Every path under data/ and imports/bioconductor/ at RSEc HEAD (no file contents)."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout",
             RSEC_GIT_URL, tmp],
            check=True, capture_output=True, text=True, timeout=timeout, env=env,
        )
        out = subprocess.run(
            ["git", "-C", tmp, "ls-tree", "-r", "--name-only", "HEAD",
             "data", "imports/bioconductor"],
            check=True, capture_output=True, text=True, timeout=timeout, env=env,
        )
    return out.stdout.splitlines()


def parse_rsec_paths(paths: Iterable[str]) -> dict[str, tuple[bool, str | None]]:
    """{lowercased package: (in imports/bioconductor, bio.tools id or None)} per the pick rule."""
    listed: set[str] = set()
    files: set[tuple[str, str]] = set()  # (data/<folder>, file name)
    for path in paths:
        if path.startswith(_IMPORT_DIR) and path.endswith(_IMPORT_SUFFIX):
            listed.add(path[len(_IMPORT_DIR):-len(_IMPORT_SUFFIX)])
        elif path.startswith("data/") and path.count("/") == 2:
            _, folder, name = path.split("/")
            files.add((folder, name))
    ids: dict[str, list[str]] = {}
    for folder, name in sorted(files):
        if name == f"{folder}.bioconductor.json" and (folder, f"{folder}.biotools.json") in files:
            ids.setdefault(folder.removeprefix(_ID_PREFIX), []).append(folder)
    # Two qualified ids: prefer the unprefixed (curated, older) one.
    return {
        key: (
            key in listed,
            min(ids[key], key=lambda i: i.startswith(_ID_PREFIX)) if key in ids else None,
        )
        for key in listed | ids.keys()
    }


def update_dim_package(
    con: duckdb.DuckDBPyConnection, flags: dict[str, tuple[bool, str | None]]
) -> int:
    """Set dim_package.in_elixir_rsec / biotools_id for every row from ``flags``.

    Returns the number of rows flagged.
    """
    con.execute("BEGIN")
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _rsec (name VARCHAR, in_rsec BOOLEAN, biotools_id VARCHAR)"
    )
    con.executemany("INSERT INTO _rsec VALUES (?, ?, ?)", [[k, *v] for k, v in flags.items()])
    con.execute(
        """
        UPDATE dim_package SET
            in_elixir_rsec = COALESCE(
                (SELECT r.in_rsec FROM _rsec r WHERE r.name = lower(package_name)), FALSE),
            biotools_id    = (SELECT r.biotools_id FROM _rsec r WHERE r.name = lower(package_name))
        """
    )
    con.execute("DROP TABLE _rsec")
    con.execute("COMMIT")
    return con.execute(
        "SELECT count(*) FILTER (WHERE in_elixir_rsec) FROM dim_package"
    ).fetchone()[0]


def refresh_dim_package(con: duckdb.DuckDBPyConnection) -> int | None:
    """Best-effort fetch → parse → update; None (values untouched) when skipped.

    Skips on a fetch failure, a listing with no Bioconductor imports, or a listing that shrank
    below half of the stored counts (likely an upstream reorganisation, not real removals).
    """
    try:
        paths = fetch_rsec_paths()
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  ELIXIR RSEc listing unavailable ({exc}); skipped")
        return None
    flags = parse_rsec_paths(paths)
    n_listed = sum(in_rsec for in_rsec, _ in flags.values())
    n_ids = sum(biotools_id is not None for _, biotools_id in flags.values())
    if not n_listed:
        print("  ELIXIR RSEc listing has no Bioconductor imports; skipped")
        return None
    stored_listed, stored_ids = con.execute(
        "SELECT count(*) FILTER (WHERE in_elixir_rsec), count(biotools_id) FROM dim_package"
    ).fetchone()
    # ponytail: parsed counts include names not in dim_package, so this floor only errs lenient.
    if n_listed < stored_listed / 2 or n_ids < stored_ids / 2:
        print(f"  ELIXIR RSEc listing shrank: {n_listed} listed / {n_ids} bio.tools ids, "
              f"store has {stored_listed} / {stored_ids}; skipped")
        return None
    n = update_dim_package(con, flags)
    k = con.execute("SELECT count(*) FROM dim_package WHERE biotools_id IS NOT NULL").fetchone()[0]
    print(f"  ELIXIR RSEc: {n} packages listed, {k} with a bio.tools id")
    return n
