"""Custom frameless title bar with drag support and window controls."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from src.core.theme import current_theme
from src.ui.widgets import CapsLabel, IconButton, MusicButton, WindowButton


class StatusDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        glow = QColor(theme.success)
        glow.setAlpha(50)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(0, 0, 12, 12))
        painter.setBrush(theme.success)
        painter.drawEllipse(QRectF(3.5, 3.5, 5, 5))


class TitleBar(QWidget):
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()
    music_requested = Signal()
    downloads_requested = Signal()
    update_requested = Signal()

    HEIGHT = 62

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("TitleBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(26, 0, 10, 0)
        layout.setSpacing(0)

        status = QWidget()
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(2)
        status_layout.addWidget(StatusDot())
        status_layout.addWidget(CapsLabel("FIONIX  ·  READY", size=9, spacing=1.5, muted=True))
        layout.addWidget(status)

        layout.addStretch(1)
        self.update_button = QPushButton("Доступно обновление")
        self.update_button.setObjectName("UpdatePill")
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button.hide()
        self.update_button.clicked.connect(self.update_requested.emit)
        layout.addWidget(self.update_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(10)

        self.downloads_button = IconButton(
            "download", size=(32, 32), icon_size=15, radius=10, tooltip="Загрузки"
        )
        self.downloads_button.clicked.connect(self.downloads_requested.emit)
        layout.addWidget(self.downloads_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(8)
        self.music_button = MusicButton()
        self.music_button.clicked.connect(self.music_requested.emit)
        layout.addWidget(self.music_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(12)

        separator = QFrame()
        separator.setObjectName("TitleBarSeparator")
        separator.setFixedSize(1, 20)
        separator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(separator, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(8)

        self.minimize_button = WindowButton("minimize", "РЎРІРµСЂРЅСѓС‚СЊ")
        self.maximize_button = WindowButton("maximize", "Р Р°Р·РІРµСЂРЅСѓС‚СЊ")
        self.close_button = WindowButton("close", "Р—Р°РєСЂС‹С‚СЊ", danger=True)
        self.minimize_button.clicked.connect(self.minimize_requested.emit)
        self.maximize_button.clicked.connect(self.maximize_requested.emit)
        self.close_button.clicked.connect(self.close_requested.emit)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

        self._transparent_children(status, separator)

    @staticmethod
    def _transparent_children(*widgets: QWidget) -> None:
        for widget in widgets:
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # ---------------------------------------------------------------- state
    def set_update_available(self, version: str, _url: str = "") -> None:
        label = version.lstrip("v") if version else ""
        self.update_button.setText(
            f"Доступно обновление {label}" if label else "Доступно обновление"
        )
        self.update_button.show()

    def clear_update(self) -> None:
        self.update_button.hide()

    def set_maximized(self, maximized: bool) -> None:
        self.maximize_button.set_icon_name("restore" if maximized else "maximize")
        self.maximize_button.setToolTip("Р’РѕСЃСЃС‚Р°РЅРѕРІРёС‚СЊ" if maximized else "Р Р°Р·РІРµСЂРЅСѓС‚СЊ")
        self.maximize_button.setAccessibleName(self.maximize_button.toolTip())

    # --------------------------------------------------------------- events
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            if window.isMaximized():
                self._drag_offset = None
            else:
                self._drag_offset = event.globalPosition().toPoint() - window.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            window = self.window()
            if not window.isMaximized():
                window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

