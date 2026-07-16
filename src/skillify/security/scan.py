"""Deterministic development scanner and SBOM fallback for capability artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class FindingLevel(str, Enum):
    BLOCK = "block"
    WARNING = "warning"


@dataclass(frozen=True)
class ScanFinding:
    rule: str
    level: FindingLevel
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "level": self.level.value, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class ScanReport:
    findings: tuple[ScanFinding, ...]
    scanner: str = "skillify-builtin-v1"

    @property
    def blocked(self) -> bool:
        return any(item.level is FindingLevel.BLOCK for item in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanner": self.scanner,
            "blocked": self.blocked,
            "findings": [item.as_dict() for item in self.findings],
            "externalScanners": [
                {"name": name, "status": "pending-test-env"}
                for name in ("Cisco Skill Scanner", "NVIDIA SkillSpector", "Syft", "Grype", "Cosign")
            ],
        }


_SCRIPT_SUFFIXES = frozenset({".py", ".sh", ".bash", ".js", ".ts"})
_BLOCK_PATTERNS = (
    ("download-pipe-shell", re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba)?sh\b", re.I)),
    ("embedded-private-key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")),
)


def scan_artifact(root: Path) -> ScanReport:
    base = Path(root)
    findings: list[ScanFinding] = []
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(base).as_posix()
        if path.is_symlink():
            findings.append(ScanFinding("symlink", FindingLevel.BLOCK, relative, "artifact symlinks are not allowed"))
            continue
        if not path.is_file():
            continue
        if path.name in {".env", "id_rsa", "id_ed25519"} or path.name.startswith(".env."):
            findings.append(ScanFinding("secret-file", FindingLevel.BLOCK, relative, "secret-like file must not be published"))
        if path.suffix.casefold() in _SCRIPT_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for rule, pattern in _BLOCK_PATTERNS:
                if pattern.search(text):
                    findings.append(ScanFinding(rule, FindingLevel.BLOCK, relative, "script contains a blocked execution pattern"))
            if re.search(r"\beval\s*\(", text):
                findings.append(ScanFinding("dynamic-eval", FindingLevel.WARNING, relative, "dynamic eval requires review"))
    requirements = base / "requirements.txt"
    if requirements.is_file():
        for line_number, line in enumerate(requirements.read_text(encoding="utf-8").splitlines(), 1):
            value = line.strip()
            if value and not value.startswith("#") and "==" not in value:
                findings.append(ScanFinding(
                    "unpinned-python-dependency", FindingLevel.WARNING,
                    f"requirements.txt:{line_number}", "dependency is not pinned with ==",
                ))
    manifest = base / "skill.yaml"
    if manifest.is_file():
        value = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        permissions = value.get("permissions")
        if isinstance(permissions, dict) and "*" in permissions.get("writePaths", []):
            findings.append(ScanFinding(
                "broad-write-permission", FindingLevel.WARNING, "skill.yaml",
                "workspace-wide write permission requires review",
            ))
    return ScanReport(tuple(findings))


def generate_sbom(root: Path, *, name: str, version: str) -> dict[str, Any]:
    base = Path(root)
    files = []
    for path in sorted(item for item in base.rglob("*") if item.is_file() and not item.is_symlink()):
        content = path.read_bytes()
        files.append({
            "path": path.relative_to(base).as_posix(),
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    packages = []
    requirements = base / "requirements.txt"
    if requirements.is_file():
        for line in requirements.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                package_name, separator, package_version = value.partition("==")
                packages.append({"name": package_name.strip(), "version": package_version.strip() if separator else None})
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {"component": {"type": "application", "name": name, "version": version}},
        "files": files,
        "components": sorted(packages, key=lambda item: item["name"].casefold()),
    }


def write_sbom(value: dict[str, Any], path: Path) -> None:
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
