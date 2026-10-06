"""People from a package's ``Authors@R`` (or the rendered ``Author`` fallback).

``Authors@R`` is R code, so ``eval(parse())`` would run arbitrary code from
every package in the repositories. This module never evaluates anything: it
tokenizes the field and walks the call tree, accepting only ``c()``,
``person()`` and literal arguments (strings, ``NULL``). Anything else
(a variable, ``paste0()``, ``as.person()``, arithmetic, ...) raises
:class:`NotLiteral` internally and :func:`parse_authors_r` returns ``None`` so
the caller falls back to the rendered ``Author`` string.

Emails are accepted in the input but deliberately never stored on
:class:`Person`: nothing downstream can publish what it never had.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_MAX_DEPTH = 20  # c(person(...)) nests a handful deep; refuse pathological input
_MAX_LEN = 200_000

ORCID_RE = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])\b")
_ROR_URL_RE = re.compile(r"ror\.org/(0[0-9a-hj-km-np-tv-z]{8})\b", re.IGNORECASE)
_ROR_BARE_RE = re.compile(r"^(0[0-9a-hj-km-np-tv-z]{8})$", re.IGNORECASE)

# person() formals, in R's positional order (utils::person).
_PERSON_FORMALS = ("given", "family", "middle", "email", "role", "comment")
_PERSON_ALIASES = {"first": "given", "last": "family"}


class NotLiteral(ValueError):
    """The field uses something other than c()/person()/literals; do not evaluate."""


@dataclass(frozen=True)
class Person:
    """One credited person (or organisation, for ``fnd``). No email, by design."""

    given: str
    family: str
    roles: tuple[str, ...]
    orcid: str | None = None
    ror: str | None = None
    notes: tuple[str, ...] = ()  # free-text comment values (grant numbers, PI names, ...)

    @property
    def name(self) -> str:
        return " ".join(f"{self.given} {self.family}".split())


# ── tokenizer ────────────────────────────────────────────────────────────────

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0"}
_IDENT_START = re.compile(r"[A-Za-z.]")
_IDENT_BODY = re.compile(r"[A-Za-z0-9._]*")


def _tokenize(text: str) -> list[tuple[str, str]]:
    toks: list[tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == "#":  # R comment: to end of line
            while i < n and text[i] != "\n":
                i += 1
        elif ch in "(),=":
            toks.append((ch, ch))
            i += 1
        elif ch in "\"'":
            i, s = _read_string(text, i)
            toks.append(("str", s))
        elif ch == "`":
            j = text.find("`", i + 1)
            if j < 0:
                raise NotLiteral("unterminated backtick name")
            toks.append(("id", text[i + 1 : j]))
            i = j + 1
        elif _IDENT_START.match(ch):
            start = i
            j = _IDENT_BODY.match(text, i + 1).end()  # always matches (may be empty)
            # utils::person / base::c — a namespace qualifier is harmless; keep the last part.
            while text.startswith("::", j):
                if j + 2 >= n or not _IDENT_START.match(text[j + 2]):
                    raise NotLiteral("bad namespace qualifier")
                start = j + 2
                j = _IDENT_BODY.match(text, start + 1).end()
            toks.append(("id", text[start:j]))
            i = j
        else:
            raise NotLiteral(f"unsupported character {ch!r}")
    return toks


def _read_string(text: str, i: int) -> tuple[int, str]:
    quote = text[i]
    out: list[str] = []
    i += 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == quote:
            return i + 1, "".join(out)
        if ch == "\\":
            i += 1
            if i >= n:
                break
            esc = text[i]
            if esc in "ux":  # \uXXXX / \xXX
                width = 4 if esc == "u" else 2
                braced = text[i + 1 : i + 2] == "{"
                start = i + 2 if braced else i + 1
                hexd = text[start : start + width]
                if not re.fullmatch(rf"[0-9a-fA-F]{{1,{width}}}", hexd or "x"):
                    raise NotLiteral("bad unicode escape")
                out.append(chr(int(hexd, 16)))
                i = start + len(hexd) + (1 if braced else 0)
                continue
            if esc not in _ESCAPES:
                raise NotLiteral(f"unsupported escape \\{esc}")
            out.append(_ESCAPES[esc])
        else:
            out.append(ch)
        i += 1
    raise NotLiteral("unterminated string")


# ── call-tree parser (no evaluation) ─────────────────────────────────────────


@dataclass
class _Call:
    name: str
    args: list[tuple[str | None, object]]  # (argument name, str | None | _Call)


class _Parser:
    def __init__(self, toks: list[tuple[str, str]]):
        self.toks = toks
        self.pos = 0

    def _peek(self) -> tuple[str, str] | None:
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def _take(self, kind: str) -> str:
        tok = self._peek()
        if tok is None or tok[0] != kind:
            raise NotLiteral(f"expected {kind}")
        self.pos += 1
        return tok[1]

    def parse(self) -> object:
        value = self._expr(0)
        if self._peek() is not None:
            raise NotLiteral("trailing tokens")
        return value

    def _expr(self, depth: int) -> object:
        if depth > _MAX_DEPTH:
            raise NotLiteral("nested too deeply")
        tok = self._peek()
        if tok is None:
            raise NotLiteral("unexpected end")
        kind, val = tok
        if kind == "str":
            self.pos += 1
            return val
        if kind != "id":
            raise NotLiteral(f"unexpected {val!r}")
        self.pos += 1
        nxt = self._peek()
        if nxt is not None and nxt[0] == "(":
            if val not in ("c", "person"):
                raise NotLiteral(f"call to {val}() is not allowed")
            return _Call(val, self._args(depth))
        if val == "NULL":
            return None
        raise NotLiteral(f"bare name {val!r} (variable reference?)")

    def _args(self, depth: int) -> list[tuple[str | None, object]]:
        self._take("(")
        args: list[tuple[str | None, object]] = []
        while True:
            tok = self._peek()
            if tok is None:
                raise NotLiteral("unterminated call")
            if tok[0] == ")":
                self.pos += 1
                return args
            if tok[0] == ",":  # empty argument, e.g. person("A", "B", , "email")
                args.append((None, None))
                self.pos += 1
                continue
            name: str | None = None
            nxt = self.toks[self.pos + 1] if self.pos + 1 < len(self.toks) else None
            if tok[0] in ("id", "str") and nxt is not None and nxt[0] == "=":
                name = tok[1]
                self.pos += 2
            args.append((name, self._expr(depth + 1)))
            tok = self._peek()
            if tok is not None and tok[0] == ",":
                self.pos += 1
            elif tok is None or tok[0] != ")":
                raise NotLiteral("expected , or )")


# ── evaluation of the (already parsed, never executed) tree ──────────────────


def _strings(value: object) -> list[tuple[str | None, str]]:
    """Flatten a string / NULL / c(...) of strings into (name, string) pairs."""
    if value is None:
        return []
    if isinstance(value, str):
        return [(None, value)]
    assert isinstance(value, _Call)
    if value.name != "c":
        raise NotLiteral(f"{value.name}() where a string vector is expected")
    out: list[tuple[str | None, str]] = []
    for name, arg in value.args:
        for inner_name, s in _strings(arg):
            out.append((name or inner_name, s))
    return out


def _match_formal(name: str) -> str | None:
    """R argument matching: exact name, else a unique prefix of a formal."""
    name = _PERSON_ALIASES.get(name, name)
    if name in _PERSON_FORMALS:
        return name
    hits = [f for f in _PERSON_FORMALS if f.startswith(name)] if name else []
    return hits[0] if len(hits) == 1 else None


def _person(call: _Call) -> Person:
    bound: dict[str, object] = {}
    positional: list[object] = []
    for name, arg in call.args:
        if name is None:
            positional.append(arg)
            continue
        field = _match_formal(name)
        if field is None or field in bound:
            raise NotLiteral(f"unsupported person() argument {name!r}")
        bound[field] = arg
    free = [f for f in _PERSON_FORMALS if f not in bound]
    if len(positional) > len(free):
        raise NotLiteral("too many positional person() arguments")
    bound.update(zip(free, positional, strict=False))

    def text(field: str) -> str:
        # An email that landed in a name slot is dropped, never kept.
        words = (w for _, s in _strings(bound.get(field)) for w in s.split() if "@" not in w)
        return " ".join(words)

    comment = _strings(bound.get("comment"))
    middle = _strings(bound.get("middle"))
    if any(ORCID_RE.search(s) for _, s in middle):
        # person(..., c(ORCID = "…")) passed positionally after named args lands in `middle`
        # (R matches it there too); it's an ORCID comment, not a middle name.
        comment, bound["middle"] = [*comment, *middle], None

    given = " ".join(f"{text('given')} {text('middle')}".split())
    roles: list[str] = []
    for _, r in _strings(bound.get("role")):
        r = r.strip().lower()
        if r and r not in roles:
            roles.append(r)
    orcid, ror, notes = _comment_parts(comment)
    return Person(given, text("family"), tuple(roles), orcid, ror, notes)


def _comment_parts(
    items: list[tuple[str | None, str]],
) -> tuple[str | None, str | None, tuple[str, ...]]:
    orcid = ror = None
    notes: list[str] = []
    for key, value in items:
        k = (key or "").lower()
        if m := ORCID_RE.search(value):
            if k in ("", "orcid"):
                orcid = orcid or m.group(1).upper()
                continue
        if k == "ror" or _ROR_URL_RE.search(value) or _ROR_BARE_RE.match(value.strip()):
            m = _ROR_URL_RE.search(value) or _ROR_BARE_RE.match(value.strip())
            if m:
                ror = ror or f"https://ror.org/{m.group(1).lower()}"
                continue
        if value.strip():
            notes.append(value.strip())
    return orcid, ror, tuple(notes)


def _collect(value: object) -> list[Person]:
    if not isinstance(value, _Call):
        raise NotLiteral("Authors@R must be person() or c(person(), ...)")
    if value.name == "person":
        return [_person(value)]
    people: list[Person] = []
    for _, arg in value.args:
        people.extend(_collect(arg))
    return people


def parse_authors_r(text: str | None) -> list[Person] | None:
    """People from raw ``Authors@R`` code, or ``None`` when it isn't plain literals.

    ``None`` means "fall back to the rendered Author field"; an empty list means a
    literal ``c()`` with nobody in it.
    """
    if not text or not text.strip() or len(text) > _MAX_LEN:
        return None
    try:
        return _collect(_Parser(_tokenize(text)).parse())
    except NotLiteral:
        return None


# ── rendered ``Author`` fallback ─────────────────────────────────────────────

_AND_RE = re.compile(r"\s+(?:and|&)\s+")
_ROLES_RE = re.compile(r"\[([^\]]*)\]")
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_NAME_END_RE = re.compile(r"[\[(<]")


def _split_top_level(text: str) -> list[str]:
    """Split on commas that sit outside ``()`` / ``[]`` (roles and comments contain commas)."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _split_and(chunk: str) -> list[str]:
    """Split ``A B and C D`` into two entries, but leave ``Biostatistics and Bioinformatics``."""
    for m in _AND_RE.finditer(chunk):
        left, right = chunk[: m.start()], chunk[m.end() :]
        if len(left.split()) >= 2 and len(right.split()) >= 2:
            return [left, *_split_and(right)]
    return [chunk]


_MAX_NAME_WORDS = 6  # longer than this is a sentence ("X with contributions from Y, Z …")


def _clean_rendered_name(raw: str) -> tuple[str, str | None]:
    """A display name from free text: no emails/URLs, bare ORCIDs lifted out, or ``""``."""
    raw = re.split(r"\s+with\s+contributions?\b", raw, maxsplit=1, flags=re.IGNORECASE)[0]
    orcid = None
    words: list[str] = []
    for w in raw.split():
        if "@" in w or "://" in w or w.startswith("www."):
            continue
        if m := ORCID_RE.fullmatch(w.strip("()<>[]")):
            orcid = orcid or m.group(1).upper()
            continue
        words.append(w)
    name = " ".join(words).strip(" ,")
    return (name, orcid) if 0 < len(words) <= _MAX_NAME_WORDS else ("", orcid)


def parse_rendered(text: str | None) -> list[Person]:
    """Best-effort people from the rendered ``Author`` field.

    Lossy by nature: roles are in ``[…]``, ORCID/comment in ``(…)``, email in ``<…>``
    (dropped). A name with no ``[roles]`` yields a person with no roles.
    """
    if not text:
        return []
    people: list[Person] = []
    for chunk in _split_top_level(" ".join(text.split())):
        for entry in _split_and(chunk):
            entry = entry.strip(" .;")
            if not entry:
                continue
            m = _NAME_END_RE.search(entry)
            raw_name = entry[: m.start()] if m else entry
            name, name_orcid = _clean_rendered_name(raw_name)
            if not name:
                continue
            roles: list[str] = []
            for rm in _ROLES_RE.finditer(entry):
                for r in rm.group(1).split(","):
                    r = r.strip().lower()
                    if r and r not in roles:
                        roles.append(r)
            comments = [(None, c) for pm in _PAREN_RE.finditer(entry) for c in [pm.group(1)]]
            orcid, ror, notes = _comment_parts(comments)
            # An ORCID URL may sit in <…> inside the parens; the regex above still finds it.
            people.append(Person(name, "", tuple(roles), orcid or name_orcid, ror, notes))
    return people


# ── identity ────────────────────────────────────────────────────────────────


def normalize_name(name: str) -> str:
    """Casefolded, accent-stripped, punctuation-free name for identity keys."""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded.casefold()).split())
