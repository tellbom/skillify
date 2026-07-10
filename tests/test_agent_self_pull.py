"""Tests for T6.1 — the agent self-pull prompt (fetch+verify+install recipe)."""

from __future__ import annotations

from skillify.common.config import SkillifyConfig
from skillify.web.service import agent_prompt


def test_agent_prompt_without_web_base_url_uses_placeholder() -> None:
    prompt = agent_prompt("excel", "pivot-analysis")
    assert "skillctl install excel/pivot-analysis" in prompt
    assert "<SKILLIFY_WEB_BASE_URL>" in prompt
    assert "tarballUrl" in prompt
    assert "sha256" in prompt


def test_agent_prompt_with_web_base_url_is_concrete() -> None:
    cfg = SkillifyConfig(web_base_url="http://skillify.internal:8089")
    prompt = agent_prompt("excel", "pivot-analysis", cfg)
    assert "http://skillify.internal:8089/api/skills/excel/pivot-analysis" in prompt
    assert "checksumUrl" in prompt
    assert "verifying the checksum" in prompt
