"""~/.skillify layout + config.yaml loading (shared by CLI, installer, publisher, doctor)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def skillify_home() -> Path:
    override = os.environ.get("SKILLIFY_HOME")
    if override:
        return Path(override)
    return Path.home() / ".skillify"


@dataclass
class SkillifyConfig:
    forgejo_url: str | None = None
    forgejo_org: str | None = None
    forgejo_token: str | None = None
    devpi_index_url: str | None = None
    webhook_secret: str | None = None  # T2.1: shared secret for Forgejo webhook HMAC verification
    # Skillify business DB. Production uses the external DM8 schema initialized by
    # infra/dm8-init/01-skillify-schema.sql; SQLite remains available for local tests.
    index_db_url: str | None = None
    # M4: Keycloak JWT validation for write endpoints (upload). Frontend auth (login redirect,
    # RBAC menu bridge to the separate Rbac.Api) is a Vue3-side concern (web/) and doesn't read
    # this config — this is only what the FastAPI backend needs to *validate* a bearer token.
    keycloak_realm_url: str | None = None  # e.g. https://sso.example.com/realms/internal
    keycloak_audience: str | None = None  # expected `aud` claim (this backend's client id)
    # T6.2: opt-in client->server event reporting (skillify/common/telemetry.py). Off unless
    # explicitly configured — no network call, no data collected, by default.
    web_base_url: str | None = None  # e.g. http://localhost:8089 (skillify-web, T3.1)
    reporting_enabled: bool = False
    # M-D (docs/review-m2-m6.md): caps on the browser upload endpoint to bound memory use —
    # a raw upload larger than max_upload_bytes is rejected before being read into memory;
    # max_extracted_bytes/max_extracted_files bound the zip's *decompressed* size/entry count
    # (a zip bomb can have a tiny compressed size but a huge decompressed one).
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MiB raw .zip
    max_extracted_bytes: int = 100 * 1024 * 1024  # 100 MiB decompressed total
    max_extracted_files: int = 5000
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
    "SKILLIFY_INDEX_DB_URL": "index_db_url",
    "SKILLIFY_KEYCLOAK_REALM_URL": "keycloak_realm_url",
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
        index_db_url=data.get("index_db_url"),
        keycloak_realm_url=data.get("keycloak_realm_url"),
        keycloak_audience=data.get("keycloak_audience"),
        web_base_url=data.get("web_base_url"),
        reporting_enabled=bool(data.get("reporting_enabled", False)),
        max_upload_bytes=int(data.get("max_upload_bytes") or 20 * 1024 * 1024),
        max_extracted_bytes=int(data.get("max_extracted_bytes") or 100 * 1024 * 1024),
        max_extracted_files=int(data.get("max_extracted_files") or 5000),
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
    ):
        value = os.environ.get(env_var)
        if value:
            setattr(cfg, attr, int(value))

    reporting_env = os.environ.get("SKILLIFY_REPORTING_ENABLED")
    if reporting_env is not None:
        cfg.reporting_enabled = reporting_env.strip().lower() in ("1", "true", "yes", "on")

    return cfg
