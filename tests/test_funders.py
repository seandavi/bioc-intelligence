"""Funder normalization: alias table + NIH core project numbers."""

import pytest

from biocintel.funders import nih_grant_numbers, resolve_funder


@pytest.mark.parametrize(
    "declared",
    [
        "CZI",
        "Chan Zuckerberg Initiative (CZI)",
        "Chan Zuckerberg Initiative DAF CZF2019-002443",
        "Silicon Valley Foundation CZF2019-002443",
        "Chan Zuckerberg Initiative",
    ],
)
def test_czi_variants_share_one_funder(declared):
    f = resolve_funder(declared)
    assert (f.funder_id, f.curated) == ("F4320315474", True)


@pytest.mark.parametrize(
    ("declared", "funder_id"),
    [
        ("NIH NHGRI", "F4320337348"),
        ("NHGRI", "F4320337348"),
        ("NHGRI AnVIL Project", "F4320337348"),
        ("NIH NCI ITCR U24CA180996", "F4320337351"),  # institute beats generic NIH
        ("National Cancer Institute", "F4320337351"),
        ("National Institutes of Health", "F4320332161"),
        ("NIH R01CA276286", "F4320332161"),
        ("RADIANT EU FP7", "F4320333065"),
        ("European Research Council", "F4320334678"),
        ("European Union HORIZON-MSCA-2021 project", "F4320334322"),
        ("DFG SFB 1366, Project B04", "F4320320879"),
        ("Ministerio de Ciencia e Innovación Spain", "F4320315062"),
        ("MCIU/AEI", "F4320315062"),
    ],
)
def test_alias_table(declared, funder_id):
    assert resolve_funder(declared).funder_id == funder_id


def test_unknown_funder_is_kept_not_dropped_and_merges_by_normalized_name():
    # Burroughs Wellcome Fund is not the Wellcome Trust: it must not fall into that alias.
    a = resolve_funder("Burroughs Wellcome Fund")
    b = resolve_funder("burroughs  wellcome fund")
    assert not a.curated
    assert a.funder_id == b.funder_id == "name:burroughs wellcome fund"
    assert resolve_funder("Wellcome Trust").funder_id == "F4320311904"


def test_comment_text_is_consulted_only_when_the_name_is_unknown():
    note = ("Funded by the DFG – Deutsche Forschungsgemeinschaft",)
    assert resolve_funder("SFB1588", note).funder_id == "F4320320879"
    # the name already identifies NCI; a note mentioning NSF must not override it
    assert resolve_funder("NCI", ("not NSF",)).funder_id == "F4320337351"


@pytest.mark.parametrize(
    ("text", "core"),
    [
        ("NIH NHGRI U24HG004059", "U24HG004059"),
        ("NIH NHGRI 5U24HG004059-18", "U24HG004059"),  # type prefix and year suffix dropped
        ("1U01CA235487", "U01CA235487"),
        ("NIH NHGRI UM1HG012003", "UM1HG012003"),  # 3-char activity code
        ("R01CA230551", "R01CA230551"),
    ],
)
def test_nih_grant_numbers_reduce_to_core_project_number(text, core):
    assert nih_grant_numbers(text) == [core]
    assert resolve_funder(text).grant_number == core


def test_non_nih_identifiers_are_not_mistaken_for_grants():
    others = ("Victoria Cancer Agency ECRF21036", "CZF2019-002443", "NHMRC 1116955")
    assert nih_grant_numbers(*others) == []


def test_grant_number_in_comment_is_found_and_stripped_from_unknown_names():
    f = resolve_funder("Acme Foundation", ("U24CA289073",))
    assert f.grant_number == "U24CA289073" and f.funder_id == "name:acme foundation"
    assert resolve_funder("Acme Foundation U24CA289073").funder_id == "name:acme foundation"
