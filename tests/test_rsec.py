"""ELIXIR RSEc flag + bio.tools id (#93): path parsing, dim_package update, best-effort refresh."""

import subprocess
from pathlib import Path

import pytest

from biocintel import db, rsec
from biocintel.pipeline.extract_packages import _PKG_COLS, _upsert

FIXTURE = Path(__file__).parent / "fixtures" / "rsec_ls_tree.txt"


def _paths() -> list[str]:
    return FIXTURE.read_text().splitlines()


def _store():
    con = db.connect(":memory:")
    db.init_schema(con)
    con.executemany(
        "INSERT INTO dim_package (package_name, repo) VALUES (?, ?)",
        [("limma", "bioc"), ("ACE", "bioc"), ("scater", "bioc"),
         ("org.Hs.eg.db", "data-annotation"), ("gone", "bioc")],
    )
    con.execute("UPDATE dim_package SET in_elixir_rsec = TRUE, biotools_id = 'gone' "
                "WHERE package_name = 'gone'")
    return con


def _flags(con):
    return dict(
        (r[0], (r[1], r[2]))
        for r in con.execute(
            "SELECT package_name, in_elixir_rsec, biotools_id FROM dim_package"
        ).fetchall()
    )


def test_parse_rsec_paths_fixture():
    # ace: data/ace is an unrelated tool; alabaster.base: same-name folder ignored;
    # derfinderplot: prefixed folder has no .biotools.json; scater: two ids -> unprefixed.
    assert rsec.parse_rsec_paths(_paths()) == {
        "ace": (True, "bioconductor-ace"),
        "alabaster.base": (True, "bioconductor-alabaster.base"),
        "derfinderplot": (True, "derfinderplot"),
        "limma": (True, "limma"),
        "scater": (True, "scater"),
    }


def test_update_dim_package_sets_and_resets():
    con = _store()
    assert rsec.update_dim_package(con, rsec.parse_rsec_paths(_paths())) == 3
    assert _flags(con) == {
        "limma": (True, "limma"),
        "ACE": (True, "bioconductor-ace"),
        "scater": (True, "scater"),
        "org.Hs.eg.db": (False, None),
        "gone": (False, None),
    }


@pytest.mark.parametrize(
    "exc",
    [
        subprocess.TimeoutExpired("git", 60),
        FileNotFoundError("git"),
        subprocess.CalledProcessError(128, "git"),
    ],
)
def test_refresh_skips_on_fetch_failure(monkeypatch, exc):
    def boom():
        raise exc

    monkeypatch.setattr(rsec, "fetch_rsec_paths", boom)
    con = _store()
    assert rsec.refresh_dim_package(con) is None
    assert _flags(con)["gone"] == (True, "gone")
    assert _flags(con)["limma"] == (None, None)


def test_refresh_skips_empty_import_listing(monkeypatch):
    monkeypatch.setattr(
        rsec, "fetch_rsec_paths", lambda: [p for p in _paths() if p.startswith("data/")]
    )
    con = _store()
    assert rsec.refresh_dim_package(con) is None
    assert _flags(con)["gone"] == (True, "gone")


def test_refresh_updates_on_good_listing(monkeypatch):
    monkeypatch.setattr(rsec, "fetch_rsec_paths", _paths)
    assert rsec.refresh_dim_package(_store()) == 3


def _primed(monkeypatch):
    """Store after one good refresh: 3 listed, 3 ids."""
    con = _store()
    monkeypatch.setattr(rsec, "fetch_rsec_paths", _paths)
    assert rsec.refresh_dim_package(con) == 3
    return con


def test_refresh_skips_shrunken_import_listing(monkeypatch, capsys):
    con = _primed(monkeypatch)
    before = _flags(con)
    keep = "imports/bioconductor/limma.bioconductor.json"
    monkeypatch.setattr(
        rsec, "fetch_rsec_paths",
        lambda: [p for p in _paths() if not p.startswith("imports/bioconductor/") or p == keep],
    )
    capsys.readouterr()
    assert rsec.refresh_dim_package(con) is None
    assert _flags(con) == before
    out = capsys.readouterr().out
    assert "1 listed" in out and "store has 3 / 3" in out


def test_refresh_skips_shrunken_biotools_ids(monkeypatch):
    con = _primed(monkeypatch)
    before = _flags(con)
    monkeypatch.setattr(
        rsec, "fetch_rsec_paths",
        lambda: [p for p in _paths() if not p.endswith(".biotools.json")],
    )
    assert rsec.refresh_dim_package(con) is None
    assert _flags(con) == before


def test_refresh_updates_on_modest_shrink(monkeypatch):
    con = _primed(monkeypatch)
    keep = {f"imports/bioconductor/{n}.bioconductor.json" for n in ("limma", "ace")}
    monkeypatch.setattr(
        rsec, "fetch_rsec_paths",
        lambda: [p for p in _paths() if not p.startswith("imports/bioconductor/") or p in keep],
    )
    assert rsec.refresh_dim_package(con) == 2
    assert _flags(con)["scater"] == (False, "scater")


def test_refresh_updates_on_exact_half_shrink(monkeypatch):
    con = _primed(monkeypatch)
    con.execute("UPDATE dim_package SET in_elixir_rsec = TRUE, biotools_id = 'x' "
                "WHERE package_name = 'gone'")  # store holds 4 listed / 4 ids
    keep = {f"imports/bioconductor/{n}.bioconductor.json" for n in ("limma", "ace")}
    monkeypatch.setattr(
        rsec, "fetch_rsec_paths",
        lambda: [p for p in _paths() if not p.startswith("imports/bioconductor/") or p in keep],
    )
    assert rsec.refresh_dim_package(con) == 2  # 2 listed is exactly half of 4: `<` updates


def test_views_upsert_keeps_rsec_columns():
    con = _store()
    con.execute("UPDATE dim_package SET in_elixir_rsec = TRUE, biotools_id = 'limma' "
                "WHERE package_name = 'limma'")
    row = dict.fromkeys(_PKG_COLS)
    row.update(package_name="limma", repo="bioc", title="Linear Models")
    _upsert(con, "dim_package", _PKG_COLS, [row])
    assert _flags(con)["limma"] == (True, "limma")


def test_init_schema_migrates_pre_rsec_store():
    con = db.connect(":memory:")
    con.execute("CREATE TABLE dim_package (package_name VARCHAR, repo VARCHAR)")
    db.init_schema(con)  # CREATE IF NOT EXISTS skips the old table; ALTERs add the columns
    cols = dict(con.execute("SELECT column_name, data_type FROM information_schema.columns "
                            "WHERE table_name = 'dim_package'").fetchall())
    assert (cols["in_elixir_rsec"], cols["biotools_id"]) == ("BOOLEAN", "VARCHAR")
