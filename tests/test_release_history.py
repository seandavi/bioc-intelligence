"""Multi-release backfill (#44): past VIEWS → first_seen and the release-diff marts (no network)."""

from datetime import date

import pytest

from biocintel import db, http
from biocintel.config import RELEASE_ANNOUNCEMENTS_URL, REPOS, ReleaseConfig, views_url
from biocintel.pipeline import extract_packages as ep
from biocintel.pipeline.build_marts import _MART_SQL

# Trimmed from bioconductor.org/about/release-announcements/ (1.0 predates VIEWS).
ANNOUNCEMENTS = """
<table><thead><tr><th>Release</th><th>Date</th><th>Software packages</th><th>R</th></tr></thead>
<tbody><tr>
<td align="left"><a href="/news/bioc_3_11_release">3.11</a></td>
<td align="left">April 28, 2020</td>
<td align="right"><a href="/packages/3.11/">1,903</a></td>
<td align="left">4.0</td>
</tr><tr>
<td>3.10</td><td>October 30, 2019</td><td align="right">1823</td><td>3.6</td>
</tr><tr>
<td align="left">3.9</td><td align="left">May 3, 2019</td><td align="right">1741</td><td>3.6</td>
</tr><tr>
<td align="left">1.0</td><td align="left">May 1, 2002</td><td align="right">15</td><td>1.5</td>
</tr></tbody></table>
"""


def _views(*pkgs: str) -> str:
    return "\n\n".join(f"Package: {p}\nVersion: 1.0.{i}" for i, p in enumerate(pkgs))


@pytest.fixture
def store(monkeypatch, tmp_path):
    bioc = REPOS["bioc"]
    served = {
        RELEASE_ANNOUNCEMENTS_URL: ANNOUNCEMENTS,
        views_url(bioc, release="3.9"): _views("A", "B"),
        views_url(bioc, release="3.10"): _views("A", "C"),
        views_url(bioc): _views("A", "C", "D"),  # current release (3.11)
    }
    forced: dict[str, bool] = {}

    def fake_get_text(url, *, force_cache=False):
        forced[url] = force_cache
        if url not in served:
            raise http.HttpError(url, 404)
        return served[url]

    monkeypatch.setattr(ep, "get_text", fake_get_text)
    monkeypatch.setattr(
        ep, "fetch_release_config", lambda: ReleaseConfig("3.11", "3.12", {}, {"3.9": "3.6"})
    )
    path = tmp_path / "t.duckdb"
    monkeypatch.setattr(db, "DB_PATH", path)
    ep.run(["bioc"], all_releases=True)
    assert forced[views_url(bioc, release="3.9")] is True  # past VIEWS are immutable
    assert forced[RELEASE_ANNOUNCEMENTS_URL] is False  # the table grows each release
    con = db.connect(path)
    con.execute(_MART_SQL)
    yield con
    con.close()


def test_parse_release_announcements():
    got = ep.parse_release_announcements(ANNOUNCEMENTS)
    assert got["3.11"] == (date(2020, 4, 28), 1903)
    assert got["1.0"] == (date(2002, 5, 1), 15)
    assert len(got) == 4


def test_first_seen_is_earliest_loaded_release(store):
    rows = store.execute(
        "SELECT package_name, first_seen_release FROM dim_package ORDER BY 1"
    ).fetchall()
    # B was removed before 3.11, so it has versions but no dim_package row.
    assert rows == [("A", "3.9"), ("C", "3.10"), ("D", "3.11")]
    assert store.execute(
        "SELECT release_date, r_version FROM dim_package_version "
        "WHERE package_name = 'B'"
    ).fetchone() == (date(2019, 5, 3), "3.6")


def test_release_history_new_and_removed(store):
    rows = store.execute(
        "SELECT bioc_release, release_date, repo, n_packages, n_new, n_removed "
        "FROM mart_release_history"
    ).fetchall()
    # Numeric order (3.9 < 3.10); the earliest loaded release has no diff.
    assert rows == [
        ("3.9", date(2019, 5, 3), "bioc", 2, None, None),
        ("3.10", date(2019, 10, 30), "bioc", 2, 1, 1),
        ("3.11", date(2020, 4, 28), "bioc", 3, 1, 0),
    ]


def test_release_growth_covers_announced_releases(store):
    rows = store.execute(
        "SELECT bioc_release, n_software_announced, n_packages, n_new_packages, n_removed "
        "FROM mart_release_growth"
    ).fetchall()
    assert rows == [
        ("1.0", 15, None, None, None),  # announced only, no VIEWS
        ("3.9", 1741, 2, None, None),
        ("3.10", 1823, 2, 1, 1),
        ("3.11", 1903, 3, 1, 0),
    ]
