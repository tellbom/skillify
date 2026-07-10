"""Parse '<namespace>/<name>[@version]' identifiers used across CLI commands."""

from __future__ import annotations

import re

_SEGMENT_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def is_valid_segment(value: str) -> bool:
    """True if `value` is a valid namespace/name segment (spec §3.1: lowercase alnum + `-`,
    no path separators, no leading/trailing `-`)."""
    return bool(_SEGMENT_RE.match(value))


class InvalidIdentifier(Exception):
    pass


def parse_identifier(identifier: str) -> tuple[str, str, str | None]:
    rest, _, version = identifier.partition("@")
    if "/" not in rest:
        raise InvalidIdentifier(f"expected '<namespace>/<name>[@version]', got {identifier!r}")
    namespace, _, name = rest.partition("/")
    if not is_valid_segment(namespace) or not is_valid_segment(name):
        raise InvalidIdentifier(f"namespace/name must match {_SEGMENT_RE.pattern}, got {identifier!r}")
    return namespace, name, (version or None)
