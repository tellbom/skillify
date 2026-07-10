"""Minimal semver-range matching for `dependencies.skills` entries (T1.5).

Supports the operators validated by the manifest schema/validator (spec §4 rule 7):
exact ("1.2.3"), ">=", "<=", ">", "<", "^" (caret), "~" (tilde).
"""

from __future__ import annotations

from packaging.version import Version

_OPERATORS = ("^", "~", ">=", "<=", ">", "<")


def parse_range(range_str: str) -> tuple[str, Version]:
    range_str = range_str.strip()
    for op in _OPERATORS:
        if range_str.startswith(op):
            return op, Version(range_str[len(op):].strip())
    return "=", Version(range_str)


def satisfies(version_str: str, range_str: str) -> bool:
    op, base = parse_range(range_str)
    v = Version(version_str)
    if op == "=":
        return v == base
    if op == ">=":
        return v >= base
    if op == "<=":
        return v <= base
    if op == ">":
        return v > base
    if op == "<":
        return v < base
    if op == "^":
        if base.major > 0:
            upper = Version(f"{base.major + 1}.0.0")
        elif base.minor > 0:
            upper = Version(f"0.{base.minor + 1}.0")
        else:
            upper = Version(f"0.0.{base.micro + 1}")
        return base <= v < upper
    if op == "~":
        upper = Version(f"{base.major}.{base.minor + 1}.0")
        return base <= v < upper
    raise ValueError(f"unsupported range operator in {range_str!r}")  # pragma: no cover


def max_satisfying(versions: list[str], range_str: str) -> str | None:
    matching = [v for v in versions if satisfies(v, range_str)]
    if not matching:
        return None
    return max(matching, key=Version)
