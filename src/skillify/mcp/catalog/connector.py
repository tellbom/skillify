"""Search and load community Skills while an endpoint Agent is running."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any, Protocol

import requests
from mcp.server.fastmcp import FastMCP

from skillify.common.config import load_agent_paths, load_config
from skillify.install.dependencies import install_with_dependencies
from skillify.install.projector import ProjectionError, project_to_targets


class CatalogBackend(Protocol):
    def search(self, query: str, limit: int) -> dict[str, Any]: ...
    def detail(self, namespace: str, name: str, version: str | None) -> dict[str, Any]: ...


class SkillLoader(Protocol):
    def load(self, detail: dict[str, Any]) -> dict[str, Any]: ...


class CatalogHttpBackend:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _get(self, path: str, params: dict[str, object]) -> dict[str, Any]:
        response = requests.get(
            self.base_url + path,
            params=params,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=15,
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Skillify catalog response must be an object")
        return value

    def search(self, query: str, limit: int) -> dict[str, Any]:
        return self._get("/api/endpoint/catalog/skills", {"q": query, "limit": limit})

    def detail(self, namespace: str, name: str, version: str | None) -> dict[str, Any]:
        params: dict[str, object] = {}
        if version:
            params["version"] = version
        return self._get(f"/api/endpoint/catalog/skills/{namespace}/{name}", params)


class EndpointSkillLoader:
    """Cache the instructions, then best-effort install/project the verified release."""

    def __init__(self, target: str | None) -> None:
        self.target = target

    def load(self, detail: dict[str, Any]) -> dict[str, Any]:
        namespace = str(detail.get("namespace") or "")
        name = str(detail.get("name") or "")
        version = str(detail.get("version") or "")
        skill_md = detail.get("skillMd")
        if not namespace or not name or not version or not isinstance(skill_md, str) or not skill_md.strip():
            raise ValueError("published Skill detail must include namespace, name, version and SKILL.md")

        cache_dir = load_agent_paths().cache_dir / "catalog" / f"{namespace}__{name}@{version}"
        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        cache_file = cache_dir / "SKILL.md"
        cache_file.write_text(skill_md, encoding="utf-8")
        cache_file.chmod(0o600)

        install_status = "context-cached"
        projection_status = "not-requested"
        try:
            cfg = load_config()
            lock = install_with_dependencies(f"{namespace}/{name}@{version}", cfg=cfg)
            install_status = "installed"
            if self.target:
                try:
                    project_to_targets(cfg, lock, [self.target])
                    projection_status = "projected"
                except ProjectionError as exc:
                    projection_status = f"conflict: {exc}"
        except Exception as exc:
            # The current task can still use the authenticated SKILL.md response. A missing
            # artifact credential or native-directory conflict must not turn into a user prompt.
            install_status = f"context-only: {exc}"

        return {
            "coordinate": f"{namespace}/{name}@{version}",
            "description": detail.get("description"),
            "skillMd": skill_md,
            "cachePath": str(cache_file),
            "installStatus": install_status,
            "projectionStatus": projection_status,
        }


class RuntimeCatalogConnector:
    def __init__(self, backend: CatalogBackend, loader: SkillLoader) -> None:
        self.backend = backend
        self.loader = loader

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Search the Skillify community for instructions relevant to the current task."""
        query = query.strip()
        if not query:
            raise ValueError("catalog query must not be empty")
        if limit < 1 or limit > 20:
            raise ValueError("catalog limit must be between 1 and 20")
        return self.backend.search(query, limit)

    def load(self, namespace: str, name: str, version: str | None = None) -> dict[str, Any]:
        """Load a selected Skill into this task and cache/install it on the endpoint."""
        return self.loader.load(self.backend.detail(namespace, name, version))


def create_mcp_server(connector: RuntimeCatalogConnector) -> FastMCP:
    server = FastMCP("skillify-catalog")
    server.tool(name="skills.search")(connector.search)
    server.tool(name="skills.load")(connector.load)
    return server


def _read_token(path: Path) -> str:
    candidate = path.resolve(strict=True)
    info = candidate.stat()
    if not candidate.is_file():
        raise ValueError("catalog endpoint token path must be a file")
    if os.name == "posix" and (
        stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid()
    ):
        raise ValueError("catalog endpoint token file must be owned by the current user with mode 0600")
    value = candidate.read_text(encoding="utf-8").strip()
    prefix = "SKILLIFY_ENDPOINT_TOKEN="
    return value[len(prefix):].strip() if value.startswith(prefix) else value


def create_configured_server() -> FastMCP:
    base_url = os.environ.get("SKILLIFY_MCP_CATALOG_URL")
    token_file = os.environ.get("SKILLIFY_MCP_CATALOG_TOKEN_FILE")
    if not base_url or not token_file:
        raise ValueError("catalog URL and endpoint token file are required")
    target = os.environ.get("SKILLIFY_MCP_CATALOG_TARGET") or None
    return create_mcp_server(
        RuntimeCatalogConnector(
            CatalogHttpBackend(base_url, _read_token(Path(token_file))),
            EndpointSkillLoader(target),
        )
    )
