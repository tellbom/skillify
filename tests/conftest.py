"""Shared pytest fixtures.

`_isolate_agent_presence_markers` is autouse and safety-critical: `auto_select_targets`
(T1.4a) checks real marker directories like `~/.claude` to decide whether to auto-project
an installed skill into that agent's real skills dir. Without this fixture, any test that
installs a skill via the CLI (`skillctl install ...` with no `--target`) on a machine that
happens to have `~/.claude` (e.g. this very dev box, since we're running inside Claude Code)
would silently write into the developer's real `~/.claude/skills/`. Tests that specifically
want to exercise auto-selection re-patch `AGENT_PRESENCE_MARKERS` themselves.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_agent_presence_markers(monkeypatch):
    import skillify.install.agent_defaults as agent_defaults

    monkeypatch.setattr(agent_defaults, "AGENT_PRESENCE_MARKERS", {})
