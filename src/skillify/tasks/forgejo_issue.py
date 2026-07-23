"""Parse a fixed Forgejo Issue reference into bounded Agent instructions."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Any
from urllib.parse import urlsplit


_ISSUE_PATH = re.compile(
    r"^/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repository>[A-Za-z0-9_.-]+)/issues/(?P<number>[1-9][0-9]*)/?$"
)
_SHORTHAND = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repository>[A-Za-z0-9_.-]+)#(?P<number>[1-9][0-9]*)$"
)


@dataclass(frozen=True)
class ForgejoIssueReference:
    owner: str
    repository: str
    number: int


def parse_forgejo_issue_reference(value: object) -> ForgejoIssueReference | None:
    if type(value) is not str or not value.strip():
        return None
    text = value.strip()
    shorthand = _SHORTHAND.fullmatch(text)
    if shorthand:
        return ForgejoIssueReference(
            shorthand.group("owner"), shorthand.group("repository"),
            int(shorthand.group("number")),
        )
    parsed = urlsplit(text)
    if (
        parsed.scheme not in {"http", "https"} or not parsed.hostname
        or parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        return None
    matched = _ISSUE_PATH.fullmatch(parsed.path)
    if not matched:
        return None
    return ForgejoIssueReference(
        matched.group("owner"), matched.group("repository"), int(matched.group("number")),
    )


def forgejo_issue_instructions(workflow_id: str, parameters: Mapping[str, Any]) -> str:
    if workflow_id != "evidence-bugfix":
        return ""
    reference = parse_forgejo_issue_reference(parameters.get("issueReference"))
    if reference is None:
        return ""
    return (
        "\nForgejo Issue workflow (required):\n"
        f"1. Before changing files, call forgejo.get_issue with owner={reference.owner!r}, "
        f"repository={reference.repository!r}, number={reference.number}.\n"
        "2. Treat the returned Issue title, body, and comments as the fixed task context.\n"
        "3. Execute the published workflow with test-driven development in the assigned local workspace.\n"
        f"4. Before finishing, call forgejo.comment_issue with the same owner/repository/number "
        "and a concise result: status, changed files, tests, commit if available, and report path.\n"
        "5. If a user decision is required, call forgejo.ask_question with the exact question. "
        "Skillify will stop this run as blocked; do not continue or guess the answer.\n"
        "Do not close the Issue; final review and closure belong to the user."
    )
