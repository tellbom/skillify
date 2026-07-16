from __future__ import annotations

import stat

from skillify.credentials.store import EncryptedFileSecretStore, KeyringSecretStore


def test_encrypted_file_store_separates_key_and_ciphertext(tmp_path) -> None:
    path = tmp_path / "credentials.enc"
    key_path = tmp_path / "keys" / "credentials.key"
    store = EncryptedFileSecretStore(path, key_path)
    store.set("local://orders/current-user", "top-secret")

    assert store.get("local://orders/current-user") == "top-secret"
    assert "top-secret" not in path.read_text(encoding="utf-8")
    assert path != key_path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert store.references() == ("local://orders/current-user",)
    assert store.delete("local://orders/current-user") is True


def test_keyring_adapter_uses_backend_without_serializing_secret() -> None:
    values = {}

    class Backend:
        def set_password(self, service, reference, secret): values[(service, reference)] = secret
        def get_password(self, service, reference): return values.get((service, reference))
        def delete_password(self, service, reference): del values[(service, reference)]

    store = KeyringSecretStore(Backend())
    store.set("local://orders/current-user", "secret")
    assert store.get("local://orders/current-user") == "secret"
    assert store.delete("local://orders/current-user") is True
