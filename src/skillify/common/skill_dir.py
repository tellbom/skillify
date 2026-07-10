"""Shared helper: re-home an extracted skill tree under a directory whose basename matches
its manifest's declared `name` — required because `validate_skill_dir`'s standalone check
(spec §4 rule 3) requires directory basename == manifest name, but content pulled from a
Forgejo archive (T2.1) or a browser zip upload (T4.2) arrives in an arbitrarily-named dir.

M-B (docs/review-m2-m6.md): `declared_name` comes straight from untrusted `skill.yaml`
content (or, in the webhook path, an untrusted repo name) and used to be joined onto
`dest_root` with no validation — a crafted `name: ../../evil` (or an absolute path, which
`Path.__truediv__` would let replace `dest_root` outright) could move the extracted tree
outside `dest_root` before schema validation ever runs. Reject anything that isn't a bare
`namespace`/`name`-shaped segment before touching the filesystem, and re-check the resolved
destination is still inside `dest_root` as a second layer of defense.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from skillify.common.identifier import is_valid_segment


class InvalidDeclaredName(Exception):
    pass


def rehome_to_declared_name(skill_dir: Path, declared_name: str, dest_root: Path) -> Path:
    if not is_valid_segment(declared_name):
        raise InvalidDeclaredName(
            f"skill.yaml name {declared_name!r} is not a valid path segment "
            "(expected lowercase alnum + '-', no separators)"
        )

    dest_root = dest_root.resolve()
    dest = (dest_root / declared_name).resolve()
    if dest != dest_root and dest.parent != dest_root:
        raise InvalidDeclaredName(f"resolved destination {dest} escapes {dest_root}")

    if skill_dir.resolve() == dest:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(skill_dir), str(dest))
    return dest
