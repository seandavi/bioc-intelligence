from datetime import date

from biocintel.pipeline.extract_downloads import parse_stats_tab

# Layout per BiocPkgTools: header + per-(package, year, month) rows with an
# "all" subtotal we drop. Tab/space separated.
STATS_SAMPLE = """\
Package\tYear\tMonth\tNb_of_distinct_IPs\tNb_of_downloads
limma\t2015\tSep\t1000\t2500
limma\t2015\tOct\t1200\t3000
limma\t2015\tall\t13000\t40000
limma\t2026\tJan\t5000\t12000
"""


def test_parses_monthly_rows_and_drops_all():
    rows = parse_stats_tab(STATS_SAMPLE, "bioc", date(2026, 6, 26))
    assert len(rows) == 3  # the Month=all subtotal is dropped
    months = {(r["year"], r["month"]) for r in rows}
    assert months == {(2015, 9), (2015, 10), (2026, 1)}


def test_methodology_era_boundary_oct_2015():
    rows = {(r["year"], r["month"]): r for r in parse_stats_tab(STATS_SAMPLE, "bioc", date.today())}
    assert rows[(2015, 9)]["methodology_era"] == "pre_2015_10"
    assert rows[(2015, 10)]["methodology_era"] == "modern"
    assert rows[(2026, 1)]["methodology_era"] == "modern"


def test_values_and_repo_tag():
    rows = parse_stats_tab(STATS_SAMPLE, "bioc", date.today())
    jan = next(r for r in rows if r["month"] == 1)
    assert jan["distinct_ips"] == 5000
    assert jan["downloads"] == 12000
    assert jan["repo"] == "bioc"
