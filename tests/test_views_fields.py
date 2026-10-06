"""VIEWS dependency / maintenance / docs fields → dim_package → directory + dependency marts."""

from datetime import date

from biocintel import db
from biocintel.dcf import parse_dcf
from biocintel.pipeline.build_marts import _MART_SQL
from biocintel.pipeline.extract_packages import _PKG_COLS, _upsert, _views_fields

VIEWS_EXCERPT = """\
Package: limma
Version: 3.68.4
Depends: R (>= 3.6.0)
Imports: grDevices, graphics, stats, utils, methods, statmod
Suggests: BiasedUrn, ellipse, gplots, knitr, locfit, MASS, splines,
        affy, AnnotationDbi
License: GPL (>=2)
NeedsCompilation: yes
Title: Linear Models for Microarray and Omics Data
git_last_commit_date: 2026-05-31
Date/Publication: 2026-05-31
vignettes: vignettes/limma/inst/doc/usersguide.pdf,
        vignettes/limma/inst/doc/intro.html
vignetteTitles: limma User's Guide, A brief introduction to limma
hasREADME: FALSE
hasNEWS: TRUE
hasINSTALL: FALSE
hasLICENSE: FALSE
dependsOnMe: ASpli, BLMA, cghMCR
importsMe: a4Base, ABSSeq,
        affycoretools
suggestsMe: ABarray, ADaCGH2
dependencyCount: 6

Package: oldpkg
Version: 1.0.0
Depends: R (>= 4.0), methods, limma (>= 3.0)
LinkingTo: Rcpp
PackageStatus: Deprecated
vignettes: vignettes/oldpkg/inst/doc/a.html, vignettes/oldpkg/inst/doc/b.html
vignetteTitles: Alpha, Beta, with comma
linksToMe: downstream
"""


def _fields():
    return {r["Package"]: _views_fields(r) for r in parse_dcf(VIEWS_EXCERPT)}


def test_dependency_lists_strip_qualifiers_and_drop_r():
    f = _fields()
    assert f["limma"]["depends"] == []
    assert f["limma"]["imports"] == [
        "grDevices", "graphics", "stats", "utils", "methods", "statmod",
    ]
    assert f["limma"]["suggests"][-2:] == ["affy", "AnnotationDbi"]  # continuation line joined
    assert f["oldpkg"]["depends"] == ["methods", "limma"]
    assert f["oldpkg"]["linking_to"] == ["Rcpp"]


def test_reverse_dependency_lists():
    f = _fields()["limma"]
    assert f["depends_on_me"] == ["ASpli", "BLMA", "cghMCR"]
    assert f["imports_me"] == ["a4Base", "ABSSeq", "affycoretools"]
    assert f["suggests_me"] == ["ABarray", "ADaCGH2"]
    assert f["links_to_me"] == []
    assert _fields()["oldpkg"]["links_to_me"] == ["downstream"]


def test_booleans_dates_and_scalars():
    f = _fields()["limma"]
    assert (f["has_news"], f["has_readme"], f["has_install"], f["has_license"]) == (
        True, False, False, False,
    )
    assert f["needs_compilation"] is True
    assert f["git_last_commit_date"] == date(2026, 5, 31)
    assert f["date_publication"] == date(2026, 5, 31)
    assert f["dependency_count"] == 6
    assert f["license"] == "GPL (>=2)"
    assert f["package_status"] is None


def test_missing_fields_are_null_not_false():
    f = _fields()["oldpkg"]
    assert f["package_status"] == "Deprecated"
    assert f["has_news"] is None and f["needs_compilation"] is None
    assert f["git_last_commit_date"] is None and f["dependency_count"] is None


def test_vignettes_count_and_titles():
    f = _fields()
    assert f["limma"]["n_vignettes"] == 2
    assert f["limma"]["vignette_titles"] == ["limma User's Guide", "A brief introduction to limma"]
    # Titles with embedded commas can't be split reliably: keep the raw string.
    assert f["oldpkg"]["n_vignettes"] == 2
    assert f["oldpkg"]["vignette_titles"] == ["Alpha, Beta, with comma"]


def test_directory_and_dependency_marts():
    con = db.connect(":memory:")
    db.init_schema(con)
    rows = []
    for r in parse_dcf(VIEWS_EXCERPT):
        row = dict.fromkeys(_PKG_COLS)
        row.update(package_name=r["Package"], repo="bioc", **_views_fields(r))
        rows.append(row)
    _upsert(con, "dim_package", _PKG_COLS, rows)
    con.execute(_MART_SQL)
    d = con.execute(
        "SELECT n_reverse_deps, n_deps, git_last_commit_date, package_status, has_news, "
        "n_vignettes, license, bioc_url FROM mart_package_directory WHERE package_name='limma'"
    ).fetchone()
    assert d == (
        6, 6, date(2026, 5, 31), None, True, 2, "GPL (>=2)", "https://bioconductor.org/packages/limma/",
    )
    deps = con.execute(
        "SELECT dep, kind FROM mart_package_dependency "
        "WHERE package_name='oldpkg' ORDER BY kind, dep"
    ).fetchall()
    assert deps == [("limma", "depends"), ("methods", "depends"), ("Rcpp", "linking_to")]
