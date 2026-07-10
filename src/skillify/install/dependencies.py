"""Recursive `dependencies.skills` resolution + install (T1.5).

Python dependencies are handled per-skill inside `installer.install_skill` (venv + `uv pip
install --index-url <devpi>`, T1.4/T1.5); this module is specifically the skill-to-skill
dependency graph walk PLAN.md §4 describes as "解析 skill 间依赖递归安装".
"""

from __future__ import annotations

from dataclasses import dataclass

from skillify.common.config import SkillifyConfig
from skillify.install.installer import InstallError, install_skill
from skillify.install.lock import SkillLock
from skillify.install.semver_range import max_satisfying
from skillify.publish.forgejo_client import ForgejoClient, ForgejoError


class DependencyError(Exception):
    pass


@dataclass
class InstallPlanEntry:
    identifier: str
    lock: SkillLock


def resolve_skill_dependency_version(
    cfg: SkillifyConfig, namespace: str, name: str, range_str: str
) -> str:
    if not cfg.forgejo_url or not cfg.forgejo_token:
        raise DependencyError(
            f"cannot resolve {namespace}/{name}@{range_str}: forgejo_url/forgejo_token not configured"
        )
    org = cfg.forgejo_org or namespace
    client = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    try:
        releases = client.list_releases(org, name)
    except ForgejoError as exc:
        raise DependencyError(str(exc)) from exc
    versions = [r.tag_name.removeprefix("v") for r in releases]
    best = max_satisfying(versions, range_str)
    if best is None:
        raise DependencyError(
            f"no published version of {namespace}/{name} satisfies {range_str!r} "
            f"(available: {versions or 'none'})"
        )
    return best


def install_with_dependencies(
    identifier: str,
    *,
    cfg: SkillifyConfig,
    source_override: str | None = None,
    _visiting: frozenset[str] | None = None,
    _installed: dict[str, SkillLock] | None = None,
) -> dict[str, SkillLock]:
    """Install `identifier` and everything under its `dependencies.skills`, depth-first.

    Returns a map of "namespace/name" -> SkillLock for every skill installed in this call
    (including the root). Raises DependencyError on a dependency cycle.

    Diamond dependencies (A->B, A->C, B->D, C->D) are installed at most once per call (F4):
    `_installed` is threaded through the whole recursive walk (not just merged from return
    values), so the second time D is reached its already-recorded lock is reused instead of
    re-downloading/re-installing. A skill requested twice at two different versions in the
    same run is a real conflict — since the neutral dir holds one version per skill at a
    time (PLAN.md §4) — and raises DependencyError rather than silently overwriting.
    """
    visiting = _visiting or frozenset()
    installed = _installed if _installed is not None else {}
    root_key = identifier.split("@", 1)[0]
    if root_key in visiting:
        raise DependencyError(f"dependency cycle detected: {' -> '.join([*visiting, root_key])}")

    requested_version = identifier.split("@", 1)[1] if "@" in identifier else None
    if root_key in installed:
        already = installed[root_key]
        if requested_version and requested_version != already.version:
            raise DependencyError(
                f"version conflict for {root_key}: already installed at {already.version} "
                f"earlier in this run, but also required at {requested_version}"
            )
        return installed  # already installed via another branch of the dependency graph

    lock = install_skill(identifier, cfg=cfg, source_override=source_override)
    installed[lock.identifier] = lock

    if lock.skillDeps and source_override:
        raise DependencyError(
            f"{lock.identifier} declares dependencies.skills but was installed via --source "
            "(no registry context to resolve dependency versions from)"
        )

    for dep in lock.skillDeps:
        dep_ident, _, dep_range = dep.partition("@")
        dep_namespace, dep_name = dep_ident.split("/", 1)
        dep_version = resolve_skill_dependency_version(cfg, dep_namespace, dep_name, dep_range)
        install_with_dependencies(
            f"{dep_namespace}/{dep_name}@{dep_version}",
            cfg=cfg,
            _visiting=visiting | {root_key},
            _installed=installed,
        )

    return installed
