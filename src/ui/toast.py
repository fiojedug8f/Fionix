"""Non-blocking Fluent toast notifications."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class Toast(QFrame):
    closed = Signal(object)

    COLORS = {
        "error": ("#3A1D24", "#FF879A"),
        "success": ("#173528", "#59D99A"),
        "info": ("#243247", "#75B9FF"),
    }

    def __init__(self, parent: QWidget, title: str, message: str, kind: str = "info") -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(340)
        background, accent = self.COLORS.get(kind, self.COLORS["info"])
        self.setStyleSheet(
            f"QFrame#Toast {{ background-color: {background}; "
            f"border: 1px solid {accent}; border-radius: 10px; }}"
            f"QLabel {{ color: #F5F5F5; background: transparent; }}"
            f"QPushButton {{ color: {accent}; background: transparent; border: none; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(3)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title or ("Ошибка" if kind == "error" else "Готово"))
        label.setStyleSheet(f"font-weight: 600; color: {accent};")
        top.addWidget(label, 1)
        close = QPushButton("×")
        close.setFixedSize(20, 20)
        close.clicked.connect(self.dismiss)
        top.addWidget(close)
        layout.addLayout(top)
        body = QLabel(message)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self.adjustSize()

    def show_at(self, x: int, y: int) -> None:
        self.move(x + 24, y)
        self.show()
        self.raise_()
        animation = QPropertyAnimation(self._effect, b"opacity", self)
        animation.setDuration(180)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(self._slide_in)
        self._opacity_animation = animation
        animation.start()
        self._timer.start(3600)

    def _slide_in(self) -> None:
        animation = QPropertyAnimation(self, b"pos", self)
        animation.setDuration(180)
        animation.setStartValue(QPoint(self.x() + 20, self.y()))
        animation.setEndValue(QPoint(self.x() - 20, self.y()))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pos_animation = animation
        animation.start()

    def dismiss(self) -> None:
        self._timer.stop()
        animation = QPropertyAnimation(self._effect, b"opacity", self)
        animation.setDuration(140)
        animation.setStartValue(self._effect.opacity())
        animation.setEndValue(0.0)
        animation.finished.connect(self._finish)
        self._close_animation = animation
        animation.start()

    def _finish(self) -> None:
        self.closed.emit(self)
        self.hide()
        self.deleteLater()


class ToastManager:
    def __init__(self, window: QWidget) -> None:
        self.window = window
        self.items: list[Toast] = []

    def show(self, title: str, message: str, kind: str = "info") -> None:
        toast = Toast(self.window, title, message, kind)
        toast.closed.connect(self._remove)
        self.items.append(toast)
        self._reflow()
        for item in self.items:
            if item is toast:
                item.show_at(self._x(), self._y())
                break

    def _remove(self, toast: Toast) -> None:
        if toast in self.items:
            self.items.remove(toast)
        self._reflow()

    def _x(self) -> int:
        return max(12, self.window.width() - 356)

    def _y(self) -> int:
        return 64 + sum(item.height() + 8 for item in self.items[:-1])

    def _reflow(self) -> None:
        y = 64
        for item in self.items:
            item.move(self._x(), y)
            y += item.height() + 8
