from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from skillify.apps import load_app_contract
from skillify.apps.file_processing import process_text, summarize_csv


ROOT = Path(__file__).parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_file_processing_manifest_pins_published_skills_without_network_dependencies() -> None:
    app_dir = ROOT / "apps/file-processing"
    contract = load_app_contract(yaml.safe_load((app_dir / "app.yaml").read_text(encoding="utf-8")))
    assert [(item.id, item.version) for item in contract.skills] == [
        ("word-frequency", "0.1.0"), ("pivot-analysis", "0.1.0"),
    ]
    assert "Standard-library-only" in (app_dir / "requirements.lock").read_text(encoding="utf-8")


def test_text_processor_is_deterministic_and_does_not_modify_input(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("Pear apple pear. APPLE pear banana.\n", encoding="utf-8")
    before = _sha(source)

    first = process_text(source, tmp_path / "output-one", top=3)
    second = process_text(source, tmp_path / "output-two", top=3)

    assert _sha(source) == before
    assert (tmp_path / "output-one/word-frequency.csv").read_text() == (
        tmp_path / "output-two/word-frequency.csv"
    ).read_text()
    assert (tmp_path / "output-one/word-frequency.csv").read_text() == (
        "word,count\npear,3\napple,2\nbanana,1\n"
    )
    assert first["changes"][0]["operation"] == "created"
    assert first == second


def test_csv_summary_is_deterministic_and_writes_change_manifest(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    source.write_text("region,amount\nwest,10.5\neast,3\nwest,2.5\n", encoding="utf-8")
    before = source.read_bytes()

    manifest = summarize_csv(
        source, tmp_path / "summary-output",
        group_by="region", value_column="amount", operation="sum",
    )

    assert source.read_bytes() == before
    assert (tmp_path / "summary-output/summary.csv").read_text() == (
        "region,sum_amount\neast,3\nwest,13\n"
    )
    assert (tmp_path / "summary-output/changes.json").is_file()
    assert manifest["input"]["name"] == "orders.csv"


def test_processors_refuse_in_place_output(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("text", encoding="utf-8")
    with pytest.raises(ValueError, match="new directory"):
        process_text(source, tmp_path)
