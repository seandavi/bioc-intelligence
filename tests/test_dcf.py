from biocintel.dcf import parse_dcf, parse_maintainer, split_list

VIEWS_SAMPLE = """\
Package: a4
Version: 1.60.0
Depends: a4Base, a4Preproc
License: GPL-3
Title: Automated Affymetrix Array Analysis Umbrella Package
Description: Umbrella package is available for the entire Automated
        Affymetrix Array Analysis suite of package.
biocViews: Microarray
Maintainer: Laure Cougnaud <laure.cougnaud@openanalytics.eu>
git_branch: RELEASE_3_23

Package: ABarray
Version: 1.94.0
biocViews: Microarray, OneChannel, DataImport
Maintainer: Yongming Sun <yongming.sun@example.org>
git_branch: RELEASE_3_23
"""


def test_parse_dcf_splits_records():
    recs = parse_dcf(VIEWS_SAMPLE)
    assert len(recs) == 2
    assert recs[0]["Package"] == "a4"
    assert recs[1]["Version"] == "1.94.0"


def test_continuation_folds_to_single_field():
    recs = parse_dcf(VIEWS_SAMPLE)
    assert recs[0]["Description"].startswith("Umbrella package")
    assert "Affymetrix Array Analysis suite" in recs[0]["Description"]
    assert "\n" not in recs[0]["Description"]


def test_split_list_strips_version_constraints():
    assert split_list("a4Base, R (>= 4.3), methods") == ["a4Base", "R", "methods"]
    assert split_list(None) == []


def test_parse_maintainer():
    assert parse_maintainer("Laure Cougnaud <laure.cougnaud@openanalytics.eu>") == (
        "Laure Cougnaud",
        "laure.cougnaud@openanalytics.eu",
    )
    assert parse_maintainer(None) == (None, None)
