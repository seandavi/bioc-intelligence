"""DuckDB connection + schema bootstrap helpers.

One file is the canonical store (spec §2). These helpers keep the pipeline
modules free of connection boilerplate; each module opens the DB, writes its
tables, and closes.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import duckdb

from .config import DB_PATH


def connect(
    path: Path | str | None = None, *, read_only: bool = False
) -> duckdb.DuckDBPyConnection:
    """Open (creating parent dirs as needed) the canonical DuckDB store."""
    p = Path(path) if path is not None else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(p), read_only=read_only)


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create all canonical tables if absent (idempotent)."""
    ddl = resources.files("biocintel").joinpath("schema.sql").read_text(encoding="utf-8")
    con.execute(ddl)
