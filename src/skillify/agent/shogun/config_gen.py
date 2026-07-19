"""Generate the minimal Shogun runtime configuration without embedding secrets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


_REF = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s]+$")
_ENV = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class GeneratedShogunConfig:
    settings_path: Path
    permissions_path: Path
    queue_dir: Path
    command: tuple[str, ...]
    environment: dict[str, str]


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
    config_dir = root / "config"
    queue_dir = root / "queue"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for child in (queue_dir, queue_dir / "tasks", queue_dir / "reports", queue_dir / "inbox"):
        child.mkdir(parents=True, exist_ok=True, mode=0o700)
    cli_type = "opencode" if preferred_cli == "opencode" else "claude"
    agents = {
        "karo": {"type": cli_type, "model": model},
        **{
            f"ashigaru{index}": {"type": cli_type, "model": model}
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

    entrypoint = Path(install_root) / "shutsujin_departure.sh"
    environment = {
        "SHOGUN_QUEUE_DIR": str(queue_dir),
        "SHOGUN_SETTINGS_FILE": str(settings_path),
        **public_env,
    }
    return GeneratedShogunConfig(
        settings_path, permissions_path, queue_dir,
        (str(entrypoint), "-c", "--permission-mode", "default"), environment,
    )
