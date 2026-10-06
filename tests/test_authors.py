"""Authors@R parsing: literal-only (never evaluated), clean fallback, no emails."""

from pathlib import Path

from biocintel.authors import normalize_name, parse_authors_r, parse_rendered
from biocintel.dcf import parse_dcf

DESEQ2 = """\
c(
    person("Michael", "Love", email="love@example.org", role = c("aut","cre"),
           comment = c(ORCID = "0000-0001-8401-0545")),
    person("Simon", "Anders", role = c("aut","ctb")),  # a trailing R comment
    person("Wolfgang", "Huber", role = c("aut","ctb"),
           comment = c(ORCID = "0000-0002-0474-2218")),
    person("RADIANT EU FP7", role="fnd"),
    person("NIH NHGRI", role="fnd"),
    person("CZI", role="fnd"))
"""


def test_parses_people_roles_orcid_and_funders():
    people = parse_authors_r(DESEQ2)
    assert [p.name for p in people] == [
        "Michael Love", "Simon Anders", "Wolfgang Huber",
        "RADIANT EU FP7", "NIH NHGRI", "CZI",
    ]
    love, anders, huber, *funders = people
    assert love.roles == ("aut", "cre") and love.orcid == "0000-0001-8401-0545"
    assert anders.roles == ("aut", "ctb") and anders.orcid is None
    assert huber.orcid == "0000-0002-0474-2218"
    assert all(f.roles == ("fnd",) for f in funders)


def test_email_is_never_kept():
    (love, *_) = parse_authors_r(DESEQ2)
    assert "love@example.org" not in repr(love)
    assert not hasattr(love, "email")


def test_positional_empty_and_partial_arguments():
    # person(given, family, middle, email, role, comment) with a skipped middle,
    # plus R's partial argument matching (give= for given=).
    people = parse_authors_r(
        'c(person("Marcel", "Ramos", , "m@x.org", c("aut", "cre"),'
        ' c(ORCID = "0000-0002-3242-0582")),'
        ' person(give = "Martin", fam = "Morgan", rol = "ctb"))'
    )
    assert people[0].roles == ("aut", "cre") and people[0].orcid == "0000-0002-3242-0582"
    assert people[1].name == "Martin Morgan" and people[1].roles == ("ctb",)


def test_orcid_as_url_and_ror_in_comment():
    (p,) = parse_authors_r(
        'person("A", "B", role = "aut", '
        'comment = c(ORCID = "https://orcid.org/0000-0003-4046-0063", '
        'ROR = "https://ror.org/05r0vyz12"))'
    )
    assert p.orcid == "0000-0003-4046-0063"
    assert p.ror == "https://ror.org/05r0vyz12"


def test_comment_text_survives_as_notes():
    (p,) = parse_authors_r('person("NCI", role = "fnd", comment = "U24CA289073")')
    assert p.notes == ("U24CA289073",)


def test_given_vector_and_middle_compose_name():
    (p,) = parse_authors_r('person(given = c("Ji", "Ping"), middle = "Q.", family = "Wang")')
    assert p.name == "Ji Ping Q. Wang"


def test_namespace_qualifier_and_null():
    (p,) = parse_authors_r('utils::person("A", "B", email = NULL, role = "aut")')
    assert p.name == "A B"


def test_string_escapes():
    (p,) = parse_authors_r(r'person("Andr\u00e9", "O\"Neil")')
    assert p.name == 'André O"Neil'


def test_non_literal_input_falls_back_without_evaluating(tmp_path: Path):
    marker = tmp_path / "pwned"
    nasty = [
        f'system("touch {marker}")',
        f'c(person("A", "B"), system("touch {marker}"))',
        f'person("A", "B", role = system("touch {marker}"))',
        'person(paste0("A", "B"), "C")',
        'c(person("A", "B"), me)',  # variable reference
        'as.person("A B [aut]")',
        'person("A", "B", comment = c(ORCID = 0000-0002-5778-7014))',  # unquoted: arithmetic
        'person("A", "B")\nperson("C", "D")',  # two top-level expressions
        'c(person("A", "B")',  # unterminated
        'person("A", "B", bogus = "x")',
        "",
        None,
    ]
    for text in nasty:
        assert parse_authors_r(text) is None, text
    assert not marker.exists()


def test_pathological_nesting_falls_back():
    assert parse_authors_r("c(" * 500 + ")" * 500) is None


def test_empty_c_is_empty_not_fallback():
    assert parse_authors_r("c()") == []


def test_r_comment_does_not_swallow_following_lines():
    # parse_dcf(fold=True) would join these onto one line and the # would eat the rest.
    dcf = (
        "Package: x\n"
        'Authors@R: c(person("A", "B", role = "aut"), # first\n'
        '    person("C", "D", role = "cre"))\n'
        "Version: 1\n"
    )
    folded = parse_dcf(dcf)[0]["Authors@R"]
    raw = parse_dcf(dcf, fold=False)[0]["Authors@R"]
    assert [p.name for p in parse_authors_r(raw)] == ["A B", "C D"]
    assert parse_authors_r(folded) is None  # folded, the # eats the rest: why fold=False exists


RENDERED = (
    "Michael Love [aut, cre] (<https://orcid.org/0000-0001-8401-0545>), Simon Anders [aut, ctb], "
    "Wolfgang Huber [aut, ctb] (<https://orcid.org/0000-0002-0474-2218>), CZI [fnd], "
    "Chan Zuckerberg Initiative DAF CZF2019-002443 [fnd]"
)


def test_rendered_author_fallback():
    people = parse_rendered(RENDERED)
    assert [p.name for p in people] == [
        "Michael Love", "Simon Anders", "Wolfgang Huber", "CZI",
        "Chan Zuckerberg Initiative DAF CZF2019-002443",
    ]
    assert people[0].roles == ("aut", "cre") and people[0].orcid == "0000-0001-8401-0545"
    assert people[3].roles == ("fnd",)


def test_rendered_keeps_commas_inside_brackets_and_drops_email():
    (p,) = parse_rendered("Jane Doe <jane@example.org> [aut, cre, ctb]")
    assert p.name == "Jane Doe" and p.roles == ("aut", "cre", "ctb")
    assert "jane@example.org" not in repr(p)


def test_rendered_and_only_splits_two_name_entries():
    assert [p.name for p in parse_rendered("Michael Love and Simon Anders")] == [
        "Michael Love", "Simon Anders",
    ]
    assert [p.name for p in parse_rendered("Biostatistics and Bioinformatics Group")] == [
        "Biostatistics and Bioinformatics Group",
    ]


def test_rendered_empty():
    assert parse_rendered(None) == [] and parse_rendered("  ") == []


def test_normalize_name_strips_accents_case_and_punctuation():
    assert normalize_name("Hervé Pagès") == normalize_name("herve  PAGES")
    assert normalize_name("W. Evan Johnson") == "w evan johnson"


def test_positional_orcid_comment_is_not_a_middle_name():
    # R binds the unnamed c(ORCID=...) to `middle`; the package meant it as the comment.
    (p,) = parse_authors_r(
        'person(given = "Mark", family = "Ziemann", role = "aut", c(ORCID = "0000-0002-7688-6974"))'
    )
    assert p.name == "Mark Ziemann" and p.orcid == "0000-0002-7688-6974"


def test_email_in_a_name_slot_is_dropped():
    (p,) = parse_authors_r('person("Shreya", "Rao", "s@x.org", "shreya@x.org", role = "aut")')
    assert "@" not in repr(p)


def test_rendered_names_drop_emails_and_lift_bare_orcids_and_reject_sentences():
    people = parse_rendered(
        "Mark 0000-0002-7688-6974 Ziemann [aut], Steffen Neumann {a|b}@ipb.de, "
        "Gordon K Smyth with contributions from Jenny Dai, "
        "Lihua Julie Zhu Paul Scemama Benjamin R. Holmes Hervé Pagès Kai Hu"
    )
    assert [(p.name, p.orcid) for p in people] == [
        ("Mark Ziemann", "0000-0002-7688-6974"),
        ("Steffen Neumann", None),
        ("Gordon K Smyth", None),
    ]
