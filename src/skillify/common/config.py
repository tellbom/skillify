"""Skillify configuration loading shared by the CLI and endpoint runtime."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


def skillify_home() -> Path:
    override = os.environ.get("SKILLIFY_HOME")
    if override:
        return Path(override)
    return Path.home() / ".skillify"


@dataclass(frozen=True)
class AgentPaths:
    config_dir: Path
    state_dir: Path
    cache_dir: Path
    log_dir: Path
    legacy_config_file: Path | None = None

    @property
    def config_path(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def legacy_config_path(self) -> Path:
        return self.legacy_config_file or self.config_dir / "config.yaml"

    @property
    def runtime_path(self) -> Path:
        return self.state_dir / "runtime.json"

    @property
    def log_path(self) -> Path:
        return self.log_dir / "agent.log"


@dataclass(frozen=True)
class AgentLocalConfig:
    provider: str = "opencode"
    allowed_workspaces: tuple[str, ...] = ()
    workspace_aliases: dict[str, str] = field(default_factory=dict)
    model_endpoint: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    allowed_model_hosts: tuple[str, ...] = ()
    credential_env_names: tuple[str, ...] = ()
    control_plane_url: str | None = None
    endpoint_token_file: str | None = None
    forgejo_mcp_credentials_file: str | None = None
    opencode_executable: str | None = None
    opencode_manifest_path: str | None = None
    opencode_artifact_root: str | None = None
    opencode_user_config_path: str | None = None
    shogun_manifest_path: str | None = None
    shogun_artifact_path: str | None = None
    shogun_install_root: str | None = None
    shogun_team_enabled: bool = False
    agent_host_mode: str = "official"
    agent_host_entrypoint: str | None = None
    node_executable: str = "node"
    allow_legacy_tui: bool = False


def load_agent_paths(
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> AgentPaths:
    env = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    config_override = env.get("SKILLIFY_AGENT_CONFIG_DIR")
    config_dir = Path(config_override) if config_override else user_home / ".skillctl"
    legacy_config_file = (
        config_dir / "config.yaml"
        if config_override else
        Path(env.get("XDG_CONFIG_HOME", user_home / ".config")) / "skillify" / "agent" / "config.yaml"
    )
    state_home = Path(env.get("XDG_STATE_HOME", user_home / ".local" / "state"))
    cache_home = Path(env.get("XDG_CACHE_HOME", user_home / ".cache"))
    return AgentPaths(
        config_dir=config_dir,
        state_dir=Path(env.get("SKILLIFY_AGENT_STATE_DIR", state_home / "skillify" / "agent")),
        cache_dir=Path(env.get("SKILLIFY_AGENT_CACHE_DIR", cache_home / "skillify" / "agent")),
        log_dir=Path(env.get("SKILLIFY_AGENT_LOG_DIR", state_home / "skillify" / "agent" / "log")),
        legacy_config_file=legacy_config_file,
    )


def load_agent_local_config(paths: AgentPaths) -> AgentLocalConfig:
    data: dict[str, Any] = {}
    try:
        loaded = json.loads(paths.config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        try:
            loaded = yaml.safe_load(paths.legacy_config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            loaded = None
        except yaml.YAMLError as exc:
            raise ValueError("legacy agent config must be valid YAML") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("agent settings must be valid JSON") from exc
    if loaded is not None:
        if not isinstance(loaded, dict):
            raise ValueError("agent settings must be an object")
        data = dict(loaded)
    scalar_overrides = {
        "SKILLIFY_AGENT_MODEL_ENDPOINT": "model_endpoint",
        "SKILLIFY_AGENT_MODEL_PROVIDER": "model_provider",
        "SKILLIFY_AGENT_MODEL_NAME": "model_name",
        "SKILLIFY_OPENCODE_MANIFEST_PATH": "opencode_manifest_path",
        "SKILLIFY_OPENCODE_ARTIFACT_ROOT": "opencode_artifact_root",
        "SKILLIFY_OPENCODE_USER_CONFIG_PATH": "opencode_user_config_path",
        "SKILLIFY_MCP_FORGEJO_CREDENTIALS_FILE": "forgejo_mcp_credentials_file",
        "SKILLIFY_OPENCODE_EXECUTABLE": "opencode_executable",
        "SKILLIFY_SHOGUN_MANIFEST_PATH": "shogun_manifest_path",
        "SKILLIFY_SHOGUN_ARTIFACT_PATH": "shogun_artifact_path",
        "SKILLIFY_SHOGUN_INSTALL_ROOT": "shogun_install_root",
        "SKILLIFY_AGENT_HOST_ENTRYPOINT": "agent_host_entrypoint",
        "SKILLIFY_AGENT_NODE_EXECUTABLE": "node_executable",
    }
    for env_name, key in scalar_overrides.items():
        if env_name in os.environ:
            data[key] = os.environ[env_name]
    for env_name, key in {
        "SKILLIFY_AGENT_ALLOWED_MODEL_HOSTS": "allowed_model_hosts",
        "SKILLIFY_AGENT_CREDENTIAL_ENV_NAMES": "credential_env_names",
    }.items():
        if env_name in os.environ:
            data[key] = [value.strip() for value in os.environ[env_name].split(",") if value.strip()]
    if "SKILLIFY_AGENT_SHOGUN_TEAM_ENABLED" in os.environ:
        data["shogun_team_enabled"] = os.environ["SKILLIFY_AGENT_SHOGUN_TEAM_ENABLED"].strip().lower() in {
            "1", "true", "yes", "on",
        }
    if "SKILLIFY_AGENT_HOST_MODE" in os.environ:
        data["agent_host_mode"] = os.environ["SKILLIFY_AGENT_HOST_MODE"]
    if "SKILLIFY_AGENT_ALLOW_LEGACY_TUI" in os.environ:
        data["allow_legacy_tui"] = os.environ["SKILLIFY_AGENT_ALLOW_LEGACY_TUI"].strip().lower() in {
            "1", "true", "yes", "on",
        }
    config = AgentLocalConfig(
        provider=str(data.get("provider", "opencode")),
        allowed_workspaces=tuple(data.get("allowed_workspaces", ())),
        workspace_aliases=dict(data.get("workspace_aliases", {})),
        model_endpoint=data.get("model_endpoint"),
        model_provider=data.get("model_provider"),
        model_name=data.get("model_name"),
        allowed_model_hosts=tuple(data.get("allowed_model_hosts", ())),
        credential_env_names=tuple(data.get("credential_env_names", ())),
        control_plane_url=data.get("control_plane_url"),
        endpoint_token_file=data.get("endpoint_token_file"),
        forgejo_mcp_credentials_file=data.get("forgejo_mcp_credentials_file"),
        opencode_executable=data.get("opencode_executable"),
        opencode_manifest_path=data.get("opencode_manifest_path"),
        opencode_artifact_root=data.get("opencode_artifact_root"),
        opencode_user_config_path=data.get("opencode_user_config_path"),
        shogun_manifest_path=data.get("shogun_manifest_path"),
        shogun_artifact_path=data.get("shogun_artifact_path"),
        shogun_install_root=data.get("shogun_install_root"),
        shogun_team_enabled=bool(data.get("shogun_team_enabled", False)),
        agent_host_mode=str(data.get("agent_host_mode", "official")),
        agent_host_entrypoint=data.get("agent_host_entrypoint"),
        node_executable=str(data.get("node_executable", "node")),
        allow_legacy_tui=bool(data.get("allow_legacy_tui", False)),
    )
    if config.provider not in {"opencode", "claude-code"}:
        raise ValueError("provider must be opencode or claude-code")
    if config.agent_host_mode not in {"official", "legacy"}:
        raise ValueError("agent_host_mode must be official or legacy")
    if config.agent_host_mode == "legacy" and not config.allow_legacy_tui:
        raise ValueError("legacy Agent TUI requires explicit allow_legacy_tui=true")
    if any(not Path(value).is_absolute() for value in config.allowed_workspaces):
        raise ValueError("allowed workspaces must be absolute")
    if len(set(config.allowed_workspaces)) != len(config.allowed_workspaces):
        raise ValueError("allowed workspaces must be unique")
    if any(not isinstance(alias, str) or not Path(path).is_absolute()
           for alias, path in config.workspace_aliases.items()):
        raise ValueError("workspace aliases must map names to absolute paths")
    if (config.opencode_user_config_path is not None and
            not Path(config.opencode_user_config_path).is_absolute()):
        raise ValueError("OpenCode user config path must be absolute")
    if (config.forgejo_mcp_credentials_file is not None and
            not Path(config.forgejo_mcp_credentials_file).is_absolute()):
        raise ValueError("Forgejo MCP credentials file path must be absolute")
    if (config.endpoint_token_file is not None and
            not Path(config.endpoint_token_file).is_absolute()):
        raise ValueError("endpoint token file path must be absolute")
    if (config.opencode_executable is not None and
            not Path(config.opencode_executable).is_absolute()):
        raise ValueError("OpenCode executable path must be absolute")
    if (config.agent_host_entrypoint is not None and
            not Path(config.agent_host_entrypoint).is_absolute()):
        raise ValueError("Agent Host entrypoint must be absolute")
    shogun_paths = (
        config.shogun_manifest_path, config.shogun_artifact_path, config.shogun_install_root,
    )
    if any(value is not None and not Path(value).is_absolute() for value in shogun_paths):
        raise ValueError("Shogun paths must be absolute")
    sequence_fields = (config.allowed_model_hosts, config.credential_env_names)
    if any(not isinstance(item, str) for sequence in sequence_fields for item in sequence):
        raise ValueError("model host and credential names must be strings")
    return config


def save_agent_local_config(paths: AgentPaths, config: AgentLocalConfig) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = paths.config_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(paths.config_path)


@dataclass
class SkillifyConfig:
    forgejo_url: str | None = None
    forgejo_org: str | None = None
    forgejo_token: str | None = None
    devpi_index_url: str | None = None
    webhook_secret: str | None = None  # T2.1: shared secret for Forgejo webhook HMAC verification
    endpoint_task_signing_secret: str | None = None
    endpoint_device_secret: str | None = None
    shogun_team_enabled: bool = False
    # Skillify business DB. Production uses the external DM8 schema initialized by
    # infra/dm8-init/01-skillify-schema.sql; SQLite remains available for local tests.
    index_db_url: str | None = None
    # M4: Keycloak JWT validation for write endpoints (upload). Frontend auth (login redirect,
    # RBAC menu bridge to the separate Rbac.Api) is a Vue3-side concern (web/) and doesn't read
    # this config — this is only what the FastAPI backend needs to *validate* a bearer token.
    keycloak_realm_url: str | None = None  # e.g. https://sso.example.com/realms/internal
    keycloak_jwks_url: str | None = None  # optional container-internal cert endpoint
    keycloak_audience: str | None = None  # expected `aud` claim (this backend's client id)
    # T6.2: opt-in client->server event reporting (skillify/common/telemetry.py). Off unless
    # explicitly configured — no network call, no data collected, by default.
    web_base_url: str | None = None  # e.g. http://localhost:8089 (skillify-web, T3.1)
    reporting_enabled: bool = False
    # C-3: Web uploads can mirror validated source into Forgejo Git before publishing.
    # Disabled by default for local/fake-Forgejo use; the complete Compose stack enables it.
    web_upload_git_enabled: bool = False
    # M-D (docs/review-m2-m6.md): caps on the browser upload endpoint to bound memory use —
    # a raw upload larger than max_upload_bytes is rejected before being read into memory;
    # max_extracted_bytes/max_extracted_files bound the zip's *decompressed* size/entry count
    # (a zip bomb can have a tiny compressed size but a huge decompressed one).
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MiB raw .zip
    max_extracted_bytes: int = 100 * 1024 * 1024  # 100 MiB decompressed total
    max_extracted_files: int = 5000
    build_ttl_seconds: int = 86400
    default_targets: list[str] = field(default_factory=lambda: ["claude"])
    home: Path = field(default_factory=skillify_home)

    @property
    def skills_dir(self) -> Path:
        return self.home / "skills"

    @property
    def venvs_dir(self) -> Path:
        return self.home / "venvs"

    @property
    def agents_dir(self) -> Path:
        return self.home / "agents"

    @property
    def locks_dir(self) -> Path:
        return self.home / "locks"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def config_path(self) -> Path:
        return self.home / "config.yaml"

    def ensure_dirs(self) -> None:
        for d in (self.skills_dir, self.venvs_dir, self.agents_dir, self.locks_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)


_ENV_OVERRIDES = {
    "SKILLIFY_FORGEJO_URL": "forgejo_url",
    "SKILLIFY_FORGEJO_ORG": "forgejo_org",
    "SKILLIFY_FORGEJO_TOKEN": "forgejo_token",
    "SKILLIFY_DEVPI_INDEX_URL": "devpi_index_url",
    "SKILLIFY_WEBHOOK_SECRET": "webhook_secret",
    "SKILLIFY_ENDPOINT_TASK_SIGNING_SECRET": "endpoint_task_signing_secret",
    "SKILLIFY_ENDPOINT_DEVICE_SECRET": "endpoint_device_secret",
    "SKILLIFY_INDEX_DB_URL": "index_db_url",
    "SKILLIFY_KEYCLOAK_REALM_URL": "keycloak_realm_url",
    "SKILLIFY_KEYCLOAK_JWKS_URL": "keycloak_jwks_url",
    "SKILLIFY_KEYCLOAK_AUDIENCE": "keycloak_audience",
    "SKILLIFY_WEB_BASE_URL": "web_base_url",
}


def load_config(home: Path | None = None) -> SkillifyConfig:
    """Load ~/.skillify/config.yaml, then apply SKILLIFY_* env var overrides.

    Missing config file is not an error — callers (e.g. `doctor`) are expected to
    report that as a checkable condition, not crash.
    """
    home = home or skillify_home()
    data: dict[str, Any] = {}
    config_path = home / "config.yaml"
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded

    cfg = SkillifyConfig(
        forgejo_url=data.get("forgejo_url"),
        forgejo_org=data.get("forgejo_org"),
        forgejo_token=data.get("forgejo_token"),
        devpi_index_url=data.get("devpi_index_url"),
        webhook_secret=data.get("webhook_secret"),
        endpoint_task_signing_secret=data.get("endpoint_task_signing_secret"),
        endpoint_device_secret=data.get("endpoint_device_secret"),
        shogun_team_enabled=bool(data.get("shogun_team_enabled", False)),
        index_db_url=data.get("index_db_url"),
        keycloak_realm_url=data.get("keycloak_realm_url"),
        keycloak_jwks_url=data.get("keycloak_jwks_url"),
        keycloak_audience=data.get("keycloak_audience"),
        web_base_url=data.get("web_base_url"),
        reporting_enabled=bool(data.get("reporting_enabled", False)),
        web_upload_git_enabled=bool(data.get("web_upload_git_enabled", False)),
        max_upload_bytes=int(data.get("max_upload_bytes") or 20 * 1024 * 1024),
        max_extracted_bytes=int(data.get("max_extracted_bytes") or 100 * 1024 * 1024),
        max_extracted_files=int(data.get("max_extracted_files") or 5000),
        build_ttl_seconds=int(data.get("build_ttl_seconds") or 86400),
        default_targets=data.get("default_targets") or ["claude"],
        home=home,
    )

    for env_var, attr in _ENV_OVERRIDES.items():
        value = os.environ.get(env_var)
        if value:
            setattr(cfg, attr, value)

    for env_var, attr in (
        ("SKILLIFY_MAX_UPLOAD_BYTES", "max_upload_bytes"),
        ("SKILLIFY_MAX_EXTRACTED_BYTES", "max_extracted_bytes"),
        ("SKILLIFY_MAX_EXTRACTED_FILES", "max_extracted_files"),
        ("SKILLIFY_BUILD_TTL_SECONDS", "build_ttl_seconds"),
    ):
        value = os.environ.get(env_var)
        if value:
            setattr(cfg, attr, int(value))

    reporting_env = os.environ.get("SKILLIFY_REPORTING_ENABLED")
    if reporting_env is not None:
        cfg.reporting_enabled = reporting_env.strip().lower() in ("1", "true", "yes", "on")

    web_git_env = os.environ.get("SKILLIFY_WEB_UPLOAD_GIT_ENABLED")
    if web_git_env is not None:
        cfg.web_upload_git_enabled = web_git_env.strip().lower() in ("1", "true", "yes", "on")

    team_env = os.environ.get("SKILLIFY_SHOGUN_TEAM_ENABLED")
    if team_env is not None:
        cfg.shogun_team_enabled = team_env.strip().lower() in ("1", "true", "yes", "on")

    return cfg
