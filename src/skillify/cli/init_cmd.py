"""`skillctl init` — scaffold a new skill (T1.1a)."""

from __future__ import annotations

import re
from pathlib import Path

import typer
import yaml
from rich.console import Console

_IDENT_SEGMENT_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

_TEMPLATES = {"prompt", "python"}

_SKILL_MD_TEMPLATE = """---
name: {name}
description: TODO — one sentence describing what this skill does and when to use it.
---

# {title}

TODO: describe what this skill does, how the agent should use it, and any inputs/outputs.
"""

_README_TEMPLATE = """# {namespace}/{name}

TODO: human-facing docs. `SKILL.md` is what the agent reads; this is what a person reads
before deciding whether to install it.

## Install

```
skillctl install {namespace}/{name}
```
"""

_EXAMPLE_TEMPLATE = """# Example usage

TODO: a worked example an author/reviewer can follow to confirm the skill behaves as intended.
"""


def _manifest_dict(namespace: str, name: str, template: str) -> dict:
    manifest = {
        "manifestVersion": 1,
        "namespace": namespace,
        "name": name,
        "version": "0.1.0",
        "description": "TODO — one sentence, <=500 chars, matches SKILL.md frontmatter intent.",
        "author": "TODO",
        "license": "MIT",
        "runtime": "claude-agent-skill",
        "targets": ["claude"],
        "tags": [],
    }
    if template == "python":
        manifest["dependencies"] = {"python": ["requests>=2.31"], "system": [], "skills": []}
    return manifest


def run_init(
    *, identifier: str, template: str, dest: Path, console: Console, err_console: Console
) -> None:
    if template not in _TEMPLATES:
        err_console.print(f"[red]--template must be one of {sorted(_TEMPLATES)}, got {template!r}[/red]")
        raise typer.Exit(code=2)

    if "/" not in identifier:
        err_console.print(f"[red]identifier must be '<namespace>/<name>', got {identifier!r}[/red]")
        raise typer.Exit(code=2)
    namespace, _, name = identifier.partition("/")
    for label, segment in (("namespace", namespace), ("name", name)):
        if not _IDENT_SEGMENT_RE.match(segment):
            err_console.print(
                f"[red]{label} {segment!r} must match {_IDENT_SEGMENT_RE.pattern}[/red]"
            )
            raise typer.Exit(code=2)

    skill_dir = dest / namespace / name
    if skill_dir.exists():
        err_console.print(f"[red]{skill_dir} already exists[/red]")
        raise typer.Exit(code=1)

    skill_dir.mkdir(parents=True)
    (skill_dir / "examples").mkdir()

    manifest = _manifest_dict(namespace, name, template)
    (skill_dir / "skill.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (skill_dir / "SKILL.md").write_text(
        _SKILL_MD_TEMPLATE.format(name=name, title=name.replace("-", " ").title()),
        encoding="utf-8",
    )
    (skill_dir / "README.md").write_text(
        _README_TEMPLATE.format(namespace=namespace, name=name), encoding="utf-8"
    )
    (skill_dir / "examples" / "example.md").write_text(_EXAMPLE_TEMPLATE, encoding="utf-8")

    if template == "python":
        (skill_dir / "scripts").mkdir()
        (skill_dir / "scripts" / "run.py").write_text(
            '"""TODO: entrypoint script for this skill."""\n\n'
            "import requests  # example dependency declared in skill.yaml\n\n\n"
            "def main() -> None:\n"
            "    raise NotImplementedError\n\n\n"
            'if __name__ == "__main__":\n'
            "    main()\n",
            encoding="utf-8",
        )
        (skill_dir / "requirements.txt").write_text("requests>=2.31\n", encoding="utf-8")

    # Self-verify: a freshly generated skill must pass the validator it will be
    # checked against at publish time. If this ever fails it's this generator's bug.
    from skillify.validator import validate_skill_dir

    result = validate_skill_dir(skill_dir, namespace_aware=True)
    if not result.ok:
        err_console.print(
            "[red]internal error: generated skill failed validation — this is a bug in "
            "`skillctl init`, not in your skill:[/red]"
        )
        for issue in result.issues:
            err_console.print(f"  [red]•[/red] {issue.path}: {issue.message}")
        raise typer.Exit(code=3)

    console.print(f"[green]Created[/green] {skill_dir} (template={template})")
    console.print("Next: fill in the TODOs in SKILL.md / skill.yaml / README.md, then:")
    console.print(f"  skillctl validate {skill_dir}")
    console.print(f"  skillctl publish {skill_dir}")
