"""Parser for Debian Control File (DCF) text — the format of VIEWS & DESCRIPTION.

Records are separated by blank lines; each field is ``Key: value`` with
continuation lines indented by whitespace. Field values are returned with
continuation newlines folded to single spaces (the common case for VIEWS), which
is what every consumer here wants.
"""

from __future__ import annotations

from collections.abc import Iterator


def parse_dcf(text: str) -> list[dict[str, str]]:
    """Parse DCF ``text`` into a list of records (one dict per stanza)."""
    return list(_iter_records(text))


def _iter_records(text: str) -> Iterator[dict[str, str]]:
    record: dict[str, str] = {}
    key: str | None = None
    for raw in text.splitlines():
        if not raw.strip():  # blank line ends a record
            if record:
                yield record
                record, key = {}, None
            continue
        if raw[0].isspace():  # continuation of the previous field
            if key is not None:
                record[key] = f"{record[key]} {raw.strip()}".strip()
            continue
        head, sep, val = raw.partition(":")
        if not sep:  # malformed line without a colon — skip defensively
            continue
        key = head.strip()
        record[key] = val.strip()
    if record:
        yield record


def split_list(value: str | None) -> list[str]:
    """Split a comma-separated DCF field (biocViews, Depends, …) into clean items.

    Version constraints like ``R (>= 4.3)`` keep only the package/term name.
    """
    if not value:
        return []
    out = []
    for part in value.split(","):
        name = part.strip().split(" ")[0].split("(")[0].strip()
        if name:
            out.append(name)
    return out


def parse_maintainer(value: str | None) -> tuple[str | None, str | None]:
    """Split a ``Name <email>`` maintainer string into ``(name, email)``."""
    if not value:
        return None, None
    name, _, rest = value.partition("<")
    email = rest.split(">")[0].strip() if rest else None
    return (name.strip() or None), (email or None)
