"""HTTP client helpers to talk to the Jellyfin API."""
from __future__ import annotations

import hashlib
import platform
from typing import Any, Dict, Optional

import requests


class JellyfinClient:
    """Thin wrapper around the Jellyfin REST API."""

    def __init__(self, server_url: str | None = None) -> None:
        self.session = requests.Session()
        self.server_url = ""
        self.access_token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.device_id: Optional[str] = None
        if server_url:
            self.configure(server_url)

    @staticmethod
    def generate_device_id() -> str:
        info = f"{platform.node()}-{platform.system()}-{platform.machine()}"
        return hashlib.md5(info.encode()).hexdigest()

    def configure(self, server_url: str) -> None:
        self.server_url = server_url.rstrip("/")

    # Authentication -----------------------------------------------------
    def authenticate(self, username: str, password: str) -> Dict[str, Any]:
        if not self.server_url:
            raise ValueError("Server URL is not configured")

        self.device_id = self.generate_device_id()

        auth_url = f"{self.server_url}/Users/authenticatebyname"
        headers = {
            "Content-Type": "application/json",
            "X-Emby-Authorization": (
                f'MediaBrowser Client="JellyGrab", Device="Python", DeviceId="{self.device_id}", Version="1.0.0"'
            ),
        }

        payload = {"Username": username, "Pw": password}
        response = self.session.post(auth_url, json=payload, headers=headers, timeout=15)

        if response.status_code != 200:
            message = "Credenciais inválidas"
            try:
                message = response.json().get("Message", message)
            except ValueError:
                pass
            raise PermissionError(message)

        data = response.json()
        self.access_token = data.get("AccessToken")
        self.user_id = data.get("User", {}).get("Id")

        if not self.access_token or not self.user_id:
            raise RuntimeError("Falha ao obter token de acesso")

        return data

    # Requests helpers ---------------------------------------------------
    def _require_auth(self) -> None:
        if not self.access_token or not self.user_id or not self.device_id:
            raise RuntimeError("Client is not authenticated")

    def request_headers(self) -> Dict[str, str]:
        self._require_auth()
        return {
            "X-Emby-Token": self.access_token or "",
            "X-Emby-Authorization": (
                f'MediaBrowser Client="JellyGrab", Device="Python", DeviceId="{self.device_id}", Version="1.0.0"'
            ),
        }

    # High level API -----------------------------------------------------
    def list_views(self) -> Dict[str, Any]:
        self._require_auth()
        url = f"{self.server_url}/Users/{self.user_id}/Views"
        params = {"IncludeHidden": "false"}
        response = self.session.get(url, headers=self.request_headers(), params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    def list_series(self, parent_id: str | None = None) -> Dict[str, Any]:
        self._require_auth()
        url = f"{self.server_url}/Users/{self.user_id}/Items"
        params = {
            "IncludeItemTypes": "Series",
            "Recursive": "true",
            "Fields": "Overview,SortName,ProductionYear",
            "SortBy": "SortName",
            "SortOrder": "Ascending",
        }
        if parent_id:
            params["ParentId"] = parent_id
        response = self.session.get(url, headers=self.request_headers(), params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def list_episodes(self, series_id: str) -> Dict[str, Any]:
        self._require_auth()
        url = f"{self.server_url}/Shows/{series_id}/Episodes"
        params = {
            "UserId": self.user_id,
            "Fields": "Overview,IndexNumber,ParentIndexNumber,MediaSources",
            "IsMissing": "false",
            "IsVirtualUnaired": "false",
        }
        response = self.session.get(url, headers=self.request_headers(), params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def list_seasons(self, series_id: str) -> Dict[str, Any]:
        self._require_auth()
        url = f"{self.server_url}/Shows/{series_id}/Seasons"
        params = {
            "UserId": self.user_id,
            "Fields": "ItemCounts,ProductionYear",
        }
        response = self.session.get(url, headers=self.request_headers(), params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def get_item(self, item_id: str) -> Dict[str, Any]:
        self._require_auth()
        url = f"{self.server_url}/Users/{self.user_id}/Items/{item_id}"
        params = {"Fields": "MediaSources"}
        response = self.session.get(url, headers=self.request_headers(), params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    def stream_episode(self, episode_id: str, timeout: int = 30) -> requests.Response:
        self._require_auth()
        download_url = f"{self.server_url}/Videos/{episode_id}/stream.mp4"
        headers = self.request_headers()
        headers.update({"Accept-Encoding": "identity", "Connection": "keep-alive"})
        response = self.session.get(download_url, headers=headers, stream=True, timeout=timeout)
        response.raise_for_status()
        return response

    def build_stream_url(self, episode_id: str) -> str:
        self._require_auth()
        return f"{self.server_url}/Videos/{episode_id}/stream.mp4"


__all__ = ["JellyfinClient"]
