from __future__ import annotations

import json
import os
import threading
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from skillify.agent.capability_lock import (
    CapabilityKind,
    CapabilityLock,
    CapabilityLockError,
    CapabilityLockStore,
    GeneratedOwnership,
    InstallScope,
    LockedDependency,
)


def make_lock(**overrides: object) -> CapabilityLock:
    values: dict[str, object] = {
        "schema_version": 1,
        "kind": CapabilityKind.SKILL,
        "namespace": "excel",
        "name": "pivot-analysis",
        "version": "1.2.3",
        "forgejo_release": "v1.2.3",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "checksum": "a" * 64,
        "dependencies": (
            LockedDependency("skill", "excel/lookup", "2.0.0", "b" * 64),
        ),
        "scope": InstallScope.PROJECT,
        "generated": (
            GeneratedOwnership(".opencode/skills/pivot-analysis/SKILL.md", None, "c" * 64),
        ),
        "installed_at": "2026-07-16T00:00:00+00:00",
    }
    values.update(overrides)
    return CapabilityLock(**values)  # type: ignore[arg-type]


def test_capability_lock_is_canonical_immutable_and_round_trips() -> None:
    lock = make_lock(
        dependencies=(
            LockedDependency("workflow", "zeta/build", "1.0.0", "d" * 64),
            LockedDependency("skill", "alpha/lookup", "2.0.0", "b" * 64),
        ),
        generated=(
            GeneratedOwnership("z/file", None, "e" * 64),
            GeneratedOwnership("a/config.json", "/mcp/repo~1search", "f" * 64),
        ),
    )

    text = lock.to_json()

    assert text == CapabilityLock.from_json(text).to_json()
    assert json.loads(text)["dependencies"][0]["identifier"] == "alpha/lookup"
    assert json.loads(text)["generated"][0]["path"] == "a/config.json"
    assert '"latest"' not in text
    assert lock.digest == __import__("hashlib").sha256(text.encode()).hexdigest()
    with pytest.raises(FrozenInstanceError):
        lock.version = "9.9.9"  # type: ignore[misc]


def test_capability_lock_normalizes_equivalent_utc_timestamp_spelling() -> None:
    assert make_lock(installed_at="2026-07-16T00:00:00Z").installed_at == "2026-07-16T00:00:00+00:00"


@pytest.mark.parametrize("version", ["", "latest", "main", "^1.2.3", "1.2", "01.2.3"])
def test_lock_rejects_non_exact_version(version: str) -> None:
    with pytest.raises(CapabilityLockError, match="exact semantic version"):
        make_lock(version=version)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("commit", "a" * 39, "40-hex"),
        ("checksum", "g" * 64, "64-hex"),
        ("installed_at", "2026-07-16T00:00:00", "UTC"),
        ("installed_at", "2026-07-16T01:00:00+01:00", "UTC"),
        ("forgejo_release", "latest", "immutable"),
    ],
)
def test_lock_rejects_mutable_or_malformed_identity(field: str, value: str, message: str) -> None:
    with pytest.raises(CapabilityLockError, match=message):
        make_lock(**{field: value})


@pytest.mark.parametrize(
    "path",
    [
        "/absolute/file", "../escape", "a/../../escape", "a\\..\\escape",
        "a/./file", "a//file", "a/file/", "a/\x00file", "a/\x1ffile",
    ],
)
def test_generated_ownership_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(CapabilityLockError, match="relative safe path"):
        GeneratedOwnership(path, None, "a" * 64)


@pytest.mark.parametrize("pointer", ["mcp/key", "/mcp/~", "/mcp/~2bad"])
def test_generated_ownership_rejects_invalid_json_pointer(pointer: str) -> None:
    with pytest.raises(CapabilityLockError, match="JSON pointer"):
        GeneratedOwnership("opencode.json", pointer, "a" * 64)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: GeneratedOwnership("bad\ud800name", None, "a" * 64),
        lambda: GeneratedOwnership("opencode.json", "/mcp/bad\udfffname", "a" * 64),
        lambda: LockedDependency("skill", "excel/bad\ud800name", "1.0.0", "a" * 64),
        lambda: make_lock(namespace="bad\ud800name"),
        lambda: make_lock(forgejo_release="v1.2.3\udfff"),
        lambda: make_lock(installed_at="2026-07-16T00:00:00+00:00\ud800"),
    ],
)
def test_constructor_rejects_non_utf8_unicode_scalar_strings(factory) -> None:
    with pytest.raises(CapabilityLockError, match="valid UTF-8"):
        factory()


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("generated", "path", "bad\ud800name"),
        ("generated", "json_pointer", "/mcp/bad\udfffname"),
        ("dependencies", "identifier", "excel/bad\ud800name"),
        ("lock", "namespace", "bad\udfffname"),
        ("lock", "forgejo_release", "v1.2.3\ud800"),
        ("lock", "installed_at", "2026-07-16T00:00:00+00:00\udfff"),
    ],
)
def test_from_json_rejects_non_utf8_unicode_scalar_strings(
    section: str, field: str, value: str,
) -> None:
    data = json.loads(make_lock().to_json())
    if section == "lock":
        data[field] = value
    else:
        data[section][0][field] = value

    with pytest.raises(CapabilityLockError, match="valid UTF-8"):
        CapabilityLock.from_json(json.dumps(data))


def test_valid_unicode_scalar_generated_path_remains_canonical() -> None:
    lock = make_lock(generated=(GeneratedOwnership("skills/分析-😀.md", None, "a" * 64),))
    assert CapabilityLock.from_json(lock.to_json()).digest == lock.digest


def test_lock_rejects_duplicate_dependencies_and_ownership() -> None:
    dependency = LockedDependency("skill", "excel/lookup", "2.0.0", "b" * 64)
    with pytest.raises(CapabilityLockError, match="duplicate dependency"):
        make_lock(dependencies=(dependency, replace(dependency, version="3.0.0")))

    ownership = GeneratedOwnership("opencode.json", "/mcp/echo", "c" * 64)
    with pytest.raises(CapabilityLockError, match="duplicate generated ownership"):
        make_lock(generated=(ownership, ownership))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update({"unexpected": True}),
        lambda data: data["dependencies"][0].update({"unexpected": True}),
        lambda data: data["generated"][0].update({"unexpected": True}),
        lambda data: data.update({"schema_version": "1"}),
        lambda data: data.update({"dependencies": {}}),
    ],
)
def test_from_json_rejects_unknown_fields_and_wrong_types(mutation) -> None:
    data = json.loads(make_lock().to_json())
    mutation(data)
    with pytest.raises(CapabilityLockError):
        CapabilityLock.from_json(json.dumps(data))


@pytest.mark.parametrize(
    "text",
    [
        '{"schema_version":1,"schema_version":1}',
        make_lock().to_json().replace('"kind":"skill"', '"kind":"skill","kind":"skill"'),
        make_lock().to_json().replace(
            '"identifier":"excel/lookup"',
            '"identifier":"excel/lookup","identifier":"excel/lookup"',
        ),
        make_lock().to_json().replace(
            '"json_pointer":null',
            '"json_pointer":null,"json_pointer":null',
        ),
    ],
)
def test_from_json_rejects_duplicate_fields_at_every_level(text: str) -> None:
    with pytest.raises(CapabilityLockError, match="duplicate JSON field"):
        CapabilityLock.from_json(text)


def test_store_writes_current_and_digest_history_atomically_with_private_modes(tmp_path: Path) -> None:
    store = CapabilityLockStore(tmp_path / "locks")
    first = make_lock()
    second = replace(first, version="1.2.4", forgejo_release="v1.2.4", checksum="d" * 64)

    current = store.write_current(first)
    store.write_current(second)

    assert store.read_current(CapabilityKind.SKILL, "excel", "pivot-analysis") == second
    assert store.read_digest(first.digest) == first
    assert store.read_digest(second.digest) == second
    assert current.stat().st_mode & 0o777 == 0o600
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in (tmp_path / "locks/history").glob("*.json"))
    assert not list((tmp_path / "locks").rglob("*.tmp"))

    store.remove_current(second)
    assert store.read_current(CapabilityKind.SKILL, "excel", "pivot-analysis") is None
    assert store.read_digest(first.digest) == first


def test_store_rejects_coordinate_traversal_and_digest_traversal(tmp_path: Path) -> None:
    store = CapabilityLockStore(tmp_path / "locks")
    with pytest.raises(CapabilityLockError, match="namespace"):
        store.read_current(CapabilityKind.SKILL, "../escape", "thing")
    with pytest.raises(CapabilityLockError, match="digest"):
        store.read_digest("../escape")


def test_store_rejects_symlinked_store_paths(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "locks"
    root.mkdir()
    (root / "current").symlink_to(outside, target_is_directory=True)
    store = CapabilityLockStore(root)

    with pytest.raises(CapabilityLockError, match="symlink"):
        store.write_current(make_lock())
    assert not list(outside.iterdir())


def test_store_rejects_symlink_in_root_ancestor(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)

    with pytest.raises(CapabilityLockError, match="symlink"):
        CapabilityLockStore(alias / "locks").write_current(make_lock())
    assert not (outside / "locks").exists()


def test_store_never_reads_or_removes_through_symlinked_directories(tmp_path: Path) -> None:
    lock = make_lock()
    outside = tmp_path / "outside"
    current_outside = outside / "skill" / "excel"
    current_outside.mkdir(parents=True)
    outside_current = current_outside / "pivot-analysis.json"
    outside_current.write_text(lock.to_json(), encoding="utf-8")
    history_outside = tmp_path / "history-outside"
    history_outside.mkdir()
    (history_outside / f"{lock.digest}.json").write_text(lock.to_json(), encoding="utf-8")

    root = tmp_path / "locks"
    root.mkdir()
    (root / "current").symlink_to(outside, target_is_directory=True)
    (root / "history").symlink_to(history_outside, target_is_directory=True)
    store = CapabilityLockStore(root)

    with pytest.raises(CapabilityLockError, match="symlink"):
        store.read_current(lock.kind, lock.namespace, lock.name)
    with pytest.raises(CapabilityLockError, match="symlink"):
        store.read_digest(lock.digest)
    with pytest.raises(CapabilityLockError, match="symlink"):
        store.remove_current(lock)
    assert outside_current.read_text(encoding="utf-8") == lock.to_json()


def test_store_rejects_symlinked_current_file(tmp_path: Path) -> None:
    store = CapabilityLockStore(tmp_path / "locks")
    lock = make_lock()
    current = store.write_current(lock)
    outside = tmp_path / "outside.json"
    outside.write_text("owned", encoding="utf-8")
    current.unlink()
    current.symlink_to(outside)

    with pytest.raises(CapabilityLockError, match="symlink"):
        store.read_current(lock.kind, lock.namespace, lock.name)
    with pytest.raises(CapabilityLockError, match="symlink"):
        store.write_current(lock)
    assert outside.read_text(encoding="utf-8") == "owned"


def test_store_rejects_current_lock_whose_content_has_different_coordinate(tmp_path: Path) -> None:
    store = CapabilityLockStore(tmp_path / "locks")
    expected = make_lock()
    current = store.write_current(expected)
    misplaced = replace(expected, namespace="other")
    current.write_text(misplaced.to_json(), encoding="utf-8")

    with pytest.raises(CapabilityLockError, match="coordinate mismatch"):
        store.read_current(expected.kind, expected.namespace, expected.name)


def test_store_refuses_to_remove_newer_current_with_stale_lock(tmp_path: Path) -> None:
    store = CapabilityLockStore(tmp_path / "locks")
    first = make_lock()
    second = replace(first, version="1.2.4", forgejo_release="v1.2.4", checksum="d" * 64)
    store.write_current(first)
    store.write_current(second)

    with pytest.raises(CapabilityLockError, match="does not match current"):
        store.remove_current(first)
    assert store.read_current(second.kind, second.namespace, second.name) == second


def test_remove_validates_and_unlinks_through_same_parent_descriptor(tmp_path: Path, monkeypatch) -> None:
    store = CapabilityLockStore(tmp_path / "locks")
    lock = make_lock()
    store.write_current(lock)
    real_open_parent = store._open_parent
    opened: list[Path] = []

    def recording_open_parent(path: Path, *, create: bool):
        opened.append(path)
        return real_open_parent(path, create=create)

    monkeypatch.setattr(store, "_open_parent", recording_open_parent)
    store.remove_current(lock)

    assert opened == [store._current_path(lock)]


def test_remove_does_not_delete_concurrently_written_current(tmp_path: Path, monkeypatch) -> None:
    first_store = CapabilityLockStore(tmp_path / "locks")
    second_store = CapabilityLockStore(tmp_path / "locks")
    first = make_lock()
    second = replace(first, version="1.2.4", forgejo_release="v1.2.4", checksum="d" * 64)
    first_store.write_current(first)
    current_path = first_store._current_path(first)
    writer_started = threading.Event()
    writer_done = threading.Event()
    writer_errors: list[BaseException] = []

    def write_new_current() -> None:
        writer_started.set()
        try:
            second_store.write_current(second)
        except BaseException as exc:  # surfaced in the test thread below
            writer_errors.append(exc)
        finally:
            writer_done.set()

    real_reject = first_store._reject_leaf_symlink
    writer: threading.Thread | None = None

    def interleave_before_unlink(directory_fd: int, name: str, path: Path) -> None:
        nonlocal writer
        real_reject(directory_fd, name, path)
        if path == current_path and writer is None:
            writer = threading.Thread(target=write_new_current)
            writer.start()
            assert writer_started.wait(timeout=1)
            writer_done.wait(timeout=0.2)

    monkeypatch.setattr(first_store, "_reject_leaf_symlink", interleave_before_unlink)
    first_store.remove_current(first)
    assert writer is not None
    writer.join(timeout=2)

    assert not writer.is_alive()
    assert writer_errors == []
    assert first_store.read_current(second.kind, second.namespace, second.name) == second


def test_atomic_write_never_uses_path_following_chmod(tmp_path: Path, monkeypatch) -> None:
    real_chmod = os.chmod

    def reject_path_chmod(*args, **kwargs):
        raise AssertionError("store must use descriptor-anchored fchmod")

    monkeypatch.setattr(os, "chmod", reject_path_chmod)
    current = CapabilityLockStore(tmp_path / "locks").write_current(make_lock())
    monkeypatch.setattr(os, "chmod", real_chmod)

    assert current.stat().st_mode & 0o777 == 0o600
