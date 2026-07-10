"""Shared literal fixtures for validator/CLI tests (not collected by pytest)."""

VALID_SKILL_MD = """---
name: pivot-analysis
description: Build pivot tables from tabular data.
---

# Pivot Analysis

Do the thing.
"""

VALID_MANIFEST = """
manifestVersion: 1
namespace: excel
name: pivot-analysis
version: 0.1.0
description: Build pivot tables from tabular data.
author: Jane Doe
license: MIT
runtime: claude-agent-skill
targets: [claude]
"""
