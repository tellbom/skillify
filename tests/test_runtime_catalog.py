from __future__ import annotations

from dataclasses import dataclass

import pytest

from skillify.mcp.catalog.connector import RuntimeCatalogConnector


class Backend:
    def search(self, query: str, limit: int) -> dict:
        return {"items": [{"namespace": "community", "name": query}], "total": 1, "limit": limit}

    def detail(self, namespace: str, name: str, version: str | None) -> dict:
        return {
            "namespace": namespace, "name": name, "version": version or "1.0.0",
            "description": "TDD guidance", "skillMd": "# Test-driven development",
        }


@dataclass
class Loader:
    loaded: dict | None = None

    def load(self, detail: dict) -> dict:
        self.loaded = detail
        return {"coordinate": f"{detail['namespace']}/{detail['name']}@{detail['version']}",
                "skillMd": detail["skillMd"]}


def test_runtime_catalog_searches_then_loads_selected_skill() -> None:
    loader = Loader()
    connector = RuntimeCatalogConnector(Backend(), loader)

    result = connector.search("systematic-debugging", limit=3)
    loaded = connector.load("community", "systematic-debugging")

    assert result["items"][0]["name"] == "systematic-debugging"
    assert loaded["coordinate"] == "community/systematic-debugging@1.0.0"
    assert loader.loaded is not None and loader.loaded["skillMd"].startswith("# Test-driven")


def test_runtime_catalog_rejects_empty_search_without_user_prompt() -> None:
    connector = RuntimeCatalogConnector(Backend(), Loader())

    with pytest.raises(ValueError, match="must not be empty"):
        connector.search(" ")
