"""extract_people — Authors@R → people and funders (dim_/bridge_ person and funder tables).

Bioconductor-native, no lake. Per package, in order of fidelity:

1. ``Authors@R`` from the DESCRIPTION in the ``bioconductor-source`` org (raw code,
   parsed without evaluating it — see ``biocintel.authors``);
2. the rendered ``Author`` field of that same DESCRIPTION;
3. the rendered ``Author`` field from VIEWS (the only source for the
   data-annotation packages the org doesn't carry).

A package whose ``Authors@R`` is not plain ``c()``/``person()`` literals drops to the
next source, so nothing is ever evaluated. Emails never reach the store.

Person identity is the ORCID when declared, else the normalized name; a name that
carries exactly one ORCID anywhere in the corpus inherits it everywhere, so the
same person with and without an ORCID collapses to one row. ``fnd`` entries become
funders (normalized through ``funder_aliases.yaml``); a fnd-only entry with no ORCID
is an organisation and is *not* a person. Because identity spans repos, the tables
are rebuilt whole each run.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .. import db
from ..authors import Person, normalize_name, parse_authors_r, parse_rendered
from ..config import REPOS, views_url
from ..dcf import parse_dcf
from ..funders import resolve_funder
from ..http import HttpError, get_text
from .extract_citation_files import source_url

_WORKERS = 16  # one small GET per package, as in extract_citation_files


@dataclass
class PackageAuthors:
    """Everything known about who is credited on one package."""

    package_name: str
    repo: str
    people: list[Person]
    source: str  # 'authors_r' | 'description_author' | 'views_author' | 'none'
    maintainer: str | None = None  # dim_package.maintainer name (VIEWS), used if no 'cre' role


@dataclass
class Assembled:
    persons: list[tuple]  # dim_person rows
    package_persons: list[tuple]  # bridge_package_person rows
    funders: list[tuple]  # dim_funder rows
    package_funders: list[tuple]  # bridge_package_funder rows
    counts: dict[str, int] = field(default_factory=dict)


# Generic credit lines, not people: counting "Bioconductor Package Maintainer" as a developer
# of 548 packages would swamp every "developers with more than N packages" ranking.
_PLACEHOLDER_RE = re.compile(
    r"\b(package maintainer|bioconductor (project|dev(elopment)? team|core team|maintainer)"
    r"|biocore)\b"
)


def _is_not_a_person(p: Person) -> bool:
    """Funder-only organisations (``fnd`` without ORCID) and generic Bioconductor credit lines."""
    if p.roles == ("fnd",) and not p.orcid:
        return True
    return bool(_PLACEHOLDER_RE.search(normalize_name(p.name)))


def pick_people(
    description: str | None, views_author: str | None
) -> tuple[list[Person], str]:
    """People + source for one package from its DESCRIPTION text and VIEWS Author."""
    if description:
        rec = (parse_dcf(description, fold=False) or [{}])[0]
        people = parse_authors_r(rec.get("Authors@R"))
        if people is not None:
            return people, "authors_r"
        if people := parse_rendered(rec.get("Author")):
            return people, "description_author"
    if people := parse_rendered(views_author):
        return people, "views_author"
    return [], "none"


def _with_maintainer(pkg: PackageAuthors) -> list[tuple[Person, str]]:
    """People (with row source), adding the VIEWS maintainer if nobody holds ``cre``."""
    rows = [(p, pkg.source) for p in pkg.people]
    if pkg.maintainer and not any("cre" in p.roles for p, _ in rows):
        key = normalize_name(pkg.maintainer)
        for i, (p, src) in enumerate(rows):
            if key and normalize_name(p.name) == key:
                roles = (*p.roles, "cre")
                rows[i] = (Person(p.given, p.family, roles, p.orcid, p.ror, p.notes), src)
                break
        else:
            rows.append((Person(pkg.maintainer, "", ("cre",)), "maintainer"))
    return rows


def assemble(packages: list[PackageAuthors]) -> Assembled:
    """Resolve identities and build every table row. Pure: no IO."""
    # Names that carry exactly one ORCID anywhere inherit it for their un-ORCID'd mentions.
    name_orcids: dict[str, set[str]] = defaultdict(set)
    per_pkg: list[tuple[PackageAuthors, list[tuple[Person, str]]]] = []
    declared_orcid: set[tuple[str, str]] = set()  # packages that *declare* an ORCID (as
    declared_fnd: set[tuple[str, str]] = set()  # written, not inherited) / a fnd role
    for pkg in packages:
        rows = _with_maintainer(pkg)
        per_pkg.append((pkg, rows))
        for p, _src in rows:
            if p.orcid:
                name_orcids[normalize_name(p.name)].add(p.orcid)
                declared_orcid.add((pkg.package_name, pkg.repo))
            if "fnd" in p.roles:
                declared_fnd.add((pkg.package_name, pkg.repo))

    def person_id(p: Person) -> tuple[str, str | None] | None:
        key = normalize_name(p.name)
        orcid = p.orcid
        if not orcid and len(name_orcids.get(key, ())) == 1:
            (orcid,) = name_orcids[key]
        if orcid:
            return f"orcid:{orcid}", orcid
        return (f"name:{key}", None) if key else None

    names: dict[str, Counter[str]] = defaultdict(Counter)
    orcids: dict[str, str | None] = {}
    rors: dict[str, str] = {}
    membership: dict[tuple[str, str, str], tuple[list[str], str]] = {}
    funder_rows: dict[tuple, None] = {}
    funder_names: dict[str, Counter[str]] = defaultdict(Counter)
    funder_meta: dict[str, tuple[str, bool]] = {}

    for pkg, rows in per_pkg:
        for p, src in rows:
            if "fnd" in p.roles and p.name:
                f = resolve_funder(p.name, p.notes)
                funder_rows[
                    (pkg.package_name, pkg.repo, f.funder_id, p.name, f.grant_number, src)
                ] = None
                funder_meta[f.funder_id] = (f.name, f.curated)
                funder_names[f.funder_id][f.name] += 1
            if _is_not_a_person(p) or not (ident := person_id(p)):
                continue
            pid, orcid = ident
            names[pid][p.name] += 1
            orcids[pid] = orcid
            if p.ror:
                rors.setdefault(pid, p.ror)
            slot = (pkg.package_name, pkg.repo, pid)
            roles, first_src = membership.get(slot, ([], src))
            membership[slot] = ([*roles, *(r for r in p.roles if r not in roles)], first_src)

    persons = [
        (pid, c.most_common(1)[0][0], orcids[pid], rors.get(pid))
        for pid, c in sorted(names.items())
    ]
    package_persons = [
        (pkg, repo, pid, roles, src)
        for (pkg, repo, pid), (roles, src) in sorted(membership.items())
    ]
    funders = [
        (fid, name if curated else funder_names[fid].most_common(1)[0][0], curated)
        for fid, (name, curated) in sorted(funder_meta.items())
    ]
    package_funders = sorted(funder_rows, key=lambda r: tuple("" if v is None else v for v in r))
    counts = {
        "packages": len(packages),
        "persons": len(persons),
        "package_persons": len(package_persons),
        "funders": len(funders),
        "package_funders": len(package_funders),
        "packages_declaring_orcid": len(declared_orcid),
        "packages_declaring_fnd": len(declared_fnd),
    }
    return Assembled(persons, package_persons, funders, package_funders, counts)


def _fetch(package: str) -> str | None:
    try:
        return get_text(source_url(package, "DESCRIPTION"))
    except HttpError:
        return None  # not in the org (e.g. most data-annotation packages)


def run() -> dict[str, int]:
    """Rebuild the people/funder tables from every package in ``dim_package``."""
    con = db.connect()
    db.init_schema(con)
    try:
        rows = con.execute(
            "SELECT package_name, repo, maintainer FROM dim_package ORDER BY repo, package_name"
        ).fetchall()
        if not rows:
            print("  no packages in dim_package — run extract-packages first")
            return {"packages": 0}

        views: dict[tuple[str, str], str | None] = {}
        for key, repo in REPOS.items():
            for rec in parse_dcf(get_text(views_url(repo))):
                views[(rec.get("Package", ""), key)] = rec.get("Author")

        with ThreadPoolExecutor(_WORKERS) as pool:
            descriptions = list(pool.map(lambda r: _fetch(r[0]), rows))

        packages = []
        for (name, repo, maintainer), desc in zip(rows, descriptions, strict=True):
            people, source = pick_people(desc, views.get((name, repo)))
            packages.append(PackageAuthors(name, repo, people, source, maintainer))

        out = assemble(packages)
        tables = [  # (table, rows) — child tables first so a failed insert leaves no orphans
            ("bridge_package_funder", out.package_funders, 6),
            ("dim_funder", out.funders, 3),
            ("bridge_package_person", out.package_persons, 5),
            ("dim_person", out.persons, 4),
        ]
        con.execute("BEGIN")
        for table, _, _ in tables:
            con.execute(f"DELETE FROM {table}")
        for table, data, width in reversed(tables):
            marks = ", ".join("?" * width)
            con.executemany(f"INSERT INTO {table} VALUES ({marks})", data)
        con.execute("COMMIT")

        by_source = Counter(p.source for p in packages)
        n_orcid = con.execute(
            "SELECT count(*) FROM dim_person WHERE orcid IS NOT NULL"
        ).fetchone()[0]
        print(
            f"  {out.counts['packages']} packages; people source: "
            + ", ".join(f"{k}={v}" for k, v in sorted(by_source.items()))
        )
        print(
            f"  dim_person {out.counts['persons']} ({n_orcid} with ORCID), "
            f"bridge_package_person {out.counts['package_persons']}, "
            f"dim_funder {out.counts['funders']}, "
            f"bridge_package_funder {out.counts['package_funders']}"
        )
        print(
            f"  packages declaring an ORCID: {out.counts['packages_declaring_orcid']}; "
            f"declaring a fnd role: {out.counts['packages_declaring_fnd']}"
        )
        return out.counts
    finally:
        con.close()


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(
        description="Extract people and funders from Authors@R."
    ).parse_args(argv)
    print("extract_people:")
    run()


if __name__ == "__main__":
    main()
