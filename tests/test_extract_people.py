"""extract_people: source fallback chain, identity resolution, funder split."""

from biocintel.pipeline.extract_people import PackageAuthors, assemble, pick_people

DESEQ2_DESC = """\
Package: DESeq2
Authors@R: c(
    person("Michael", "Love", email="love@example.org", role = c("aut","cre"),
           comment = c(ORCID = "0000-0001-8401-0545")),
    person("Simon", "Anders", role = c("aut","ctb")),
    person("Wolfgang", "Huber", role = c("aut","ctb"),
           comment = c(ORCID = "0000-0002-0474-2218")),
    person("RADIANT EU FP7", role="fnd"),
    person("NIH NHGRI", role="fnd"),
    person("CZI", role="fnd"))
Version: 1.0
"""


def _pkg(name, desc=None, views=None, repo="bioc", maintainer=None):
    people, source = pick_people(desc, views)
    return PackageAuthors(name, repo, people, source, maintainer)


def test_deseq2_people_roles_and_funders():
    out = assemble([_pkg("DESeq2", DESEQ2_DESC)])
    by_pid = {p[0]: p for p in out.persons}
    assert set(by_pid) == {
        "orcid:0000-0001-8401-0545", "name:simon anders", "orcid:0000-0002-0474-2218",
    }
    roles = {pid: r for _, _, pid, r, _ in out.package_persons}
    assert roles["orcid:0000-0001-8401-0545"] == ["aut", "cre"]
    assert roles["name:simon anders"] == ["aut", "ctb"]
    assert sorted(f[2] for f in out.package_funders) == ["czi", "eu-fp7", "nih-nhgri"]
    # funders are organisations, not people
    assert not any("czi" in pid or "nhgri" in pid for pid in by_pid)


def test_no_email_anywhere_in_output():
    out = assemble([_pkg("DESeq2", DESEQ2_DESC)])
    assert "@" not in repr(out)


def test_non_literal_authors_r_falls_back_to_rendered_author():
    desc = (
        "Package: x\nAuthors@R: c(person('A', 'B'), me)\n"
        "Author: Jane Doe [aut, cre] (<https://orcid.org/0000-0001-2345-6789>)\n"
    )
    people, source = pick_people(desc, "ignored VIEWS Author")
    assert source == "description_author"
    assert [(p.name, p.orcid) for p in people] == [("Jane Doe", "0000-0001-2345-6789")]


def test_views_author_is_last_resort_and_none_when_nothing():
    assert pick_people(None, "Jane Doe [aut]")[1] == "views_author"
    assert pick_people(None, None) == ([], "none")
    assert pick_people("Package: x\n", None) == ([], "none")


def test_orcid_propagates_to_same_name_without_one_and_conflicts_do_not():
    a = _pkg("a", "Package: a\nAuthors@R: c(person('Jane', 'Doe', role='aut',"
                  " comment=c(ORCID='0000-0001-2345-6789')))\n")
    b = _pkg("b", "Package: b\nAuthors@R: c(person('Jane', 'Doe', role='cre'))\n")
    out = assemble([a, b])
    assert {pid for _, _, pid, _, _ in out.package_persons} == {"orcid:0000-0001-2345-6789"}

    # two different people sharing a name each keep their own ORCID; the bare one stays by name
    def wei(pkg, extra):
        return _pkg(pkg, f"Package: {pkg}\nAuthors@R: c(person('Wei', 'Wang'{extra}))\n")

    x = wei("x", ", comment=c(ORCID='0000-0001-0000-0001')")
    y = wei("y", ", comment=c(ORCID='0000-0002-0000-0002')")
    z = wei("z", ", role='aut'")
    pids = {(p, pid) for p, _, pid, _, _ in assemble([x, y, z]).package_persons}
    assert ("z", "name:wei wang") in pids
    assert ("x", "orcid:0000-0001-0000-0001") in pids and ("y", "orcid:0000-0002-0000-0002") in pids


def test_funder_with_orcid_is_both_funder_and_person_but_org_is_only_funder():
    desc = (
        "Package: x\nAuthors@R: c("
        "person('Lab', 'Head', role='fnd', comment=c(ORCID='0000-0003-1111-2222')), "
        "person('NCI', role='fnd', comment='U24CA289073'))\n"
    )
    out = assemble([_pkg("x", desc)])
    assert [p[0] for p in out.persons] == ["orcid:0000-0003-1111-2222"]
    funders = {(f[2], f[4]) for f in out.package_funders}
    assert funders == {("name:lab head", None), ("nih-nci", "U24CA289073")}


def test_maintainer_from_views_when_no_cre_role():
    # no 'cre' in the Author field: the VIEWS maintainer is credited, merged into the
    # same person when the name matches, added as a new row otherwise
    merged = _pkg("m", views="Jane Doe [aut]", maintainer="Jane Doe")
    added = _pkg("n", views="Jane Doe [aut]", maintainer="Someone Else")
    out = assemble([merged, added])
    rows = {(pkg, pid): (roles, src) for pkg, _, pid, roles, src in out.package_persons}
    assert rows[("m", "name:jane doe")] == (["aut", "cre"], "views_author")
    assert rows[("n", "name:someone else")] == (["cre"], "maintainer")


def test_same_person_listed_twice_in_a_package_merges_roles():
    desc = "Package: x\nAuthors@R: c(person('A', 'B', role='aut'), person('A', 'B', role='cre'))\n"
    out = assemble([_pkg("x", desc)])
    assert [(r[2], r[3]) for r in out.package_persons] == [("name:a b", ["aut", "cre"])]


def test_rows_are_unique_per_package_and_person():
    out = assemble([_pkg("DESeq2", DESEQ2_DESC), _pkg("DESeq2", DESEQ2_DESC, repo="workflows")])
    keys = [(p, r, pid) for p, r, pid, _, _ in out.package_persons]
    assert len(keys) == len(set(keys))


BIOC = "Bioconductor Package Maintainer"


def test_generic_bioconductor_credit_lines_are_not_people():
    out = assemble([
        _pkg("a", views="Jane Doe [aut], The Bioconductor Project [cph]", maintainer=BIOC),
        _pkg("b", views="Bioconductor Core Team [aut]", maintainer=BIOC),
    ])
    assert [p[0] for p in out.persons] == ["name:jane doe"]


def test_declared_counts_ignore_orcid_inherited_from_other_packages():
    orcid = "comment=c(ORCID='0000-0001-2345-6789')"
    a = _pkg("a", f"Package: a\nAuthors@R: c(person('Jane', 'Doe', {orcid}))\n")
    b = _pkg("b", "Package: b\nAuthors@R: c(person('Jane', 'Doe'), person('NCI', role='fnd'))\n")
    out = assemble([a, b])
    assert out.counts["packages_declaring_orcid"] == 1  # b inherits the id but did not declare it
    assert out.counts["packages_declaring_fnd"] == 1
