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

# dim_package columns added with the VIEWS dependency/maintenance fields (#39).
_DIM_PACKAGE_VIEWS_COLUMNS = [
    ("depends", "VARCHAR[]"),
    ("imports", "VARCHAR[]"),
    ("suggests", "VARCHAR[]"),
    ("linking_to", "VARCHAR[]"),
    ("depends_on_me", "VARCHAR[]"),
    ("imports_me", "VARCHAR[]"),
    ("suggests_me", "VARCHAR[]"),
    ("links_to_me", "VARCHAR[]"),
    ("dependency_count", "INTEGER"),
    ("git_last_commit_date", "DATE"),
    ("date_publication", "DATE"),
    ("package_status", "VARCHAR"),
    ("has_readme", "BOOLEAN"),
    ("has_news", "BOOLEAN"),
    ("has_install", "BOOLEAN"),
    ("has_license", "BOOLEAN"),
    ("n_vignettes", "INTEGER"),
    ("vignette_titles", "VARCHAR[]"),
    ("license", "VARCHAR"),
    ("needs_compilation", "BOOLEAN"),
]


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
    # Columns added after a table first shipped; CREATE IF NOT EXISTS won't add them.
    con.execute("ALTER TABLE bridge_package_pub ADD COLUMN IF NOT EXISTS source_release VARCHAR")
    for name, typ in _DIM_PACKAGE_VIEWS_COLUMNS:
        con.execute(f"ALTER TABLE dim_package ADD COLUMN IF NOT EXISTS {name} {typ}")
