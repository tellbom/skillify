from __future__ import annotations

import hashlib
import json
from pathlib import Path


MANIFEST = Path("infra/offline/mcp-sdk-manifest.json")


def test_mcp_sdk_manifest_pins_stable_v1_wheel() -> None:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert value == {
        "schemaVersion": 1,
        "package": "mcp",
        "version": "1.28.1",
        "license": "MIT",
        "filename": "mcp-1.28.1-py3-none-any.whl",
        "sha256": "2726bca5e7193f61c5dde8b12500a6de2d9acf6d1a1c0be9e8c2e706437991df",
        "sourceUrl": "https://files.pythonhosted.org/packages/e2/5e/d118fce19f87a2e7d8101c35c8ae0ec289098a4df0ff244cec23e415aca0/mcp-1.28.1-py3-none-any.whl",
        "intranetUri": "devpi://skillify/mcp/1.28.1/mcp-1.28.1-py3-none-any.whl",
    }
    assert value["version"].split(".", 1)[0] == "1"


def test_mcp_sdk_manifest_checksum_detects_tampering(tmp_path: Path) -> None:
    wheel = tmp_path / "mcp.whl"
    wheel.write_bytes(b"tampered")
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["sha256"]

    assert hashlib.sha256(wheel.read_bytes()).hexdigest() != expected
