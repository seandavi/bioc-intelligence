"""Offline test of the published views file: built over fixture Parquet in a temp dir."""

import json

import duckdb

from biocintel import db
from biocintel.pipeline.build_marts import _MART_SQL, _MARTS, HONEST_VIEWS, write_views_db


def test_views_db_over_fixture_marts(tmp_path):
    con = db.connect(":memory:")
    db.init_schema(con)
    con.execute(_MART_SQL)  # empty marts with the current shape
    for m in _MARTS:
        con.execute(f"COPY {m} TO '{tmp_path / m}.parquet' (FORMAT parquet)")
    con.close()

    out = tmp_path / "pub" / "bioc-intelligence.duckdb"
    # Local dir as the public base keeps it offline; every column needs a definition.
    views = write_views_db(out, str(tmp_path), tmp_path, snapshot="2026-10-01")
    assert len(views) == len(_MARTS) + len(HONEST_VIEWS)

    c = duckdb.connect()
    c.execute(f"ATTACH '{out}' AS bi (READ_ONLY)")  # a client alias, not the build name
    tags = c.execute(
        "SELECT tags FROM duckdb_databases() WHERE database_name = 'bi'"
    ).fetchone()[0]
    assert tags["storage_version"].startswith("v1.0.0")
    assert c.execute(
        "SELECT count(*) FROM duckdb_views() WHERE database_name = 'bi'"
    ).fetchone()[0] == len(views)
    comment = c.execute(
        "SELECT comment FROM duckdb_views() WHERE database_name = 'bi' "
        "AND view_name = 'package_pubs_confident'"
    ).fetchone()[0]
    assert "Snapshot 2026-10-01" in comment
    assert c.execute(
        "SELECT count(*) FROM duckdb_columns() WHERE database_name = 'bi' AND comment IS NULL"
    ).fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM bi.package_impact_ranked").fetchone() == (0,)

    dp = json.loads((out.parent / "datapackage.json").read_text())
    assert {r["name"] for r in dp["resources"]} == set(_MARTS)
