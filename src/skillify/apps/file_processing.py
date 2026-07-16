"""Deterministic standard-library text and CSV batch transformations."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path


PROCESSOR_VERSION = "1.0.0"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare(input_path: Path, output_dir: Path) -> tuple[Path, Path, str]:
    source = Path(input_path).resolve(strict=True)
    destination = Path(output_dir).resolve()
    if not source.is_file() or destination == source.parent or source.is_relative_to(destination):
        raise ValueError("output must be a new directory separate from the input")
    destination.mkdir(parents=True, exist_ok=False)
    return source, destination, _digest(source)


def _manifest(destination: Path, source: Path, source_digest: str, outputs: list[Path]) -> Path:
    value = {
        "processorVersion": PROCESSOR_VERSION,
        "input": {"name": source.name, "sha256": source_digest},
        "changes": [{
            "operation": "created",
            "path": output.name,
            "size": output.stat().st_size,
            "sha256": _digest(output),
        } for output in outputs],
    }
    path = destination / "changes.json"
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def process_text(input_path: Path, output_dir: Path, *, top: int = 20) -> dict[str, object]:
    if type(top) is not int or top < 1:
        raise ValueError("top must be a positive integer")
    source, destination, source_digest = _prepare(input_path, output_dir)
    words = re.findall(r"[a-z0-9]+", source.read_text(encoding="utf-8").casefold())
    counts = sorted(Counter(words).items(), key=lambda item: (-item[1], item[0]))[:top]
    output = destination / "word-frequency.csv"
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["word", "count"])
        writer.writerows(counts)
    manifest = _manifest(destination, source, source_digest, [output])
    return json.loads(manifest.read_text(encoding="utf-8"))


def summarize_csv(
    input_path: Path,
    output_dir: Path,
    *,
    group_by: str,
    value_column: str,
    operation: str = "sum",
) -> dict[str, object]:
    if operation not in {"sum", "count", "average"}:
        raise ValueError("operation must be sum, count, or average")
    source, destination, source_digest = _prepare(input_path, output_dir)
    groups: dict[str, list[Decimal]] = defaultdict(list)
    with source.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or group_by not in reader.fieldnames or value_column not in reader.fieldnames:
            raise ValueError("group and value columns must exist")
        try:
            for row in reader:
                groups[row[group_by]].append(Decimal(row[value_column]))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("value column must contain decimal numbers") from exc
    output = destination / "summary.csv"
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow([group_by, f"{operation}_{value_column}"])
        for key in sorted(groups):
            values = groups[key]
            result = Decimal(len(values)) if operation == "count" else sum(values, Decimal())
            if operation == "average":
                result /= Decimal(len(values))
            writer.writerow([key, format(result.normalize(), "f")])
    manifest = _manifest(destination, source, source_digest, [output])
    return json.loads(manifest.read_text(encoding="utf-8"))
