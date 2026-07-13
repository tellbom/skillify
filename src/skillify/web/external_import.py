"""No-guess scanning and conversion of external Agent Skill archives."""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi.encoders import jsonable_encoder

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

from skillify.common.config import SkillifyConfig
from skillify.validator.skill_md import REQUIRED_FRONTMATTER_FIELDS, parse_frontmatter
from skillify.web.build_service import store_for_config
from skillify.web.build_store import BuildStore
from skillify.web.upload import safe_extract_zip

_DETECTED_NAMES = (
    "scripts",
    "assets",
    "references",
    "resources",
    "examples",
    "requirements.txt",
    "pyproject.toml",
    "package.json",
)

_ACTIVE_SELECTION_TOKENS: set[str] = set()
_ACTIVE_SELECTION_TOKENS_LOCK = threading.Lock()


def _process_is_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class ExternalScanNotFound(Exception):
    pass


class InvalidExternalScan(Exception):
    pass


class NoSkillCandidates(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _scan_root(cfg: SkillifyConfig) -> Path:
    return cfg.cache_dir / "skill-scans"


def _cleanup_expired_scans(cfg: SkillifyConfig) -> None:
    root = _scan_root(cfg)
    if not root.is_dir():
        return
    now = _now()
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        if directory.name.startswith("."):
            age = now.timestamp() - directory.stat().st_mtime
            if age > cfg.build_ttl_seconds:
                shutil.rmtree(directory, ignore_errors=True)
            continue
        try:
            metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
            expired = datetime.fromisoformat(metadata["expiresAt"]) <= now
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            expired = True
        if expired:
            lock_path = directory / ".selection.lock"
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileNotFoundError:
                continue
            except FileExistsError:
                try:
                    lease = json.loads(lock_path.read_text(encoding="utf-8"))
                    lock_age = now.timestamp() - lock_path.stat().st_mtime
                except (OSError, json.JSONDecodeError):
                    lease = {}
                    lock_age = max(cfg.build_ttl_seconds, 300) + 1
                with _ACTIVE_SELECTION_TOKENS_LOCK:
                    locally_active = lease.get("token") in _ACTIVE_SELECTION_TOKENS
                if locally_active or _process_is_alive(lease.get("pid")):
                    continue
                if lock_age <= max(cfg.build_ttl_seconds, 300):
                    continue
                stale_path = directory / f".selection.lock.stale.{uuid.uuid4().hex}"
                try:
                    lock_path.replace(stale_path)
                    descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except (FileNotFoundError, FileExistsError):
                    continue
            else:
                pass
            os.close(descriptor)
            shutil.rmtree(directory, ignore_errors=True)


@contextmanager
def _scan_selection_lease(directory: Path):
    lock_path = directory / ".selection.lock"
    token = uuid.uuid4().hex
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileNotFoundError as exc:
        raise ExternalScanNotFound("external scan not found") from exc
    except FileExistsError as exc:
        raise InvalidExternalScan("external scan is already being selected") from exc
    os.write(
        descriptor,
        json.dumps({"token": token, "pid": os.getpid(), "startedAt": _now().isoformat()}).encode("utf-8"),
    )
    os.fsync(descriptor)
    os.close(descriptor)
    with _ACTIVE_SELECTION_TOKENS_LOCK:
        _ACTIVE_SELECTION_TOKENS.add(token)

    stop_heartbeat = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_heartbeat.wait(1.0):
            try:
                value = json.loads(lock_path.read_text(encoding="utf-8"))
                if value.get("token") != token:
                    return
                os.utime(lock_path, None)
            except (OSError, json.JSONDecodeError):
                return

    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()

    def heartbeat() -> None:
        try:
            value = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExternalScanNotFound("external scan lease was lost") from exc
        if value.get("token") != token:
            raise ExternalScanNotFound("external scan lease was lost")
        os.utime(lock_path, None)

    try:
        yield heartbeat
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2.0)
        with _ACTIVE_SELECTION_TOKENS_LOCK:
            _ACTIVE_SELECTION_TOKENS.discard(token)
        try:
            value = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        if value.get("token") == token:
            lock_path.unlink(missing_ok=True)


def _scan_dir(cfg: SkillifyConfig, scan_id: str) -> Path:
    try:
        normalized = uuid.UUID(scan_id).hex
    except (ValueError, AttributeError, TypeError) as exc:
        raise ExternalScanNotFound("external scan not found") from exc
    return _scan_root(cfg) / normalized


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _load_scan(cfg: SkillifyConfig, scan_id: str, owner: str) -> tuple[Path, dict[str, Any]]:
    directory = _scan_dir(cfg, scan_id)
    try:
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalScanNotFound("external scan not found") from exc
    if metadata.get("owner") != owner:
        raise ExternalScanNotFound("external scan not found")
    try:
        expired = datetime.fromisoformat(metadata["expiresAt"]) <= _now()
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalScanNotFound("external scan not found") from exc
    if expired:
        raise ExternalScanNotFound("external scan not found")
    return directory, metadata


def _frontmatter(skill_md: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    try:
        text = skill_md.read_text(encoding="utf-8")
        parsed = parse_frontmatter(text)
    except UnicodeDecodeError as exc:
        return {}, [{"path": "SKILL.md", "message": f"must be UTF-8: {exc}"}]
    except yaml.YAMLError as exc:
        return {}, [{"path": "SKILL.md:frontmatter", "message": f"invalid YAML: {exc}"}]
    if parsed is None:
        return {}, [{"path": "SKILL.md:frontmatter", "message": "missing or malformed YAML frontmatter"}]
    for field in REQUIRED_FRONTMATTER_FIELDS:
        value = parsed.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                {"path": f"SKILL.md:frontmatter.{field}", "message": "required and must be a non-empty string"}
            )
    return jsonable_encoder(parsed), issues


def _requirements(root: Path) -> tuple[list[str], list[dict[str, str]]]:
    requirements: list[str] = []
    issues: list[dict[str, str]] = []
    requirements_txt = root / "requirements.txt"
    if requirements_txt.is_file():
        try:
            requirements.extend(
                line.strip()
                for line in requirements_txt.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            )
        except UnicodeDecodeError as exc:
            issues.append({"path": "requirements.txt", "message": f"must be UTF-8: {exc}"})

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = parsed.get("project")
            if project is not None and not isinstance(project, dict):
                issues.append(
                    {
                        "path": "pyproject.toml:project",
                        "message": "project must be a TOML table",
                    }
                )
            elif isinstance(project, dict):
                declared = project.get("dependencies")
                if declared is not None and (
                    not isinstance(declared, list)
                    or not all(isinstance(item, str) and item.strip() for item in declared)
                ):
                    issues.append(
                        {
                            "path": "pyproject.toml:project.dependencies",
                            "message": "dependencies must be an array of non-empty strings",
                        }
                    )
                elif isinstance(declared, list):
                    requirements.extend(declared)
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            issues.append(
                {
                    "path": "pyproject.toml",
                    "message": f"could not parse explicit dependencies: {exc}",
                }
            )

    return list(dict.fromkeys(requirements)), issues


def scan_external_zip(
    zip_path: Path,
    cfg: SkillifyConfig,
    *,
    owner: str,
) -> dict[str, Any]:
    cfg.ensure_dirs()
    _cleanup_expired_scans(cfg)
    scan_id = uuid.uuid4().hex
    final_directory = _scan_root(cfg) / scan_id
    directory = _scan_root(cfg) / f".{scan_id}.tmp"
    extracted = directory / "extracted"
    directory.mkdir(parents=True, exist_ok=False)
    try:
        safe_extract_zip(
            zip_path,
            extracted,
            max_extracted_bytes=cfg.max_extracted_bytes,
            max_extracted_files=cfg.max_extracted_files,
        )
        skill_files = sorted(extracted.rglob("SKILL.md"), key=lambda path: path.as_posix())
        if not skill_files:
            raise NoSkillCandidates("archive does not contain SKILL.md")

        candidates: list[dict[str, Any]] = []
        for skill_md in skill_files:
            root = skill_md.parent
            frontmatter, issues = _frontmatter(skill_md)
            python_requirements, requirement_issues = _requirements(root)
            detected = sorted(name for name in _DETECTED_NAMES if (root / name).exists())
            candidates.append(
                {
                    "candidateId": uuid.uuid4().hex,
                    "rootPath": root.relative_to(extracted).as_posix() or ".",
                    "frontmatter": frontmatter,
                    "detectedPaths": detected,
                    "pythonRequirements": python_requirements,
                    "issues": issues + requirement_issues,
                }
            )

        expires_at = _now() + timedelta(seconds=cfg.build_ttl_seconds)
        metadata = {
            "scanId": scan_id,
            "owner": owner,
            "expiresAt": expires_at.isoformat(),
            "candidates": candidates,
        }
        _write_json(directory / "metadata.json", metadata)
        directory.replace(final_directory)
        return {"scanId": scan_id, "expiresAt": expires_at, "candidates": candidates}
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        shutil.rmtree(final_directory, ignore_errors=True)
        raise


def select_external_candidates(
    cfg: SkillifyConfig,
    *,
    owner: str,
    scan_id: str,
    candidate_ids: list[str],
) -> list[Any]:
    _cleanup_expired_scans(cfg)
    if not candidate_ids:
        raise InvalidExternalScan("at least one candidateId is required")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise InvalidExternalScan("candidateIds must not contain duplicates")

    directory = _scan_dir(cfg, scan_id)
    with _scan_selection_lease(directory) as heartbeat:
        directory, metadata = _load_scan(cfg, scan_id, owner)
        by_id = {item["candidateId"]: item for item in metadata.get("candidates") or []}
        if any(candidate_id not in by_id for candidate_id in candidate_ids):
            raise InvalidExternalScan("candidateId does not belong to this scan")
        already_selected = set(metadata.get("selectedCandidateIds") or [])
        if already_selected.intersection(candidate_ids):
            raise InvalidExternalScan("candidateId has already been selected")

        store: BuildStore = store_for_config(cfg)
        records = []
        try:
            for candidate_id in candidate_ids:
                candidate = by_id[candidate_id]
                facts = {
                    "rootPath": candidate["rootPath"],
                    "frontmatter": candidate["frontmatter"],
                    "detectedPaths": candidate["detectedPaths"],
                    "pythonRequirements": candidate["pythonRequirements"],
                }
                record = store.create(owner, "external", detected_facts=facts)
                records.append(record)
                source = directory / "extracted" / Path(candidate["rootPath"])
                heartbeat()
                shutil.copytree(source, record.workspace, dirs_exist_ok=True)
                heartbeat()

                manifest: dict[str, Any] = {
                    "manifestVersion": 1,
                    "entrypoints": {},
                    "orchestration": {},
                    "reporting": {"enabled": False},
                }
                for field in ("name", "description"):
                    value = candidate["frontmatter"].get(field)
                    if value is not None:
                        manifest[field] = value
                if candidate["pythonRequirements"]:
                    manifest["dependencies"] = {
                        "python": candidate["pythonRequirements"],
                        "system": [],
                        "skills": [],
                    }
                (record.workspace / "skill.yaml").write_text(
                    yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
                    encoding="utf-8",
                )
            selected = [store.load(record.build_id, owner) for record in records]
            metadata["selectedCandidateIds"] = sorted(already_selected.union(candidate_ids))
            _write_json(directory / "metadata.json", metadata)
            return selected
        except Exception:
            for record in records:
                try:
                    store.delete(record.build_id, owner)
                except Exception:
                    pass
            raise
