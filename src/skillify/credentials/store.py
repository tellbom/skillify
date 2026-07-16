"""Endpoint-local secret stores; ciphertext and encryption key stay separate."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken


class SecretStore(Protocol):
    def set(self, reference: str, secret: str) -> None: ...
    def get(self, reference: str) -> str | None: ...
    def delete(self, reference: str) -> bool: ...
    def references(self) -> tuple[str, ...]: ...


class EncryptedFileSecretStore:
    def __init__(self, path: Path, key_path: Path) -> None:
        self.path = Path(path)
        self.key_path = Path(key_path)
        if self.path.resolve() == self.key_path.resolve():
            raise ValueError("encryption key and ciphertext must use separate files")

    def _fernet(self) -> Fernet:
        if not self.key_path.exists():
            self.key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(Fernet.generate_key())
        self.key_path.chmod(0o600)
        return Fernet(self.key_path.read_bytes())

    def _read(self) -> dict[str, str]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
            raise ValueError("credential store is invalid")
        return value

    def _write(self, value: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
        self.path.chmod(0o600)

    def set(self, reference: str, secret: str) -> None:
        if not reference.startswith("local://") or not secret:
            raise ValueError("credential requires a local reference and non-empty secret")
        value = self._read()
        value[reference] = self._fernet().encrypt(secret.encode()).decode()
        self._write(value)

    def get(self, reference: str) -> str | None:
        encrypted = self._read().get(reference)
        if encrypted is None:
            return None
        try:
            return self._fernet().decrypt(encrypted.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("credential ciphertext cannot be decrypted") from exc

    def delete(self, reference: str) -> bool:
        value = self._read()
        if reference not in value:
            return False
        del value[reference]
        self._write(value)
        return True

    def references(self) -> tuple[str, ...]:
        return tuple(sorted(self._read()))


class KeyringSecretStore:
    """Small adapter for Secret Service/system keyring compatible backends."""

    def __init__(self, backend, service: str = "skillify") -> None:
        self.backend = backend
        self.service = service
        self._references: set[str] = set()

    def set(self, reference: str, secret: str) -> None:
        self.backend.set_password(self.service, reference, secret)
        self._references.add(reference)

    def get(self, reference: str) -> str | None:
        return self.backend.get_password(self.service, reference)

    def delete(self, reference: str) -> bool:
        if self.get(reference) is None:
            return False
        self.backend.delete_password(self.service, reference)
        self._references.discard(reference)
        return True

    def references(self) -> tuple[str, ...]:
        return tuple(sorted(self._references))
