"""Live download registry and popover used by the title-bar task manager."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from src.ui.widgets import CapsLabel


@dataclass
class DownloadEntry:
    key: str
    title: str
    progress: int = 0
    detail: str = ""
    speed: str = ""
    started: float = 0.0
    running: bool = True


class DownloadRegistry(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[str, DownloadEntry] = {}

    def begin(self, key: str, title: str) -> None:
        self.entries[key] = DownloadEntry(key, title, started=time.monotonic())
        self.changed.emit()

    def update(self, key: str, progress: int, detail: str = "") -> None:
        entry = self.entries.get(key)
        if entry is None:
            return
        entry.progress = max(0, min(100, int(progress)))
        entry.detail = detail
        match = re.search(r"([\d.]+)\s*МБ/с", detail)
        if match:
            entry.speed = f"{match.group(1)} МБ/с"
        self.changed.emit()

    def finish(self, key: str) -> None:
        entry = self.entries.get(key)
        if entry is not None:
            entry.running = False
            self.entries.pop(key, None)
        self.changed.emit()

    def clear_finished(self) -> None:
        self.entries = {k: v for k, v in self.entries.items() if v.running}
        self.changed.emit()


downloads = DownloadRegistry()


class DownloadRow(QFrame):
    def __init__(self, entry: DownloadEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DownloadRow")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(entry.title)
        self.title.setObjectName("FieldLabel")
        top.addWidget(self.title, 1)
        self.speed = QLabel(entry.speed)
        self.speed.setObjectName("Caption")
        top.addWidget(self.speed)
        self.percent = QLabel(f"{entry.progress}%")
        self.percent.setObjectName("Caption")
        top.addWidget(self.percent)
        layout.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(entry.progress)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        layout.addWidget(self.progress)
        self.status = QLabel(entry.speed or entry.detail or "Загрузка…")
        self.status.setObjectName("Caption")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def sync(self, entry: DownloadEntry) -> None:
        self.percent.setText(f"{entry.progress}%")
        self.speed.setText(entry.speed)
        self.progress.setValue(entry.progress)
        self.status.setText(entry.speed or entry.detail or "Загрузка…")


class DownloadsPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Popover")
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(CapsLabel("ЗАГРУЗКИ", size=9, spacing=1.5, accent=True))
        self.empty = QLabel("Нет активных загрузок")
        self.empty.setObjectName("Caption")
        layout.addWidget(self.empty)
        self.list_layout = QVBoxLayout()
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        layout.addLayout(self.list_layout)
        self._rows: dict[str, DownloadRow] = {}
        downloads.changed.connect(self.refresh)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        entries = list(downloads.entries.values())
        active = {entry.key for entry in entries}
        for key in list(self._rows):
            if key not in active:
                row = self._rows.pop(key)
                row.deleteLater()
        for entry in entries:
            row = self._rows.get(entry.key)
            if row is None:
                row = DownloadRow(entry)
                self._rows[entry.key] = row
                self.list_layout.addWidget(row)
            else:
                row.sync(entry)
        self.empty.setVisible(not entries)
        self.adjustSize()

    def show_at(self, widget: QWidget) -> None:
        self.refresh()
        point = widget.mapToGlobal(widget.rect().bottomLeft())
        self.move(point.x() - self.width() + widget.width(), point.y() + 6)
        self.show()
        self.raise_()
