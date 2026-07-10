"""Tests for T1.5's semver range matcher."""

from __future__ import annotations

import pytest

from skillify.install.semver_range import max_satisfying, satisfies


@pytest.mark.parametrize(
    "version,range_str,expected",
    [
        ("1.2.3", "1.2.3", True),
        ("1.2.4", "1.2.3", False),
        ("1.2.3", ">=1.2.0", True),
        ("1.1.9", ">=1.2.0", False),
        ("1.2.3", "^1.2.0", True),
        ("1.9.9", "^1.2.0", True),
        ("2.0.0", "^1.2.0", False),
        ("0.2.3", "^0.2.0", True),
        ("0.3.0", "^0.2.0", False),
        ("1.2.5", "~1.2.0", True),
        ("1.3.0", "~1.2.0", False),
        ("1.2.3", "<2.0.0", True),
        ("2.0.0", "<2.0.0", False),
    ],
)
def test_satisfies(version: str, range_str: str, expected: bool) -> None:
    assert satisfies(version, range_str) is expected


def test_max_satisfying_picks_highest_matching() -> None:
    versions = ["1.0.0", "1.2.0", "1.2.3", "1.9.9", "2.0.0"]
    assert max_satisfying(versions, "^1.2.0") == "1.9.9"
    assert max_satisfying(versions, ">=2.0.0") == "2.0.0"
    assert max_satisfying(versions, "^3.0.0") is None
