from datetime import date

from biocintel import db
from biocintel.pipeline import judge_mentions
from biocintel.pipeline.mine_mentions import build_pattern


def test_build_pattern_word_boundary_and_escaping():
    assert build_pattern("limma") == r"\blimma\b"
    # Names with regex-special characters must be escaped.
    assert build_pattern("a4.base") == r"\ba4\.base\b"


def test_judge_pipeline_fills_columns(tmp_path):
    dbp = tmp_path / "t.duckdb"
    con = db.connect(dbp)
    db.init_schema(con)
    con.execute(
        "INSERT INTO fact_mention_candidate "
        "(package_name, repo, citing_work_id, source, mention_text, section, _extracted_snapshot) "
        "VALUES ('limma','bioc','12345','epmc','We used limma for DE analysis.','methods',?)",
        [date.today()],
    )
    con.close()

    def fake_judge(cands):
        assert cands[0]["package_name"] == "limma"
        return [{"is_genuine_mention": True, "package_confidence": 0.9,
                 "usage_vs_passing_reference": "usage"}]

    n = judge_mentions.run(fake_judge, db_path=dbp)
    assert n == 1

    con = db.connect(dbp, read_only=True)
    row = con.execute(
        "SELECT is_genuine_mention, package_confidence, usage_vs_passing_reference, "
        "judged_at IS NOT NULL FROM fact_mention_candidate"
    ).fetchone()
    con.close()
    assert row == (True, 0.9, "usage", True)


def test_judge_noop_when_no_candidates(tmp_path):
    assert judge_mentions.run(db_path=tmp_path / "empty.duckdb") == 0
