"""Push validated Web-upload source into Forgejo Git without crossing DB boundaries."""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from skillify.common.config import SkillifyConfig
from skillify.publish.forgejo_client import ForgejoClient, ForgejoError


class GitSourceError(ForgejoError):
    pass


_EXCLUDED_NAMES = {
    ".git",
    ".DS_Store",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
}


def _run_git(args: list[str], *, cwd: Path | None, env: dict[str, str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise GitSourceError(f"failed to start git: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitSourceError(f"git {' '.join(args[:2])} failed: {detail}")
    return result.stdout.strip()


def _git_env(username: str, token: str) -> dict[str, str]:
    credentials = base64.b64encode(f"{username}:{token}".encode("utf-8")).decode("ascii")
    env = os.environ.copy()
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {credentials}",
        }
    )
    return env


def _replace_worktree(repo_dir: Path, skill_dir: Path) -> None:
    for child in repo_dir.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for source in skill_dir.rglob("*"):
        relative = source.relative_to(skill_dir)
        if any(part in _EXCLUDED_NAMES for part in relative.parts):
            continue
        target = repo_dir / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def push_skill_source(
    skill_dir: Path,
    cfg: SkillifyConfig,
    *,
    org: str,
    repo: str,
    tag: str,
    uploader: str,
) -> str:
    """Create one source commit and version tag through Forgejo-managed Git."""
    if not cfg.forgejo_url or not cfg.forgejo_token:
        raise GitSourceError("forgejo_url / forgejo_token not configured")

    client = ForgejoClient(cfg.forgejo_url, cfg.forgejo_token)
    client.ensure_org_repo(org, repo)
    service_username = client.current_username()
    git_env = _git_env(service_username, cfg.forgejo_token)
    clone_url = f"{cfg.forgejo_url.rstrip('/')}/{org}/{repo}.git"
    safe_uploader = re.sub(r"[^A-Za-z0-9_.-]+", "-", uploader).strip("-") or "skillify-user"

    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="web-git-", dir=cfg.cache_dir) as temp_dir:
        repo_dir = Path(temp_dir) / "repo"
        _run_git(["clone", "--quiet", clone_url, str(repo_dir)], cwd=None, env=git_env)
        branch = _run_git(["branch", "--show-current"], cwd=repo_dir, env=git_env)
        if not branch:
            raise GitSourceError("Forgejo repository has no default branch; initialize it before Web upload")

        _replace_worktree(repo_dir, Path(skill_dir))
        _run_git(["config", "user.name", uploader or "Skillify Web"], cwd=repo_dir, env=git_env)
        _run_git(
            ["config", "user.email", f"{safe_uploader}@skillify.local"], cwd=repo_dir, env=git_env
        )
        _run_git(["add", "--all"], cwd=repo_dir, env=git_env)
        changed = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=repo_dir, env=git_env, check=False
        ).returncode
        if changed not in (0, 1):
            raise GitSourceError("git diff --cached failed")
        if changed == 1:
            _run_git(["commit", "--quiet", "-m", f"Publish {repo} {tag}"], cwd=repo_dir, env=git_env)

        head = _run_git(["rev-parse", "HEAD"], cwd=repo_dir, env=git_env)
        head_tree = _run_git(["rev-parse", "HEAD^{tree}"], cwd=repo_dir, env=git_env)
        remote_tag = _run_git(
            ["ls-remote", "--tags", "origin", f"refs/tags/{tag}"], cwd=repo_dir, env=git_env
        )
        if remote_tag:
            _run_git(["fetch", "--quiet", "origin", f"refs/tags/{tag}"], cwd=repo_dir, env=git_env)
            remote_tree = _run_git(["rev-parse", "FETCH_HEAD^{tree}"], cwd=repo_dir, env=git_env)
            if remote_tree != head_tree:
                raise GitSourceError(f"Forgejo tag {tag} already points to different source")
            return remote_tag.split()[0]

        _run_git(
            ["push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"], cwd=repo_dir, env=git_env
        )
        _run_git(["tag", tag], cwd=repo_dir, env=git_env)
        _run_git(["push", "--quiet", "origin", f"refs/tags/{tag}"], cwd=repo_dir, env=git_env)
        return head
