"""Safe zip extraction for browser-uploaded skill packages (T4.2).

Mirrors `install.extract.safe_extract`'s protections (path-traversal / zip-slip) but for
`.zip` instead of `.tar.gz`, since a web upload is arbitrary user content just like an
install artifact — the same supply-chain caution applies (PLAN.md §6.2).

M-D (docs/review-m2-m6.md): also bounds *decompressed* size and entry count — a zip's
compressed size on disk says nothing about how much it expands to (a "zip bomb"), so a
small upload could otherwise exhaust memory/disk during extraction.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


class UnsafeUpload(Exception):
    pass


def _is_within_directory(directory: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def safe_extract_zip(
    zip_path: Path,
    dest_dir: Path,
    *,
    max_extracted_bytes: int = 100 * 1024 * 1024,
    max_extracted_files: int = 5000,
) -> None:
    try:
        _extract_zip(
            zip_path,
            dest_dir,
            max_extracted_bytes=max_extracted_bytes,
            max_extracted_files=max_extracted_files,
        )
    except UnsafeUpload:
        raise
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        RuntimeError,
        ValueError,
        FileExistsError,
        NotADirectoryError,
    ) as exc:
        raise UnsafeUpload(f"invalid zip archive: {exc}") from exc


def _extract_zip(
    zip_path: Path,
    dest_dir: Path,
    *,
    max_extracted_bytes: int = 100 * 1024 * 1024,
    max_extracted_files: int = 5000,
) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        if len(infos) > max_extracted_files:
            raise UnsafeUpload(f"archive contains {len(infos)} files, exceeding the {max_extracted_files} limit")

        total_size = 0
        for info in infos:
            total_size += info.file_size
            if total_size > max_extracted_bytes:
                raise UnsafeUpload(
                    f"archive's decompressed size exceeds the {max_extracted_bytes} byte limit"
                )
            # Zip stores symlinks via the external_attr high bits (unix mode); reject them —
            # same rationale as safe_extract rejecting tar symlinks/hardlinks.
            unix_mode = info.external_attr >> 16
            if unix_mode and (unix_mode & 0o170000) == 0o120000:
                raise UnsafeUpload(f"{info.filename}: symlinks are not allowed in uploaded skill packages")
            member_path = dest_dir / info.filename
            if not _is_within_directory(dest_dir, member_path):
                raise UnsafeUpload(f"{info.filename}: escapes the extraction directory")
        zf.extractall(dest_dir)
