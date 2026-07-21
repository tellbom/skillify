"""Generate the minimal Shogun runtime configuration without embedding secrets."""

from __future__ import annotations

import json
import re
import os
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from skillify.agent.shogun.git_guard import write_git_guard


_REF = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s]+$")
_ENV = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class GeneratedShogunConfig:
    settings_path: Path
    permissions_path: Path
    queue_dir: Path
    command: tuple[str, ...]
    environment: dict[str, str]


_MUTABLE_TOP_LEVEL = frozenset({"config", "queue", "logs", "dashboard.md"})


def _project_runtime(install_root: Path, run_dir: Path) -> None:
    """Project the immutable bundle into a task directory without copying source."""
    source = Path(install_root).resolve(strict=True)
    target = Path(run_dir).resolve()
    if source == target or source in target.parents:
        raise ValueError("Shogun run directory must be outside the install root")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        if relative.parts[0] in _MUTABLE_TOP_LEVEL:
            continue
        destination = target / relative
        if item.is_symlink():
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink() and os.readlink(destination) == os.readlink(item):
                    continue
                raise FileExistsError(f"Shogun runtime projection conflicts at {relative}")
            destination.symlink_to(os.readlink(item), target_is_directory=item.is_dir())
            continue
        if item.is_dir():
            destination.mkdir(exist_ok=True, mode=0o700)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            if not destination.samefile(item):
                raise FileExistsError(f"Shogun runtime projection conflicts at {relative}")
            continue
        try:
            os.link(item, destination)
        except OSError as exc:
            raise OSError(
                f"Shogun runtime projection requires same-filesystem hard links: {relative}"
            ) from exc


def _skillify_bin_dir(root: Path) -> Path:
    """The directory prepended to PATH for Worker panes.

    Always created (and always prepended to PATH by the caller), independent
    of whether any individual launcher below (e.g. the tmux compatibility
    shim) is applicable — otherwise tools relying on this directory, such as
    the git push-denial wrapper, would silently stop taking effect whenever
    an optional launcher is absent.
    """
    launcher_dir = root / ".skillify-bin"
    launcher_dir.mkdir(mode=0o700, exist_ok=True)
    return launcher_dir


def _write_tmux_compatibility_launcher(launcher_dir: Path) -> None:
    """Bridge the one cosmetic tmux option missing from the approved 3.0a host."""
    executable = shutil.which("tmux")
    if executable is None:
        return
    launcher = launcher_dir / "tmux"
    quoted = shlex.quote(executable)
    launcher.write_text(
        "#!/bin/sh\n"
        "if [ \"$#\" -eq 4 ] && [ \"$1\" = set-option ] && [ \"$2\" = -g ] "
        "&& [ \"$3\" = window-size ] && [ \"$4\" = latest ]; then\n"
        f"  exec {quoted} set-option -g window-size largest\n"
        "fi\n"
        f"exec {quoted} \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o700)


def generate_config(
    *,
    install_root: Path,
    run_dir: Path,
    preferred_cli: str,
    worker_count: int,
    model: str,
    credential_refs: Mapping[str, str] | None = None,
    endpoint_environment: Mapping[str, str] | None = None,
    work_packages: tuple[dict[str, object], ...] = (),
    mcp_servers: Mapping[str, dict[str, object]] | None = None,
    network_allowlist: tuple[str, ...] = (),
    mcp_network_allowlist: Mapping[str, tuple[str, ...]] | None = None,
    worker_worktrees: Mapping[str, Path] | None = None,
) -> GeneratedShogunConfig:
    if preferred_cli not in {"opencode", "claude-code"}:
        raise ValueError("Shogun supports only OpenCode or Claude Code")
    if type(worker_count) is not int or not 1 <= worker_count <= 7:
        raise ValueError("Shogun worker count must be between 1 and 7")
    refs = dict(credential_refs or {})
    if any(not _ENV.fullmatch(name) or not _REF.fullmatch(value) for name, value in refs.items()):
        raise ValueError("Shogun credentials must be named references")
    public_env = dict(endpoint_environment or {})
    if any(not _ENV.fullmatch(name) or not isinstance(value, str) for name, value in public_env.items()):
        raise ValueError("Shogun endpoint environment is invalid")
    forbidden = {name for name in public_env if any(word in name for word in ("KEY", "TOKEN", "SECRET", "COOKIE"))}
    if forbidden:
        raise ValueError("Shogun endpoint environment cannot contain secrets")

    root = Path(run_dir)
    _project_runtime(Path(install_root), root)
    config_dir = root / "config"
    queue_dir = root / "queue"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for child in (queue_dir, queue_dir / "tasks", queue_dir / "reports", queue_dir / "inbox"):
        child.mkdir(parents=True, exist_ok=True, mode=0o700)
    cli_type = "opencode" if preferred_cli == "opencode" else "claude"
    worktrees = dict(worker_worktrees or {})

    def _worker_agent(worker_id: str) -> dict[str, object]:
        agent: dict[str, object] = {"type": cli_type, "model": model}
        worktree = worktrees.get(worker_id)
        if worktree is not None:
            agent["env"] = {
                "SKILLIFY_WORKER_ID": worker_id,
                "SKILLIFY_WORKTREE": str(worktree),
            }
        return agent

    agents = {
        "shogun": {"type": cli_type, "model": model},
        "karo": {"type": cli_type, "model": model},
        **{
            f"ashigaru{index}": _worker_agent(f"ashigaru{index}")
            for index in range(1, worker_count + 1)
        },
        "gunshi": {"type": cli_type, "model": model},
    }
    settings = {
        "language": "en",
        "cli": {"agents": agents},
        "skillify": {"credential_refs": refs},
    }
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    settings_path.chmod(0o600)

    package_permissions: dict[str, dict[str, object]] = {}
    worker_mcp: dict[str, list[str]] = {}
    available_mcp = set((mcp_servers or {}).keys())
    for index, package in enumerate(work_packages, start=1):
        worker = f"ashigaru{index}"
        allowed_paths = package.get("allowedPaths", [])
        if not isinstance(allowed_paths, (list, tuple)) or any(
            not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts
            for path in allowed_paths
        ):
            raise ValueError("Shogun work-package paths must be relative and bounded")
        read_only = package.get("readOnly") is True or package.get("access") == "read"
        requested_mcp = package.get("recommendedMcp", [])
        if not isinstance(requested_mcp, (list, tuple)):
            raise ValueError("Shogun work-package MCP declarations must be a list")
        package_permissions[worker] = {
            "read": list(allowed_paths),
            "edit": [] if read_only else list(allowed_paths),
        }
        worker_mcp[worker] = sorted(set(requested_mcp) & available_mcp)
    package_network = {
        target for name, targets in (mcp_network_allowlist or {}).items()
        if name in available_mcp for target in targets
    }
    effective_network = sorted(set(network_allowlist) & package_network)
    permissions = {
        "common": {
            "edit_deny": [".git/**", "queue/inbox/*.yaml"],
            "network_default": "deny",
            "network_allow": effective_network,
        },
        "roles": {
            "karo": {"display_name": "Coordinator", "read": ["queue/reports/**"], "edit": []},
            **package_permissions,
            "gunshi": {"display_name": "Reviewer", "read": ["**/*"], "edit": []},
            "integration": {
                "display_name": "Integration", "read": ["**/*"],
                "edit": sorted({path for item in package_permissions.values() for path in item["edit"]}),
                "git_push": "deny",
            },
        },
    }
    permissions_path = config_dir / "opencode-permissions.yaml"
    permissions_path.write_text(yaml.safe_dump(permissions, sort_keys=False), encoding="utf-8")
    permissions_path.chmod(0o600)
    settings["skillify"].update({
        "worker_mcp": worker_mcp,
        "network_allowlist": effective_network,
        "worker_shell_residual_risk": "trusted-intranet-host-only",
    })
    settings_path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    settings_path.chmod(0o600)

    home_dir = root / "home"
    home_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if preferred_cli == "claude-code":
        # Each task gets an isolated HOME. Seed only non-secret UI state so the
        # CLI reaches its prompt instead of blocking every pane on first-run
        # theme/onboarding dialogs; credentials still arrive over the socket.
        claude_state = home_dir / ".claude.json"
        claude_state.write_text(json.dumps({
            "hasCompletedOnboarding": True,
            "theme": "dark",
            "projects": {
                str(root.resolve()): {"hasTrustDialogAccepted": True},
            },
        }), encoding="utf-8")
        claude_state.chmod(0o600)
    bin_dir = _skillify_bin_dir(root)
    _write_tmux_compatibility_launcher(bin_dir)
    write_git_guard(bin_dir, root / "logs" / "git-guard.jsonl")
    entrypoint = root / "shutsujin_departure.sh"
    environment = {
        "SHOGUN_QUEUE_DIR": str(queue_dir),
        "SHOGUN_SETTINGS_FILE": str(settings_path),
        "HOME": str(home_dir),
        **(
            {"OPENCODE_DISABLE_AUTOUPDATE": "1"}
            if preferred_cli == "opencode"
            else {"DISABLE_AUTOUPDATER": "1"}
        ),
        **public_env,
    }
    environment["PATH"] = os.pathsep.join((
        str(bin_dir), os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    ))
    return GeneratedShogunConfig(
        settings_path, permissions_path, queue_dir,
        (str(entrypoint), "-c", "--permission-mode", "default"), environment,
    )
