"""Optional Discord Rich Presence worker.

Presence IPC is blocking, so it lives on a dedicated thread.  When pypresence
is not installed or no application id is configured, the launcher remains fully
functional and simply skips Rich Presence.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any

from PySide6.QtCore import QThread

logger = logging.getLogger(__name__)

try:
    from pypresence import Presence as _RPC
except Exception:  # optional dependency
    _RPC = None


class _PresenceWorker(QThread):
    def __init__(self, client_id: str) -> None:
        super().__init__()
        self._client_id = client_id
        self._queue: queue.Queue[tuple[str, str, str] | None] = queue.Queue()
        self._ready = threading.Event()
        self._rpc = None

    def update(self, state: str, details: str = "") -> None:
        if self.isRunning():
            self._queue.put((state, details, ""))

    def stop(self) -> None:
        self._queue.put(None)

    def run(self) -> None:
        if _RPC is None:
            return
        try:
            self._rpc = _RPC(self._client_id)
            self._rpc.connect()
            self._ready.set()
        except Exception as exc:
            logger.info("Discord Rich Presence unavailable: %s", exc)
            return
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                state, details, _ = item
                try:
                    self._rpc.update(
                        state=state or "В лаунчере Fionix",
                        details=details or "Minecraft Java Edition",
                        large_text="Fionix Launcher",
                    )
                except Exception as exc:
                    logger.debug("Discord presence update failed: %s", exc)
        finally:
            try:
                self._rpc.close()
            except Exception:
                pass


class DiscordPresence:
    def __init__(self, client_id: str) -> None:
        self._client_id = (client_id or "").strip()
        self._worker: _PresenceWorker | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._client_id and _RPC is not None)

    def start(self) -> None:
        if not self.enabled or self._worker is not None:
            return
        self._worker = _PresenceWorker(self._client_id)
        self._worker.start()
        self.set_launcher()

    def set_launcher(self) -> None:
        if self._worker is not None:
            self._worker.update("В лаунчере Fionix", "Minecraft Java Edition")

    def set_game(self, instance_name: str = "") -> None:
        if self._worker is not None:
            self._worker.update(
                "Играет в Minecraft",
                instance_name or "Minecraft Java Edition",
            )

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(1500)
            self._worker = None
