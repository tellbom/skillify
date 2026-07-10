"""Sanity checks for infra/docker-compose.yml (T0.3) that don't require Docker.

Actually starting the stack (Forgejo/Postgres/devpi) cannot be verified in this sandbox —
no `docker` binary is available (see infra/README.md's "Known gap" section). This test only
catches the class of error a syntax/shape check can catch: malformed YAML, missing services,
undeclared env vars referenced in compose but absent from .env.example.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "infra" / "docker-compose.yml"
ENV_EXAMPLE_PATH = REPO_ROOT / "infra" / ".env.example"


def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_compose_is_valid_yaml_with_expected_services() -> None:
    compose = _load_compose()
    assert set(compose["services"].keys()) == {"db", "forgejo", "devpi", "webhook"}


def test_compose_declares_named_volumes_for_persistence() -> None:
    compose = _load_compose()
    assert set(compose["volumes"].keys()) == {"forgejo-db", "forgejo-data", "devpi-data"}


def test_forgejo_depends_on_healthy_db() -> None:
    compose = _load_compose()
    forgejo = compose["services"]["forgejo"]
    assert forgejo["depends_on"]["db"]["condition"] == "service_healthy"


def test_webhook_service_builds_from_repo_root_dockerfile() -> None:
    compose = _load_compose()
    webhook = compose["services"]["webhook"]
    assert webhook["build"]["dockerfile"] == "Dockerfile"
    assert (REPO_ROOT / "Dockerfile").is_file()


def test_env_vars_referenced_in_compose_have_defaults_or_are_in_env_example() -> None:
    compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
    env_example_text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    declared_vars = set(re.findall(r"^([A-Z_][A-Z0-9_]*)=", env_example_text, re.MULTILINE))

    # ${VAR:-default} and ${VAR:?required-message} are both self-documenting even if not in
    # .env.example (the latter is intentional for secrets — no committed default); a bare
    # ${VAR} with neither modifier is the only shape that needs a declared default.
    referenced = re.findall(r"\$\{([A-Z_][A-Z0-9_]*)(:[-?][^}]*)?\}", compose_text)
    bare_vars = {name for name, modifier in referenced if not modifier}
    missing = bare_vars - declared_vars
    assert not missing, f"compose references {missing} with no default and no .env.example entry"
