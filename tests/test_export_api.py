"""Offline test of the static JSON API: rendered from tiny fixture Parquet marts in a temp dir."""

import json

from biocintel import db
from biocintel.pipeline.build_marts import _MART_SQL, _MARTS
from biocintel.pipeline.export_api import humanize, run


def _fixture_marts(tmp_path):
    con = db.connect(":memory:")
    db.init_schema(con)
    con.execute(_MART_SQL)  # empty marts with the current shape
    con.execute("""
        INSERT INTO mart_package_directory (package_name, repo, title)
        VALUES ('limma', 'bioc', 'Linear models'), ('../evil', 'bioc', 'bad');
        INSERT INTO mart_package_impact (package_name, repo, distinct_ips_trailing_12mo)
        VALUES ('limma', 'bioc', 148000);
        INSERT INTO mart_package_work (package_name, repo, work_id, citation_count, match_method,
                                       confidence)
        VALUES ('limma', 'bioc', 'W1', 1000, 'doi', 1.0),
               ('limma', 'bioc', 'W1', 1000, 'citation_file', 0.9),
               ('limma', 'bioc', 'W2', 500, 'description_doi', 0.8);
        INSERT INTO mart_grant_attribution (grant_id, agency, title, package_names)
        VALUES ('U24CA180996', 'CA', 'A grant', ['limma']), ('bad/id', 'CA', 'x', ['limma']);
        INSERT INTO mart_package_person (package_name, repo, name, is_maintainer)
        VALUES ('limma', 'bioc', 'Gordon Smyth', true);
        INSERT INTO mart_package_dependency VALUES ('limma', 'bioc', 'methods', 'imports');
    """)
    # 40 months of downloads; only the last 36 are exported.
    con.execute("""
        INSERT INTO mart_package_downloads_monthly
        SELECT 'limma', 'bioc', 2023 + (i // 12), i % 12 + 1, 10, 20, 'modern'
        FROM range(40) t(i)
    """)
    for m in _MARTS:
        con.execute(f"COPY {m} TO '{tmp_path / m}.parquet' (FORMAT parquet)")
    con.close()
    (tmp_path / "manifest.json").write_text(json.dumps({"snapshot": "2026-10-01"}))


def test_export_api_over_fixture_marts(tmp_path):
    _fixture_marts(tmp_path)
    out, badges = tmp_path / "dist" / "api", tmp_path / "dist" / "badges"
    summary = run(tmp_path, out, badges)
    assert summary["skipped"] == ["bad/id", "../evil"]
    assert not (tmp_path / "dist" / "evil.json").exists()

    index = json.loads((out / "v1" / "index.json").read_text())
    assert index["snapshot"] == "2026-10-01"
    assert index["counts"] == {"packages": 1, "grants": 1}
    assert index["packages"] == ["limma"] and index["grants"] == ["U24CA180996"]

    pkg = json.loads((out / "v1" / "package" / "limma.json").read_text())
    assert set(pkg) == {
        "snapshot", "package", "impact", "confident_citations", "papers", "grants",
        "people", "funders", "dependencies", "downloads_monthly",
    }
    assert pkg["package"]["title"] == "Linear models"
    assert pkg["confident_citations"] == 1000  # W1 counted once; description_doi excluded
    assert len(pkg["papers"]) == 3
    assert [g["grant_id"] for g in pkg["grants"]] == ["U24CA180996"]
    assert pkg["dependencies"] == {"imports": ["methods"]}
    assert len(pkg["downloads_monthly"]) == 36
    assert pkg["downloads_monthly"][-1] == {
        "year": 2026, "month": 4, "distinct_ips": 10, "downloads": 20, "methodology_era": "modern"
    }

    grant = json.loads((out / "v1" / "grant" / "U24CA180996.json").read_text())
    assert grant["packages"][0]["package_name"] == "limma"

    assert json.loads((badges / "limma" / "downloads.json").read_text()) == {
        "schemaVersion": 1, "label": "distinct IPs", "message": "12.3k/mo avg", "color": "blue"
    }
    assert json.loads((badges / "limma" / "citations.json").read_text())["message"] == "1.0k"


def test_humanize():
    assert [humanize(n) for n in (0, 999, 999.6, 12_345, 2_500_000)] == [
        "0", "999", "1.0k", "12.3k", "2.5M"
    ]
