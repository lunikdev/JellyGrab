"""Download queue and background workers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import queue
import threading
import time
from typing import Callable, Dict, Optional

from .client import JellyfinClient


ProgressCallback = Callable[["DownloadItem", Dict[str, float | str]], None]
StatusCallback = Callable[["DownloadItem", str], None]
ErrorCallback = Callable[["DownloadItem", Exception], None]
QueueCallback = Callable[[], None]


@dataclass
class DownloadItem:
    episode_id: str
    filename: str
    filepath: Path
    download_url: str
    total_size: int = 0
    downloaded: int = 0
    status: str = "Na fila"
    speed: str = "0 MB/s"
    eta: str = ""
    start_time: Optional[float] = None
    last_downloaded: int = 0
    last_time: float = field(default_factory=time.time)
    show_success: bool = True

    def as_progress_payload(self) -> Dict[str, float | str]:
        percent = (self.downloaded / self.total_size * 100) if self.total_size else 0.0
        return {
            "percent": percent,
            "downloaded": self.downloaded,
            "total_size": self.total_size,
            "speed": self.speed,
            "eta": self.eta,
        }


class DownloadController:
    """Coordinate downloads in the background and notify observers."""

    def __init__(
        self,
        client: JellyfinClient,
        max_concurrent: int = 2,
        chunk_size_mb: float = 1.0,
        on_queue_update: QueueCallback | None = None,
        on_status: StatusCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.client = client
        self.max_concurrent = max(1, max_concurrent)
        self.on_queue_update = on_queue_update
        self.on_status = on_status
        self.on_progress = on_progress
        self.on_error = on_error
        self.chunk_size = self._sanitize_chunk_size(chunk_size_mb)

        self.queue: "queue.Queue[DownloadItem]" = queue.Queue()
        self.items: Dict[str, DownloadItem] = {}
        self.current_downloads = 0
        self.cancelled: set[str] = set()
        self._lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._workers: list[threading.Thread] = []

        self._ensure_workers(self.max_concurrent)

    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize_chunk_size(chunk_size_mb: float) -> int:
        chunk_mb = max(0.25, float(chunk_size_mb))
        return int(chunk_mb * 1024 * 1024)

    # ------------------------------------------------------------------
    def set_callbacks(
        self,
        on_queue_update: QueueCallback | None = None,
        on_status: StatusCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        if on_queue_update is not None:
            self.on_queue_update = on_queue_update
        if on_status is not None:
            self.on_status = on_status
        if on_progress is not None:
            self.on_progress = on_progress
        if on_error is not None:
            self.on_error = on_error

    # ------------------------------------------------------------------
    def queue_size(self) -> int:
        return self.queue.qsize()

    # ------------------------------------------------------------------
    def queue_episode(self, episode_id: str, download_path: Path, show_success: bool = True) -> None:
        metadata = self.client.get_item(episode_id)
        series_name = metadata.get("SeriesName", "Serie")
        season = metadata.get("ParentIndexNumber", 0)
        episode = metadata.get("IndexNumber", 0)
        ep_name = metadata.get("Name", "Episodio")
        media_sources = metadata.get("MediaSources", [{}])
        total_size = media_sources[0].get("Size", 0) if media_sources else 0

        safe_series = "".join(c for c in series_name if c.isalnum() or c in (" ", "-", "_"))
        safe_ep = "".join(c for c in ep_name if c.isalnum() or c in (" ", "-", "_"))
        filename = f"{safe_series} - S{season:02d}E{episode:02d} - {safe_ep}.mp4"
        series_folder = download_path / safe_series
        series_folder.mkdir(parents=True, exist_ok=True)
        filepath = series_folder / filename

        if filepath.exists():
            existing = self.items.get(episode_id)
            if existing:
                existing.status = "✅ Já existe"
            self._emit_status(
                DownloadItem(episode_id, filename, filepath, self.client.build_stream_url(episode_id), total_size),
                "✅ Já existe",
            )
            return

        download_url = self.client.build_stream_url(episode_id)
        item = DownloadItem(
            episode_id=episode_id,
            filename=filename,
            filepath=filepath,
            download_url=download_url,
            total_size=total_size,
            show_success=show_success,
        )

        with self._lock:
            self.items[episode_id] = item
        self.queue.put(item)
        self._emit_status(item, "🔄 Na fila")
        self._emit_queue_update()

    # ------------------------------------------------------------------
    def cancel(self, episode_id: str) -> None:
        self.cancelled.add(episode_id)

    # ------------------------------------------------------------------
    def _worker(self) -> None:
        while True:
            item = self.queue.get()
            if item.episode_id in self.cancelled:
                self.cancelled.remove(item.episode_id)
                self.queue.task_done()
                continue

            self._acquire_slot()
            self._emit_queue_update()
            self._download_item(item)
            with self._lock:
                self.current_downloads -= 1
            self._emit_queue_update()
            self.queue.task_done()

    # ------------------------------------------------------------------
    def _download_item(self, item: DownloadItem) -> None:
        item.status = "⬇️ Baixando..."
        item.start_time = time.time()
        item.last_time = item.start_time
        item.last_downloaded = 0
        self._emit_status(item, item.status)

        try:
            response = self.client.stream_episode(item.episode_id)
            total_size = item.total_size or int(response.headers.get("content-length", 0))
            if total_size:
                item.total_size = total_size

            chunk_size = self.chunk_size
            downloaded = 0

            with item.filepath.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if item.episode_id in self.cancelled:
                        self.cancelled.remove(item.episode_id)
                        raise RuntimeError("Download cancelado pelo usuário")

                    if not chunk:
                        continue

                    handle.write(chunk)
                    downloaded += len(chunk)
                    item.downloaded = downloaded

                    self._update_progress(item)

            if item.total_size == 0:
                item.total_size = downloaded
            else:
                item.downloaded = item.total_size

            item.status = "✅ Concluído"
            item.speed = "0.00 MB/s"
            item.eta = "0s"
            self._emit_status(item, item.status)

        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, RuntimeError) and "cancelado" in str(exc).lower():
                item.status = "🚫 Cancelado"
            else:
                item.status = "❌ Erro"
            self._emit_status(item, item.status)
            if self.on_error and item.status != "🚫 Cancelado":
                self.on_error(item, exc)
        else:
            if item.show_success:
                self._emit_status(item, "✅ Concluído")

    # ------------------------------------------------------------------
    def _update_progress(self, item: DownloadItem) -> None:
        now = time.time()
        elapsed = now - item.last_time
        if elapsed < 1.0:
            return

        delta = item.downloaded - item.last_downloaded
        speed = (delta / elapsed / 1024 / 1024)
        eta_seconds = 0.0
        if speed > 0 and item.total_size:
            eta_seconds = (item.total_size - item.downloaded) / (speed * 1024 * 1024)

        item.speed = f"{speed:.2f} MB/s"
        item.eta = f"{eta_seconds:.0f}s" if eta_seconds else "Desconhecido"
        item.last_time = now
        item.last_downloaded = item.downloaded

        if self.on_progress:
            self.on_progress(item, item.as_progress_payload())

    # ------------------------------------------------------------------
    def _emit_status(self, item: DownloadItem, status: str) -> None:
        item.status = status
        if self.on_status:
            self.on_status(item, status)

    def _emit_queue_update(self) -> None:
        if self.on_queue_update:
            self.on_queue_update()

    # ------------------------------------------------------------------
    def _acquire_slot(self) -> None:
        acquired = False
        while not acquired:
            with self._lock:
                if self.current_downloads < self.max_concurrent:
                    self.current_downloads += 1
                    acquired = True
                    break
            time.sleep(0.1)

    # ------------------------------------------------------------------
    def _ensure_workers(self, desired: int) -> None:
        desired = max(1, desired)
        with self._worker_lock:
            missing = desired - len(self._workers)
            for _ in range(max(0, missing)):
                worker = threading.Thread(target=self._worker, daemon=True)
                self._workers.append(worker)
                worker.start()

    # ------------------------------------------------------------------
    def set_max_concurrent(self, max_concurrent: int) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self._ensure_workers(self.max_concurrent)
        self._emit_queue_update()

    # ------------------------------------------------------------------
    def set_chunk_size_mb(self, chunk_size_mb: float) -> None:
        self.chunk_size = self._sanitize_chunk_size(chunk_size_mb)


__all__ = ["DownloadController", "DownloadItem"]
