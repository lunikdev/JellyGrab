"""Configuration helpers for JellyGrab."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Dict

from .secrets import SecureStore, SecureStoreError


DEFAULT_CONFIG_FILENAME = "jellygrab_config.json"
SENSITIVE_KEYS = {"server_url", "username", "password"}


@dataclass
class ConfigManager:
    """Persist and retrieve application configuration values."""

    path: Path = field(default_factory=lambda: Path(DEFAULT_CONFIG_FILENAME))
    data: Dict[str, Any] = field(default_factory=dict, init=False)
    secure_store: SecureStore = field(default_factory=SecureStore, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.load()
        self._migrate_sensitive_values()

    def load(self) -> None:
        """Load configuration values from disk."""
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    self.data = json.load(handle)
            except Exception:
                self.data = {}
        else:
            self.data = {}

    def save(self) -> None:
        """Persist the in-memory configuration to disk."""
        try:
            with self.path.open("w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            raise IOError(f"Failed to write configuration file: {exc}") from exc

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    def update(self, values: Dict[str, Any]) -> None:
        self.data.update(values)
        self.save()

    def get_sensitive(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a sensitive value from secure storage."""
        if key not in SENSITIVE_KEYS:
            raise KeyError(f"{key} is not tracked as a sensitive value")
        try:
            return self.secure_store.get(key, default)
        except SecureStoreError:
            return default

    def set_sensitive(self, key: str, value: str | None) -> None:
        """Persist a sensitive value to secure storage."""
        if key not in SENSITIVE_KEYS:
            raise KeyError(f"{key} is not tracked as a sensitive value")
        try:
            if value:
                self.secure_store.set(key, value)
            else:
                self.secure_store.delete(key)
        except SecureStoreError as exc:
            raise IOError(f"Failed to persist secure value for {key}: {exc}") from exc

    def clear_sensitive(self, key: str) -> None:
        """Remove a sensitive value from secure storage."""
        if key not in SENSITIVE_KEYS:
            raise KeyError(f"{key} is not tracked as a sensitive value")
        try:
            self.secure_store.delete(key)
        except SecureStoreError:
            return

    @staticmethod
    def ensure_download_directory(path: str | os.PathLike[str]) -> Path:
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _migrate_sensitive_values(self) -> None:
        """Move sensitive values from the plain config file into secure storage."""
        changed = False
        for key in list(self.data.keys()):
            if key in SENSITIVE_KEYS:
                value = self.data.pop(key)
                if value:
                    try:
                        self.secure_store.set(key, value)
                    except SecureStoreError:
                        # Reinsert so legacy behaviour continues if secure storage fails.
                        self.data[key] = value
                        continue
                changed = True
        if changed:
            self.save()
