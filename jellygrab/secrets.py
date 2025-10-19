"""Secure storage helpers for JellyGrab secrets."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

from cryptography.fernet import Fernet, InvalidToken


class SecureStoreError(RuntimeError):
    """Raised when secure storage cannot be accessed."""


class SecureStore:
    """Persist sensitive values encrypted at rest."""

    def __init__(
        self,
        base_directory: Optional[Path] = None,
        key_filename: str = "key.bin",
        data_filename: str = "secrets.json",
    ) -> None:
        self.base_directory = base_directory or Path.home() / ".jellygrab"
        self.base_directory.mkdir(parents=True, exist_ok=True)
        self.key_path = self.base_directory / key_filename
        self.data_path = self.base_directory / data_filename
        self._fernet = Fernet(self._load_or_create_key())
        self._data: Dict[str, str] = self._load_data()

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Return the decrypted value for *key* if present."""
        token = self._data.get(key)
        if token is None:
            return default
        try:
            decrypted = self._fernet.decrypt(token.encode("utf-8"))
        except InvalidToken as exc:
            raise SecureStoreError("Stored secret is corrupt") from exc
        return decrypted.decode("utf-8")

    def set(self, key: str, value: str) -> None:
        """Encrypt and persist *value* under *key*."""
        if not value:
            raise SecureStoreError("Cannot store empty secrets")
        encrypted = self._fernet.encrypt(value.encode("utf-8"))
        self._data[key] = encrypted.decode("utf-8")
        self._save_data()

    def delete(self, key: str) -> None:
        """Remove *key* from the secure store."""
        if key in self._data:
            self._data.pop(key)
            self._save_data()

    # Internal helpers -------------------------------------------------
    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes()
        key = Fernet.generate_key()
        with self.key_path.open("wb") as handle:
            handle.write(key)
        try:
            os.chmod(self.key_path, 0o600)
        except PermissionError:
            pass
        return key

    def _load_data(self) -> Dict[str, str]:
        if self.data_path.exists():
            try:
                with self.data_path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                    if isinstance(payload, dict):
                        return {str(k): str(v) for k, v in payload.items()}
            except Exception as exc:
                raise SecureStoreError("Unable to load secure storage") from exc
        return {}

    def _save_data(self) -> None:
        try:
            with self.data_path.open("w", encoding="utf-8") as handle:
                json.dump(self._data, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            raise SecureStoreError("Unable to persist secure storage") from exc
