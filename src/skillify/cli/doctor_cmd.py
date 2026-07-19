"""`skillctl doctor` — local environment self-check (T1.1b)."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests
from rich.console import Console

from skillify.common.config import (
    AgentLocalConfig, AgentPaths, SkillifyConfig,
    load_agent_local_config, load_agent_paths, load_config,
)
from skillify.agent.codegraph import CodeGraphError, codegraph_version
from skillify.install.agent_defaults import RESERVED_UNIMPLEMENTED_AGENTS, ensure_default_agent_configs
from skillify.install.opencode_distribution import (
    check_opencode_distribution,
    detect_opencode_platform as _detect_opencode_platform,
    opencode_version as _opencode_version,
    resolve_distribution_paths,
)
from skillify.install.projector import agent_skills_root, load_agent_rule
from skillify.credentials.store import EncryptedFileSecretStore
from skillify.agent.shogun.distribution import (
    ShogunDistributionError, check_host_dependencies, load_manifest, verify_artifact,
)

REQUIRED_BINARIES = ["uv"]

# "project" is a per-project convention (cwd-relative `.skills`), not a machine-wide
# agent install, so doctor doesn't check for its presence the way it does claude/opencode.
AGENTS_EXCLUDED_FROM_DOCTOR = RESERVED_UNIMPLEMENTED_AGENTS | {"project"}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    hint: str = ""
    required: bool = True


def _check_python() -> CheckResult:
    ok = sys.version_info >= (3, 10)
    detail = f"Python {sys.version.split()[0]} at {sys.executable}"
    return CheckResult("python", ok, detail, "" if ok else "install Python >= 3.10")


def _check_binary(name: str) -> CheckResult:
    path = shutil.which(name)
    if path:
        return CheckResult(name, True, path)
    return CheckResult(name, False, "not found on PATH", f"install `{name}` and ensure it's on PATH")


def _check_codegraph() -> CheckResult:
    executable = shutil.which("codegraph")
    if executable is None:
        return CheckResult(
            "codegraph", False, "not found on PATH",
            "install the approved offline CodeGraph bundle; native grep/read remains available",
            required=False,
        )
    try:
        version = codegraph_version(executable)
    except CodeGraphError as exc:
        return CheckResult("codegraph", False, str(exc), "use the approved CodeGraph version", required=False)
    return CheckResult("codegraph", True, f"CodeGraph {version} at {executable}", required=False)


def _check_skills_dir_writable(cfg: SkillifyConfig) -> CheckResult:
    try:
        cfg.ensure_dirs()
        probe = cfg.skills_dir / ".doctor-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return CheckResult("skills-dir-writable", True, str(cfg.skills_dir))
    except OSError as exc:
        return CheckResult(
            "skills-dir-writable",
            False,
            f"{cfg.skills_dir}: {exc}",
            f"ensure {cfg.skills_dir} exists and is writable (or set SKILLIFY_HOME)",
        )


def _check_agent_target_dir(agent: str, path: Path) -> CheckResult:
    ok = path.is_dir()
    return CheckResult(
        f"agent-dir:{agent}",
        ok,
        str(path),
        "" if ok else f"{path} does not exist — install/configure {agent} first, "
        f"or this machine isn't meant to target {agent}",
    )


def _check_configured_agent_dirs(cfg: SkillifyConfig) -> list[CheckResult]:
    """Dynamically check every agent declared in ~/.skillify/agents/*.yaml (F1 fix):
    doctor no longer hardcodes which agents exist — adding a new agent adapter (a new
    agents/<agent>.yaml) makes it show up here automatically, and reserved/unimplemented
    agents (codex/aider) or the cwd-relative `project` target are never checked."""
    ensure_default_agent_configs(cfg.agents_dir)
    results = []
    for path in sorted(cfg.agents_dir.glob("*.yaml")):
        agent = path.stem
        if agent in AGENTS_EXCLUDED_FROM_DOCTOR:
            continue
        rule = load_agent_rule(cfg, agent)
        results.append(_check_agent_target_dir(agent, agent_skills_root(rule)))
    return results


def _check_forgejo_reachable(cfg: SkillifyConfig) -> CheckResult:
    if not cfg.forgejo_url:
        return CheckResult(
            "forgejo-reachable", False, "forgejo_url not configured",
            "set forgejo_url in ~/.skillify/config.yaml or SKILLIFY_FORGEJO_URL",
        )
    try:
        resp = requests.get(f"{cfg.forgejo_url.rstrip('/')}/api/v1/version", timeout=3)
        ok = resp.status_code == 200
        return CheckResult("forgejo-reachable", ok, f"HTTP {resp.status_code} from {cfg.forgejo_url}")
    except requests.RequestException as exc:
        return CheckResult(
            "forgejo-reachable", False, f"{cfg.forgejo_url}: {exc}",
            "check the URL and that Forgejo (infra/docker-compose.yml) is running",
        )


def _check_forgejo_token(cfg: SkillifyConfig) -> CheckResult:
    if not cfg.forgejo_token:
        return CheckResult(
            "forgejo-token", False, "forgejo_token not configured",
            "set forgejo_token in ~/.skillify/config.yaml or SKILLIFY_FORGEJO_TOKEN",
        )
    if not cfg.forgejo_url:
        return CheckResult("forgejo-token", False, "forgejo_url not configured", "set forgejo_url first")
    try:
        resp = requests.get(
            f"{cfg.forgejo_url.rstrip('/')}/api/v1/user",
            headers={"Authorization": f"token {cfg.forgejo_token}"},
            timeout=3,
        )
        ok = resp.status_code == 200
        detail = f"HTTP {resp.status_code}" + ("" if ok else " (token rejected)")
        return CheckResult("forgejo-token", ok, detail, "" if ok else "regenerate the token in Forgejo settings")
    except requests.RequestException as exc:
        return CheckResult("forgejo-token", False, str(exc), "check forgejo_url / network")


def _check_devpi_reachable(cfg: SkillifyConfig) -> CheckResult:
    if not cfg.devpi_index_url:
        return CheckResult(
            "devpi-reachable", False, "devpi_index_url not configured",
            "set devpi_index_url in ~/.skillify/config.yaml or SKILLIFY_DEVPI_INDEX_URL",
            required=False,
        )
    try:
        resp = requests.get(cfg.devpi_index_url, timeout=3)
        ok = resp.status_code < 500
        return CheckResult(
            "devpi-reachable", ok, f"HTTP {resp.status_code} from {cfg.devpi_index_url}",
            required=False,
        )
    except requests.RequestException as exc:
        return CheckResult(
            "devpi-reachable", False, f"{cfg.devpi_index_url}: {exc}",
            "check the external devpi URL or the standalone infra/devpi stack",
            required=False,
        )


def _check_credentials(cfg: SkillifyConfig) -> CheckResult:
    store = EncryptedFileSecretStore(
        cfg.home / "credentials.enc", cfg.home / "keys" / "credentials.key"
    )
    try:
        count = len(store.references())
    except ValueError:
        return CheckResult("credentials", False, "local credential metadata is invalid", required=False)
    return CheckResult(
        "credentials", count > 0, f"{count} local credential reference(s)",
        "add credentials only for tasks that require them", required=False,
    )


def _check_shogun(config: AgentLocalConfig) -> CheckResult:
    configured = (config.shogun_manifest_path, config.shogun_artifact_path)
    if not all(configured):
        return CheckResult(
            "shogun-team-runtime", False, "offline Shogun bundle is not configured",
            "single/delegated remain available; configure the approved bundle for team mode",
            required=False,
        )
    try:
        manifest = load_manifest(Path(config.shogun_manifest_path or ""))
        verify_artifact(Path(config.shogun_artifact_path or ""), manifest)
        status = check_host_dependencies(config.provider)
    except (OSError, ValueError, ShogunDistributionError) as exc:
        return CheckResult("shogun-team-runtime", False, str(exc), required=False)
    return CheckResult(
        "shogun-team-runtime", status.available, status.detail,
        "install missing host dependencies for team mode", required=False,
    )
def _opencode_distribution_paths(config: AgentLocalConfig) -> tuple[Path, Path] | None:
    return resolve_distribution_paths(
        config.opencode_manifest_path, config.opencode_artifact_root,
    )


def _check_opencode_distribution(*, manifest_path: Path, artifact_root: Path,
                                 platform_detector: Callable[[], tuple[str, str, str, str]],
                                 version_runner: Callable[[list[str]], str]) -> list[CheckResult]:
    return [
        CheckResult(
            check.name, check.ok, check.detail, check.hint,
            check.classification == "required",
        )
        for check in check_opencode_distribution(
            manifest_path=manifest_path,
            artifact_root=artifact_root,
            platform_detector=platform_detector,
            version_runner=version_runner,
        )
    ]


def run_doctor(
    *,
    console: Console,
    config: SkillifyConfig | None = None,
    agent_paths: AgentPaths | None = None,
    agent_config: AgentLocalConfig | None = None,
    platform_detector: Callable[[], tuple[str, str, str, str]] = _detect_opencode_platform,
    version_runner: Callable[[list[str]], str] = _opencode_version,
) -> bool:
    config_was_injected = config is not None
    cfg = config or load_config()

    checks: list[CheckResult] = [_check_python()]
    checks += [_check_binary(b) for b in REQUIRED_BINARIES]
    checks.append(_check_codegraph())
    try:
        local_config = agent_config
        if local_config is None:
            resolved_paths = agent_paths
            if resolved_paths is None:
                # Injected SkillifyConfig tests remain under cfg.home and never
                # fall through to the real XDG/user home. Normal CLI execution
                # still resolves the normal endpoint-agent XDG paths.
                resolved_paths = (
                    load_agent_paths({}, home=cfg.home)
                    if config_was_injected else load_agent_paths()
                )
            local_config = load_agent_local_config(resolved_paths)
        distribution_paths = _opencode_distribution_paths(local_config)
        if distribution_paths is not None:
            manifest_path, artifact_root = distribution_paths
            checks += _check_opencode_distribution(
                manifest_path=manifest_path,
                artifact_root=artifact_root,
                platform_detector=platform_detector,
                version_runner=version_runner,
            )
    except (OSError, TypeError, ValueError) as exc:
        checks.append(CheckResult(
            "opencode-manifest", False, str(exc), "configure the approved offline OpenCode bundle",
        ))
    checks.append(_check_skills_dir_writable(cfg))
    checks.append(_check_forgejo_reachable(cfg))
    checks.append(_check_forgejo_token(cfg))
    checks.append(_check_devpi_reachable(cfg))
    checks.append(_check_credentials(cfg))
    checks.append(_check_shogun(local_config))
    checks += _check_configured_agent_dirs(cfg)

    all_ok = True
    for check in checks:
        mark = ("[green]OK[/green]" if check.ok else
                "[red]FAIL[/red]" if check.required else "[yellow]WARN[/yellow]")
        console.print(f"{mark} {check.name}: {check.detail}")
        if not check.ok and check.required:
            all_ok = False
        if not check.ok and check.hint:
            console.print(f"     [yellow]-> {check.hint}[/yellow]")

    console.print()
    if all_ok:
        console.print("[green]doctor: all required checks passed[/green]")
    else:
        console.print("[red]doctor: one or more checks failed[/red]")
    return all_ok
