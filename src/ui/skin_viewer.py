"""Minecraft 3D skin viewer backed by the proven skinview3d library.

skinview3d owns the Steve/Alex hierarchy, UV atlas, outer-layer alpha, cape and
walking animation. QtWebEngine only provides the WebGL surface; there is no
custom skin renderer in the launcher.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QRect, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

# Face order: front, back, left, right, top, bottom.
SKIN_UV: dict[str, dict[str, tuple[int, int, int, int]]] = {
    "head": {
        "front": (8, 8, 8, 8), "back": (24, 8, 8, 8),
        "left": (16, 8, 8, 8), "right": (0, 8, 8, 8),
        "top": (8, 0, 8, 8), "bottom": (16, 0, 8, 8),
    },
    "hat": {
        "front": (40, 8, 8, 8), "back": (56, 8, 8, 8),
        "left": (48, 8, 8, 8), "right": (32, 8, 8, 8),
        "top": (40, 0, 8, 8), "bottom": (48, 0, 8, 8),
    },
    "body": {
        "front": (20, 20, 8, 12), "back": (32, 20, 8, 12),
        "left": (28, 20, 4, 12), "right": (16, 20, 4, 12),
        "top": (20, 16, 8, 4), "bottom": (28, 16, 8, 4),
    },
    "jacket": {
        "front": (20, 36, 8, 12), "back": (32, 36, 8, 12),
        "left": (28, 36, 4, 12), "right": (16, 36, 4, 12),
        "top": (20, 32, 8, 4), "bottom": (28, 32, 8, 4),
    },
    "right_arm": {
        "front": (44, 20, 4, 12), "back": (52, 20, 4, 12),
        "left": (48, 20, 4, 12), "right": (40, 20, 4, 12),
        "top": (44, 16, 4, 4), "bottom": (48, 16, 4, 4),
    },
    "right_sleeve": {
        "front": (44, 36, 4, 12), "back": (52, 36, 4, 12),
        "left": (48, 36, 4, 12), "right": (40, 36, 4, 12),
        "top": (44, 32, 4, 4), "bottom": (48, 32, 4, 4),
    },
    "left_arm": {
        "front": (36, 52, 4, 12), "back": (44, 52, 4, 12),
        "left": (40, 52, 4, 12), "right": (32, 52, 4, 12),
        "top": (36, 48, 4, 4), "bottom": (40, 48, 4, 4),
    },
    "left_sleeve": {
        "front": (52, 52, 4, 12), "back": (60, 52, 4, 12),
        "left": (56, 52, 4, 12), "right": (48, 52, 4, 12),
        "top": (52, 48, 4, 4), "bottom": (56, 48, 4, 4),
    },
    "right_leg": {
        "front": (4, 20, 4, 12), "back": (12, 20, 4, 12),
        "left": (8, 20, 4, 12), "right": (0, 20, 4, 12),
        "top": (4, 16, 4, 4), "bottom": (8, 16, 4, 4),
    },
    "right_pants": {
        "front": (4, 36, 4, 12), "back": (12, 36, 4, 12),
        "left": (8, 36, 4, 12), "right": (0, 36, 4, 12),
        "top": (4, 32, 4, 4), "bottom": (8, 32, 4, 4),
    },
    "left_leg": {
        "front": (20, 52, 4, 12), "back": (28, 52, 4, 12),
        "left": (24, 52, 4, 12), "right": (16, 52, 4, 12),
        "top": (20, 48, 4, 4), "bottom": (24, 48, 4, 4),
    },
    "left_pants": {
        "front": (4, 52, 4, 12), "back": (12, 52, 4, 12),
        "left": (8, 52, 4, 12), "right": (0, 52, 4, 12),
        "top": (4, 48, 4, 4), "bottom": (8, 48, 4, 4),
    },
}



_DEFAULT_COLORS = {
    "head": QColor("#C89B76"), "hat": QColor("#8B5E3B"),
    "body": QColor("#2C6C9E"), "jacket": QColor("#1C4F78"),
    "right_arm": QColor("#C89B76"), "left_arm": QColor("#C89B76"),
    "right_sleeve": QColor("#2C6C9E"), "left_sleeve": QColor("#2C6C9E"),
    "right_leg": QColor("#394B87"), "left_leg": QColor("#394B87"),
    "right_pants": QColor("#273466"), "left_pants": QColor("#273466"),
}






def _default_skin() -> QImage:
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    for part, faces in SKIN_UV.items():
        for x, y, w, h in faces.values():
            painter.fillRect(QRect(x, y, w, h), _DEFAULT_COLORS[part])
    painter.end()
    return image


def _asset_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"


def _image_data_url(image: QImage) -> str:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    encoded = base64.b64encode(bytes(buffer.data())).decode("ascii")
    return "data:image/png;base64," + encoded


def _js_string(value: str) -> str:
    import json

    return json.dumps(value)


class _WebSkin3DView(QWidget):
    """Interactive viewer using the proven skinview3d WebGL library."""

    def __init__(self, skin: QImage | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._view = QWebEngineView(self)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._view.page().setBackgroundColor(QColor("#202020"))
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)
        self._ready = False
        self._variant = "classic"
        self._show_hint = True
        self._skin_data = _image_data_url(skin or _default_skin())
        self._cape_data = ""
        self._view.loadFinished.connect(self._on_loaded)
        self._view.load(
            QUrl.fromLocalFile(str(_asset_root() / "skinview3d" / "viewer.html"))
        )
        self.setMinimumSize(420, 360)

    def _on_loaded(self, ok: bool) -> None:
        if not ok:
            return
        self._ready = True
        self._sync()

    def _run(self, script: str) -> None:
        if self._ready:
            self._view.page().runJavaScript(script)

    def _sync(self) -> None:
        self._run(
            "window.fionixSkin.setSkin("
            f"{_js_string(self._skin_data)}, {_js_string(self._variant)});"
        )
        self._run(
            "window.fionixSkin.setCape("
            f"{_js_string(self._cape_data) if self._cape_data else 'null'});"
        )
        self._run(
            f"window.fionixSkin.setHint({'true' if self._show_hint else 'false'});"
        )

    def set_skin(self, skin: QImage | None) -> None:
        self._skin_data = _image_data_url(skin or _default_skin())
        self._run(
            "window.fionixSkin.setSkin("
            f"{_js_string(self._skin_data)}, {_js_string(self._variant)});"
        )

    def set_cape(self, cape: QImage | None, url: str = "") -> None:
        self._cape_data = _image_data_url(cape) if cape is not None else ""
        value = _js_string(self._cape_data) if self._cape_data else "null"
        self._run(f"window.fionixSkin.setCape({value});")

    def set_variant(self, variant: str) -> None:
        self._variant = "slim" if variant == "slim" else "classic"
        self._run(f"window.fionixSkin.setModel({_js_string(self._variant)});")

    @property
    def variant(self) -> str:
        return self._variant

    def set_show_hint(self, visible: bool) -> None:
        self._show_hint = visible
        self._run(f"window.fionixSkin.setHint({'true' if visible else 'false'});")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._view.stop()
        self._view.setParent(None)
        self._view.deleteLater()
        super().closeEvent(event)


class Skin3DView(QWidget):
    """Public 3D view: skinview3d in the desktop app, software offscreen."""

    def __init__(self, skin: QImage | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._impl: QWidget
        self._available = True
        try:
            self._impl = _WebSkin3DView(skin, self)
        except Exception:
            self._available = False
            self._impl = QLabel("3D-просмотр недоступен: не удалось запустить WebGL.")
            self._impl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._impl)
        self.setMinimumSize(420, 360)

    def set_skin(self, skin: QImage | None) -> None:
        if self._available:
            self._impl.set_skin(skin)  # type: ignore[attr-defined]

    def set_cape(self, cape: QImage | None, url: str = "") -> None:
        if self._available:
            self._impl.set_cape(cape, url)  # type: ignore[attr-defined]

    def set_variant(self, variant: str) -> None:
        if self._available:
            self._impl.set_variant(variant)  # type: ignore[attr-defined]

    def set_show_hint(self, visible: bool) -> None:
        if self._available:
            self._impl.set_show_hint(visible)  # type: ignore[attr-defined]

    @property
    def variant(self) -> str:
        return self._impl.variant if self._available else "classic"  # type: ignore[attr-defined]


class SkinViewerDialog(QDialog):
    def __init__(self, parent: QWidget, skin: QImage | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("3D-скин Fionix")
        self.setMinimumSize(720, 650)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        title = QLabel("3D-просмотр скина")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(title)
        self.view = Skin3DView(skin)
        layout.addWidget(self.view, 1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
