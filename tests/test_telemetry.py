"""Tests for T6.2 — opt-in event reporting (skillify/common/telemetry.py)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from skillify.common.config import SkillifyConfig
from skillify.common.telemetry import get_or_create_machine_id, report_skill_event


class _CapturingHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.server.captured.append(json.loads(self.rfile.read(length)))
        self.send_response(204)
        self.end_headers()


@pytest.fixture()
def fake_events_server():
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.captured = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_machine_id_is_stable_across_calls(tmp_path: Path) -> None:
    cfg = SkillifyConfig(home=tmp_path / "home")
    first = get_or_create_machine_id(cfg)
    second = get_or_create_machine_id(cfg)
    assert first == second
    assert (cfg.home / "machine_id").read_text(encoding="utf-8").strip() == first


def test_report_is_noop_when_disabled(tmp_path: Path, fake_events_server) -> None:
    cfg = SkillifyConfig(
        home=tmp_path / "home",
        web_base_url=f"http://127.0.0.1:{fake_events_server.server_port}",
        reporting_enabled=False,
    )
    sent = report_skill_event(cfg, namespace="excel", name="pivot-analysis", version="0.1.0", event_type="install")
    assert sent is False
    assert fake_events_server.captured == []


def test_report_is_noop_when_web_base_url_unset(tmp_path: Path) -> None:
    cfg = SkillifyConfig(home=tmp_path / "home", reporting_enabled=True, web_base_url=None)
    sent = report_skill_event(cfg, namespace="excel", name="pivot-analysis", version="0.1.0", event_type="install")
    assert sent is False


def test_report_sends_expected_payload_when_enabled(tmp_path: Path, fake_events_server) -> None:
    cfg = SkillifyConfig(
        home=tmp_path / "home",
        web_base_url=f"http://127.0.0.1:{fake_events_server.server_port}",
        reporting_enabled=True,
    )
    sent = report_skill_event(
        cfg, namespace="excel", name="pivot-analysis", version="0.1.0", event_type="run", success=True
    )
    assert sent is True
    assert len(fake_events_server.captured) == 1
    payload = fake_events_server.captured[0]
    assert payload["eventType"] == "run"
    assert payload["version"] == "0.1.0"
    assert payload["success"] is True
    assert payload["machineId"]  # opaque id present, but nothing identifying
    assert set(payload.keys()) == {"eventType", "version", "success", "machineId"}  # no extra PII fields


def test_report_never_raises_on_unreachable_server(tmp_path: Path) -> None:
    cfg = SkillifyConfig(home=tmp_path / "home", web_base_url="http://127.0.0.1:1", reporting_enabled=True)
    sent = report_skill_event(cfg, namespace="excel", name="pivot-analysis", version="0.1.0", event_type="install")
    assert sent is False
