"""Thin fixed-target REST adapter reference for legacy internal systems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests


class RestAdapterError(RuntimeError):
    pass


class CredentialProvider(Protocol):
    def token(self, credential_ref: str, scopes: frozenset[str]) -> str: ...


@dataclass(frozen=True)
class RestTool:
    name: str
    method: str
    path: str
    scopes: frozenset[str]
    response_fields: frozenset[str]
    write: bool = False

    def __post_init__(self) -> None:
        if (
            not self.name
            or self.method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}
            or not self.path.startswith("/")
            or "//" in self.path
            or ".." in self.path
        ):
            raise ValueError("REST tool must use a fixed name, method and relative path")
        if self.write != (self.method != "GET"):
            raise ValueError("REST read and write tools must be declared separately")


class RestAdapter:
    def __init__(
        self,
        base_url: str,
        *,
        allowed_target: tuple[str, int, str],
        credential_ref: str,
        approved_scopes: frozenset[str],
        credential_provider: CredentialProvider,
        tools: tuple[RestTool, ...],
        session: requests.Session | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        parsed = urlsplit(base_url)
        host, port, protocol = allowed_target
        actual_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if (
            parsed.scheme != protocol
            or parsed.hostname != host
            or actual_port != port
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("REST target is outside the fixed network allowlist")
        if not credential_ref or not tools:
            raise ValueError("REST adapter requires a credential reference and tools")
        self.base_url = base_url.rstrip("/")
        self.credential_ref = credential_ref
        self.approved_scopes = approved_scopes
        self.credential_provider = credential_provider
        self.tools = {tool.name: tool for tool in tools}
        if len(self.tools) != len(tools):
            raise ValueError("REST tool names must be unique")
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            tool = self.tools[name]
        except KeyError as exc:
            raise RestAdapterError("unknown REST tool") from exc
        if not tool.scopes <= self.approved_scopes:
            raise PermissionError("REST tool scopes are not approved")
        token = self.credential_provider.token(self.credential_ref, tool.scopes)
        try:
            response = self.session.request(
                tool.method,
                self.base_url + tool.path,
                params=arguments if not tool.write else None,
                json=arguments if tool.write else None,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            value = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RestAdapterError("internal REST request failed") from exc
        if not isinstance(value, dict):
            raise RestAdapterError("internal REST response must be an object")
        return {key: value[key] for key in tool.response_fields if key in value}
