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

    permissions = {
        "common": {"edit_deny": [".git/**", "queue/inbox/*.yaml"]},
        "roles": {
            "coordinator": {"read": ["**/*"], "edit": []},
            "worker": {"read": ["**/*"], "edit": []},
            "reviewer": {"read": ["**/*"], "edit": []},
        },
    }
    permissions_path = config_dir / "opencode-permissions.yaml"
    permissions_path.write_text(yaml.safe_dump(permissions, sort_keys=False), encoding="utf-8")
    permissions_path.chmod(0o600)

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
