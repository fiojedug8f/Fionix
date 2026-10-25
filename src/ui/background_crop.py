"""Interactive cover-cropper for static launcher backgrounds."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.ui.launch_dialogs import OverlayDialog


class CropPreview(QWidget):
    """Cover-fit preview: drag to pan, wheel/slider to zoom."""

    changed = Signal()

    def __init__(self, image: QImage, target_aspect: float = 16 / 9, parent=None) -> None:
        super().__init__(parent)
        self._image = image
        self._aspect = max(0.5, min(3.5, target_aspect))
        self._zoom = 1.0
        self._offset = QPointF(0, 0)
        self._drag_origin: QPointF | None = None
        self._drag_offset = QPointF(0, 0)
        self.setMinimumSize(560, 315)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(700, int(700 / self._aspect))

    def set_aspect(self, aspect: float) -> None:
        self._aspect = max(0.5, min(3.5, float(aspect)))
        self._clamp_offset()
        self.update()

    def set_zoom(self, value: float) -> None:
        self._zoom = max(1.0, min(4.0, float(value)))
        self._clamp_offset()
        self.update()
        self.changed.emit()

    def _base_scale(self) -> float:
        if self._image.isNull() or self.height() <= 0:
            return 1.0
        return max(
            self.width() / self._image.width(),
            self.height() / self._image.height(),
        )

    def _clamp_offset(self) -> None:
        if self._image.isNull():
            return
        scale = self._base_scale() * self._zoom
        max_x = max(0.0, (self._image.width() * scale - self.width()) / 2)
        max_y = max(0.0, (self._image.height() * scale - self.height()) / 2)
        self._offset.setX(max(-max_x, min(max_x, self._offset.x())))
        self._offset.setY(max(-max_y, min(max_y, self._offset.y())))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#0A0910"))
        if self._image.isNull():
            painter.setPen(QColor("#B9B4CE"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Не удалось открыть изображение")
            return
        scale = self._base_scale() * self._zoom
        width = self._image.width() * scale
        height = self._image.height() * scale
        x = (self.width() - width) / 2 + self._offset.x()
        y = (self.height() - height) / 2 + self._offset.y()
        painter.drawImage(QRectF(x, y, width, height), self._image)
        painter.setPen(QColor(255, 255, 255, 40))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position()
            self._drag_offset = QPointF(self._offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag_origin is not None:
            delta = event.position() - self._drag_origin
            self._offset = self._drag_offset + delta
            self._clamp_offset()
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._drag_origin = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.changed.emit()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        delta = 0.12 if event.angleDelta().y() > 0 else -0.12
        self.set_zoom(self._zoom + delta)
        event.accept()

    def cropped_image(self, target_width: int = 1920) -> QImage:
        if self._image.isNull():
            return QImage()
        scale = self._base_scale() * self._zoom
        if scale <= 0:
            return QImage()
        visible_w = self.width() / scale
        visible_h = self.height() / scale
        center_x = self._image.width() / 2 - self._offset.x() / scale
        center_y = self._image.height() / 2 - self._offset.y() / scale
        left = max(0.0, min(self._image.width() - visible_w, center_x - visible_w / 2))
        top = max(0.0, min(self._image.height() - visible_h, center_y - visible_h / 2))
        rect = QRectF(left, top, visible_w, visible_h)
        cropped = self._image.copy(rect.toRect())
        return cropped.scaledToWidth(
            max(640, int(target_width)), Qt.TransformationMode.SmoothTransformation
        )


class BackgroundCropDialog(OverlayDialog):
    def __init__(
        self,
        parent: QWidget,
        image: QImage,
        *,
        target_size: QSize | None = None,
    ) -> None:
        super().__init__(parent, card_width=780)
        self._image = image
        aspect = 16 / 9
        if target_size is not None and target_size.width() > 0 and target_size.height() > 0:
            aspect = target_size.width() / target_size.height()
        layout = self.card_layout
        layout.addWidget(QLabel("Кадрирование фона"))
        title = layout.itemAt(layout.count() - 1).widget()
        title.setObjectName("DialogTitle")
        layout.addSpacing(5)
        hint = QLabel(
            "Перетаскивайте изображение мышью и меняйте масштаб, чтобы заполнить окно. "
            "Светлые и тёмные области сохранятся после применения."
        )
        hint.setObjectName("PageSubtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(12)
        self.preview = CropPreview(image, aspect)
        self.preview.setFixedSize(620, max(300, min(400, int(620 / aspect))))
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        zoom_row = QHBoxLayout()
        zoom_row.setContentsMargins(0, 8, 0, 0)
        zoom_label = QLabel("Масштаб")
        zoom_label.setObjectName("Caption")
        zoom_row.addWidget(zoom_label)
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(100, 400)
        self.zoom.setValue(100)
        self.zoom.valueChanged.connect(lambda value: self.preview.set_zoom(value / 100))
        zoom_row.addWidget(self.zoom, 1)
        layout.addLayout(zoom_row)
        layout.addSpacing(12)
        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setObjectName("GhostButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        apply = QPushButton("Применить")
        apply.setObjectName("SoftButton")
        apply.setCursor(Qt.CursorShape.PointingHandCursor)
        apply.clicked.connect(self.accept)
        footer.addWidget(apply)
        layout.addLayout(footer)

    def cropped_image(self) -> QImage:
        target_width = max(1920, min(3840, self._image.width() or 1920))
        return self.preview.cropped_image(target_width)
