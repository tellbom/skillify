from pathlib import Path

import yaml

from skillify.agent.shogun.contract import read_queue_file


def test_command_queue_reads_approved_upstream_top_level_list(tmp_path: Path) -> None:
    path = tmp_path / "shogun_to_karo.yaml"
    path.write_text(yaml.safe_dump([
        {"id": "cmd-1", "status": "in_progress", "purpose": "acceptance"},
    ]), encoding="utf-8")

    items = read_queue_file(path)

    assert [(item.kind, item.item_id, item.status) for item in items] == [
        ("command", "cmd-1", "in_progress"),
    ]


def test_command_queue_keeps_wrapped_legacy_form(tmp_path: Path) -> None:
    path = tmp_path / "shogun_to_karo.yaml"
    path.write_text(yaml.safe_dump({
        "commands": [{"id": "cmd-1", "status": "done"}],
    }), encoding="utf-8")

    assert read_queue_file(path)[0].status == "done"
