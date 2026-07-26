from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "scripts" / "gitnexus" / "import_source.py"
SCRIPT_PATH = ROOT / "scripts" / "deployment" / "gitnexus-docker.sh"
GATEWAY_CONFIG_PATH = ROOT / "infra" / "gitnexus-standalone" / "nginx.conf"
SPEC = importlib.util.spec_from_file_location("gitnexus_import_source", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)


def test_standalone_lifecycle_uses_docker_cli_without_compose() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    executable_lines = [
        line.strip()
        for line in script.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "docker run -d" in script
    assert "docker network create --internal" in script
    assert ":/workspace:ro" in script
    assert "--read-only" in script
    assert 'SERVER_MEMORY="$(config_value GITNEXUS_SERVER_MEMORY 0)"' in script
    assert '[[ "$memory" == "0" ]] || LIMIT_ARGS+=' in script
    assert '[[ ! -L "$repository_path" ]]' in script
    assert '[[ ! -L "$index_path" ]]' in script
    assert 'SKIP_PULL="$(config_value GITNEXUS_SKIP_PULL 1)"' in script
    assert 'BACKEND_URL="$(config_value GITNEXUS_BACKEND_URL "$PUBLIC_URL")"' in script
    assert all(
        "docker compose" not in line and "docker-compose" not in line
        for line in executable_lines
    )
    gateway_config = GATEWAY_CONFIG_PATH.read_text(encoding="utf-8")
    assert "client_max_body_size 0;" in gateway_config
    assert "proxy_request_buffering off;" in gateway_config
    assert "sub_filter 'https://fonts.googleapis.com' 'about:blank'" in gateway_config
    assert "sub_filter 'https://fonts.gstatic.com' 'about:blank'" in gateway_config


def test_deploy_mvp_renders_hardened_docker_cli_commands(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "${1:-} ${2:-}" in
  "info ") exit 0 ;;
  "image pull"|"image inspect") exit 0 ;;
  "network inspect"|"volume inspect") exit 1 ;;
  "network create"|"volume create") exit 0 ;;
  "run -d")
    previous=""
    for argument in "$@"; do
      if [[ "$previous" == "--name" ]]; then touch "$FAKE_DOCKER_STATE/$argument"; break; fi
      previous="$argument"
    done
    exit 0
    ;;
  "create --name")
    previous=""
    for argument in "$@"; do
      if [[ "$previous" == "--name" ]]; then touch "$FAKE_DOCKER_STATE/$argument"; break; fi
      previous="$argument"
    done
    exit 0
    ;;
  "container start"|"network connect") exit 0 ;;
  "container inspect")
    name="${!#}"
    [[ -f "$FAKE_DOCKER_STATE/$name" ]] || exit 1
    case "$*" in
      *State.Running*) printf 'true\\n' ;;
      *State.Health*) printf 'healthy\\n' ;;
      *State.Status*) printf 'running\\n' ;;
    esac
    exit 0
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    log = tmp_path / "docker.log"
    state = tmp_path / "docker-state"
    state.mkdir()
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(log),
        "FAKE_DOCKER_STATE": str(state),
        "GITNEXUS_STATE_ROOT": str(tmp_path / "gitnexus"),
    }

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "deploy"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    commands = log.read_text(encoding="utf-8")
    assert "network create --internal skillify-gitnexus-standalone" in commands
    assert "skillify/gitnexus:1.6.9-unlimited" in commands
    assert "ghcr.io/abhigyanpatwari/gitnexus-web:1.6.9" in commands
    assert "nginx:1.27.5-alpine" in commands
    assert (
        "--read-only --cap-drop ALL --security-opt no-new-privileges:true" in commands
    )
    assert f"{tmp_path}/gitnexus/sources:/workspace:ro" in commands
    assert (
        "network connect skillify-gitnexus-standalone skillify-gitnexus-gateway"
        in commands
    )
    assert "127.0.0.1:4747:4747" in commands
    assert "127.0.0.1:4173:8080" in commands
    assert "image pull" not in commands
    assert "--memory" not in commands
    assert "--pids-limit" not in commands


def test_env_file_configures_browser_visible_backend_without_execution(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
case "${1:-} ${2:-}" in
  "info ") exit 0 ;;
  "container inspect") exit 1 ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    env_file = tmp_path / ".env"
    marker = tmp_path / "must-not-exist"
    env_file.write_text(
        "\n".join(
            [
                "GITNEXUS_PUBLIC_URL=https://gitnexus.internal",
                "GITNEXUS_BACKEND_URL=https://gitnexus.internal",
                f"GITNEXUS_ALLOWED_GIT_HOSTS=$(touch {marker})",
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "status"],
        cwd=ROOT,
        env={
            **os.environ,
            "GITNEXUS_ENV_FILE": str(env_file),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert not marker.exists()
    assert result.returncode == 0, result.stderr
    assert "backend=https://gitnexus.internal" in result.stdout


def test_zip_import_is_isolated_and_rejects_overwrite(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as value:
        value.writestr("src/main.py", "print('ok')\n")

    target = IMPORTER.import_zip(tmp_path / "sources", "project-a", archive)

    assert (target / "src" / "main.py").read_text(encoding="utf-8") == "print('ok')\n"
    with pytest.raises(IMPORTER.ImportFailure, match="already exists"):
        IMPORTER.import_zip(tmp_path / "sources", "project-a", archive)


@pytest.mark.parametrize("name", ["../escape", "/absolute", r"..\\escape"])
def test_zip_import_rejects_path_escape(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as value:
        value.writestr(name, "unsafe")

    with pytest.raises(IMPORTER.ImportFailure, match="escapes"):
        IMPORTER.import_zip(tmp_path / "sources", "project-a", archive)


def test_zip_import_rejects_symlink(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as value:
        value.writestr(link, "../outside")

    with pytest.raises(IMPORTER.ImportFailure, match="symlinks"):
        IMPORTER.import_zip(tmp_path / "sources", "project-a", archive)


@pytest.mark.parametrize("name", [".git/config", ".gitnexus/meta.json"])
def test_zip_import_rejects_repository_metadata(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "metadata.zip"
    with zipfile.ZipFile(archive, "w") as value:
        value.writestr(name, "untrusted")

    with pytest.raises(IMPORTER.ImportFailure, match="reserved repository metadata"):
        IMPORTER.import_zip(tmp_path / "sources", "project-a", archive)


def test_git_url_requires_exact_host_and_no_credentials() -> None:
    allowed = frozenset({"forgejo.internal"})

    assert (
        IMPORTER.validated_git_url(
            "https://forgejo.internal/team/project.git",
            allowed,
        )
        == "https://forgejo.internal/team/project.git"
    )
    with pytest.raises(IMPORTER.ImportFailure, match="not approved"):
        IMPORTER.validated_git_url("https://evil.example/project.git", allowed)
    with pytest.raises(IMPORTER.ImportFailure, match="credentials"):
        IMPORTER.validated_git_url(
            "https://token@forgejo.internal/team/project.git",
            allowed,
        )
    with pytest.raises(IMPORTER.ImportFailure, match="query parameters"):
        IMPORTER.validated_git_url(
            "https://forgejo.internal/team/project.git?token=secret",
            allowed,
        )
    with pytest.raises(IMPORTER.ImportFailure, match="http or https"):
        IMPORTER.validated_git_url(
            "ssh://git@forgejo.internal/team/project.git",
            allowed,
        )


def test_git_url_allowlist_is_optional_for_controlled_intranet() -> None:
    url = "http://forgejo.internal/team/project.git"

    assert IMPORTER.validated_git_url(url, None) == url
    assert IMPORTER._allowed_hosts("") is None
    assert IMPORTER._allowed_hosts("*") is None
