"""judge_mentions — apply the multidimensional judge to stored mention candidates.

Decoupled from mining (spec §6): mine once, judge later, re-run as the judge
improves — no re-mining. Operates purely on the **local** store (no lake), reading
unjudged `fact_mention_candidate` rows and writing the judge columns
`{is_genuine_mention, package_confidence, usage_vs_passing_reference}`. A confirmed
candidate is later promoted into `fact_citation_edge` (mention_type='fulltext').

The judge itself is pluggable: `run(judge=...)` takes a callable mapping a list of
candidate dicts to a list of verdict dicts. No model is wired here yet — pass an
Anthropic-backed judge when ready. `null_judge` is a no-op used for plumbing/tests.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .. import db

Candidate = dict
Verdict = dict
Judge = Callable[[list[Candidate]], list[Verdict]]

_SELECT = """
SELECT rowid AS _rid, package_name, repo, citing_work_id, section, mention_text
FROM fact_mention_candidate
WHERE judged_at IS NULL
{limit}
"""

_UPDATE = """
UPDATE fact_mention_candidate
SET judged_at = ?, is_genuine_mention = ?, package_confidence = ?,
    usage_vs_passing_reference = ?
WHERE rowid = ?
"""


def null_judge(candidates: list[Candidate]) -> list[Verdict]:
    """No-op judge: records that nothing was decided (for plumbing/tests)."""
    return [
        {"is_genuine_mention": None, "package_confidence": None,
         "usage_vs_passing_reference": None}
        for _ in candidates
    ]


def run(judge: Judge = null_judge, *, limit: int | None = None,
        db_path: Path | str | None = None) -> int:
    """Judge unjudged candidates; returns the number processed."""
    con = db.connect(db_path)
    db.init_schema(con)
    try:
        sql = _SELECT.format(limit=f"LIMIT {int(limit)}" if limit else "")
        cols = [c[0] for c in con.execute(sql).description]
        rows = [dict(zip(cols, r, strict=True)) for r in con.execute(sql).fetchall()]
        if not rows:
            print("  no unjudged candidates")
            return 0
        verdicts = judge(rows)
        if len(verdicts) != len(rows):
            raise ValueError(f"judge returned {len(verdicts)} verdicts for {len(rows)} candidates")
        stamp = datetime.now()
        con.executemany(
            _UPDATE,
            [
                [stamp, v.get("is_genuine_mention"), v.get("package_confidence"),
                 v.get("usage_vs_passing_reference"), r["_rid"]]
                for r, v in zip(rows, verdicts, strict=True)
            ],
        )
        print(f"  judged {len(rows)} candidate(s)")
        return len(rows)
    finally:
        con.close()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Judge stored mention candidates (local).")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    print("judge_mentions (null judge — wire a real judge to decide):")
    run(null_judge, limit=args.limit)


if __name__ == "__main__":
    main()
