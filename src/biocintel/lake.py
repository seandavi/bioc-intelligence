"""Attach the shared cdsci-lake (read-only) alongside the local store.

Phase-2 enrichment is cross-catalog DuckDB SQL: the lake supplies reference
corpora (OpenAlex, iCite, RePORTER, PMC) read-only as catalog ``lake``; we attach
the local biocintel store as ``bi`` and join across them, writing results back
into ``bi`` only. The lake is never mutated.

Requires the cdsci-lake read client and its credentials (Google Secret Manager
via ``gcloud``); set ``CU_OPENALEX_LAKE_BACKEND=postgres`` for the shared lake.
This module is import-safe without the client installed — the dependency is only
touched inside :func:`connect_with_lake`, so the offline test suite and CI never
need the lake.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from . import db
from .config import DB_PATH

LAKE_ALIAS = "lake"  # set by cdsci-lake's read client
LOCAL_ALIAS = "bi"


def connect_with_lake(biocintel_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Open a connection that sees both the lake (``lake``) and local store (``bi``).

    The local schema is ensured first so enrichment can write its tables.
    """
    try:
        from cdsci.lake import lake_connect
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only with lake installed
        raise RuntimeError(
            "Phase-2 enrichment needs the cdsci-lake read client. Install it from the "
            "sibling checkout (`uv pip install -e ../cdsci-lake`) and set "
            "CU_OPENALEX_LAKE_BACKEND=postgres."
        ) from exc

    path = Path(biocintel_path or DB_PATH)
    # Ensure local tables exist before we attach the file read-write for writing.
    bootstrap = db.connect(path)
    db.init_schema(bootstrap)
    bootstrap.close()

    con = lake_connect(read_only=True)  # attaches DuckLake as `lake`
    con.execute(f"ATTACH '{path}' AS {LOCAL_ALIAS}")
    return con
