from __future__ import annotations

import os
from pathlib import Path

import pytest

from skillify.mcp.forgejo.connector import load_forgejo_environment
from skillify.tasks.forgejo_issue import (
    forgejo_issue_instructions,
    parse_forgejo_issue_reference,
)


def test_parses_forgejo_issue_url_and_shorthand() -> None:
    url = parse_forgejo_issue_reference(
        "http://192.168.124.2:3000/skillify/example/issues/42"
    )
    shorthand = parse_forgejo_issue_reference("skillify/example#42")

    assert url == shorthand
    assert url is not None
    assert (url.owner, url.repository, url.number) == ("skillify", "example", 42)


@pytest.mark.parametrize("value", [
    "BUG-42",
    "http://user:secret@forgejo/skillify/example/issues/42",
    "http://forgejo/skillify/example/pulls/42",
    "http://forgejo/skillify/example/issues/0",
    "http://forgejo/skillify/example/issues/42?token=secret",
])
def test_rejects_non_issue_or_credential_bearing_reference(value: str) -> None:
    assert parse_forgejo_issue_reference(value) is None


def test_bugfix_prompt_requires_issue_read_comment_and_user_closure() -> None:
    instructions = forgejo_issue_instructions(
        "evidence-bugfix",
        {"issueReference": "http://forgejo:3000/skillify/example/issues/7"},
    )

    assert "forgejo.get_issue" in instructions
    assert "forgejo.comment_issue" in instructions
    assert "number=7" in instructions
    assert "Do not close" in instructions
    assert forgejo_issue_instructions("feature-development", {}) == ""


def test_loads_forgejo_credentials_from_owned_0600_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    path = tmp_path / "forgejo.env"
    path.write_text(
        "SKILLIFY_MCP_FORGEJO_URL=http://forgejo:3000\n"
        "SKILLIFY_MCP_FORGEJO_TOKEN=test-token\n"
        "SKILLIFY_MCP_FORGEJO_SCOPES=repo:read,issue:write\n"
        "SKILLIFY_MCP_FORGEJO_WRITE_TOOLS=forgejo.comment_issue\n",
        encoding="utf-8",
    )
    if os.name == "posix":
        path.chmod(0o600)
    monkeypatch.setenv("SKILLIFY_MCP_FORGEJO_CREDENTIALS_FILE", str(path))
    for key in (
        "SKILLIFY_MCP_FORGEJO_URL", "SKILLIFY_MCP_FORGEJO_TOKEN",
        "SKILLIFY_MCP_FORGEJO_SCOPES", "SKILLIFY_MCP_FORGEJO_WRITE_TOOLS",
    ):
        monkeypatch.delenv(key, raising=False)

    environment = load_forgejo_environment()

    assert environment["SKILLIFY_MCP_FORGEJO_URL"] == "http://forgejo:3000"
    assert environment["SKILLIFY_MCP_FORGEJO_TOKEN"] == "test-token"


def test_rejects_unknown_forgejo_credentials_file_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    path = tmp_path / "forgejo.env"
    path.write_text(
        "SKILLIFY_MCP_FORGEJO_URL=http://forgejo:3000\n"
        "SKILLIFY_MCP_FORGEJO_TOKEN=test-token\n"
        "UNRELATED_SECRET=value\n",
        encoding="utf-8",
    )
    if os.name == "posix":
        path.chmod(0o600)
    monkeypatch.setenv("SKILLIFY_MCP_FORGEJO_CREDENTIALS_FILE", str(path))

    with pytest.raises(ValueError, match="unsupported entry"):
        load_forgejo_environment()
