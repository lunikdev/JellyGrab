"""Configuration helpers for JellyGrab."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG_FILENAME = "jellygrab_config.json"


@dataclass
class ConfigManager:
    """Persist and retrieve application configuration values."""

    path: Path = field(default_factory=lambda: Path(DEFAULT_CONFIG_FILENAME))
    data: Dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.load()

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

    @staticmethod
    def ensure_download_directory(path: str | os.PathLike[str]) -> Path:
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        return directory
