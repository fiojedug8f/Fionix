"""Software-rendered 3D Minecraft skin viewer.

It intentionally uses a small QPainter 3D pipeline instead of requiring an
OpenGL binary on end-user machines.  Cuboids are transformed, depth-sorted and
shaded per frame; both the base skin and the translucent outer layer are drawn,
and the arms/legs follow a smooth walking cycle.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.core.theme import current_theme


def _average(image: QImage, rect: tuple[int, int, int, int], fallback: QColor) -> QColor:
    if image.isNull():
        return fallback
    x, y, w, h = rect
    if x < 0 or y < 0 or x + w > image.width() or y + h > image.height():
        return fallback
    region = image.copy(x, y, w, h).scaled(
        1, 1, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    color = QColor(region.pixel(0, 0))
    if color.alpha() == 0:
        return fallback
    return color


# Classic 64×64 Minecraft skin UV atlas.  Face order:
# front, back, left, right, top, bottom.
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


class Skin3DView(QWidget):
    def __init__(self, skin: QImage | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._skin = skin if skin is not None and not skin.isNull() else _default_skin()
        self._yaw = 22.0
        self._pitch = -4.0
        self._zoom = 1.0
        self._phase = 0.0
        self._drag: QPoint | None = None
        self._show_hint = True
        self.setMinimumSize(560, 480)
        self.setMouseTracking(True)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._colors = self._sample_colors(self._skin)

    def set_show_hint(self, visible: bool) -> None:
        self._show_hint = visible
        self.update()

    def set_skin(self, skin: QImage | None) -> None:
        self._skin = skin if skin is not None and not skin.isNull() else _default_skin()
        self._colors = self._sample_colors(self._skin)
        self.update()

    @staticmethod
    def _sample_colors(image: QImage) -> dict[str, QColor]:
        fallbacks = {
            "head": QColor("#C89B76"),
            "hat": QColor("#8B5E3B"),
            "body": QColor("#2C6C9E"),
            "jacket": QColor("#1C4F78"),
            "right_arm": QColor("#C89B76"),
            "left_arm": QColor("#C89B76"),
            "right_sleeve": QColor("#2C6C9E"),
            "left_sleeve": QColor("#2C6C9E"),
            "right_leg": QColor("#394B87"),
            "left_leg": QColor("#394B87"),
            "right_pants": QColor("#273466"),
            "left_pants": QColor("#273466"),
        }
        regions = {
            "head": (8, 8, 8, 8),
            "hat": (40, 8, 8, 8),
            "body": (20, 20, 8, 12),
            "jacket": (20, 36, 8, 12),
            "right_arm": (44, 20, 4, 12),
            "left_arm": (36, 52, 4, 12),
            "right_sleeve": (44, 36, 4, 12),
            "left_sleeve": (52, 52, 4, 12),
            "right_leg": (4, 20, 4, 12),
            "left_leg": (20, 52, 4, 12),
            "right_pants": (4, 36, 4, 12),
            "left_pants": (4, 52, 4, 12),
        }
        return {
            key: _average(image, region, fallbacks[key])
            for key, region in regions.items()
        }

    def _tick(self) -> None:
        self._phase += 0.09
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag is not None:
            delta = event.position().toPoint() - self._drag
            self._yaw += delta.x() * 0.6
            self._pitch = max(-35.0, min(35.0, self._pitch + delta.y() * 0.3))
            self._drag = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._zoom = max(0.55, min(2.4, self._zoom + (0.08 if event.angleDelta().y() > 0 else -0.08)))
        self.update()
        event.accept()

    def _transform(self, points: list[tuple[float, float, float]], pivot, angle: float):
        yaw = math.radians(self._yaw)
        pitch = math.radians(self._pitch)
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        angle_rad = math.radians(angle)
        ca, sa = math.cos(angle_rad), math.sin(angle_rad)
        px, py, pz = pivot
        out = []
        distance = 88.0
        focal = 650.0
        for x, y, z in points:
            x -= px
            y -= py
            z -= pz
            if angle_rad:
                y, z = y * ca - z * sa, y * sa + z * ca
            x += px
            y += py
            z += pz
            x, z = x * cy - z * sy, x * sy + z * cy
            y, z = y * cp - z * sp, y * sp + z * cp
            denominator = max(24.0, distance + z)
            factor = focal / denominator * self._zoom
            out.append(
                (
                    self.width() / 2 + x * factor,
                    self.height() / 2 - (y - 15) * factor,
                    z,
                    factor,
                )
            )
        return out

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setPen(QColor(255, 255, 255, 22))
        for x in range(0, self.width(), 36):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 36):
            painter.drawLine(0, y, self.width(), y)
        painter.setPen(QColor(255, 255, 255, 30))
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawEllipse(
            self.width() / 2 - 95,
            self.height() - 88,
            190,
            28,
        )

        swing = math.sin(self._phase) * 29.0
        parts = [
            ("head", (0, 28, 0), (8, 8, 8), (0, 24, 0), 0.0, 1.0),
            ("hat", (0, 28, 0), (9.2, 9.2, 9.2), (0, 24, 0), 0.0, 0.42),
            ("body", (0, 17, 0), (8, 12, 4), (0, 23, 0), 0.0, 1.0),
            ("jacket", (0, 17, 0), (9.2, 13.2, 5.2), (0, 23, 0), 0.0, 0.42),
            ("right_arm", (6, 17, 0), (4, 12, 4), (6, 23, 0), swing, 1.0),
            ("right_sleeve", (6, 17, 0), (5.2, 13.2, 5.2), (6, 23, 0), swing, 0.42),
            ("left_arm", (-6, 17, 0), (4, 12, 4), (-6, 23, 0), -swing, 1.0),
            ("left_sleeve", (-6, 17, 0), (5.2, 13.2, 5.2), (-6, 23, 0), -swing, 0.42),
            ("right_leg", (2, 5, 0), (4, 12, 4), (2, 11, 0), -swing * 0.8, 1.0),
            ("right_pants", (2, 5, 0), (5.2, 13.2, 5.2), (2, 11, 0), -swing * 0.8, 0.42),
            ("left_leg", (-2, 5, 0), (4, 12, 4), (-2, 11, 0), swing * 0.8, 1.0),
            ("left_pants", (-2, 5, 0), (5.2, 13.2, 5.2), (-2, 11, 0), swing * 0.8, 0.42),
        ]
        faces = []
        for key, center, size, pivot, angle, alpha_scale in parts:
            cx, cy, cz = center
            sx, sy, sz = (size[0] / 2, size[1] / 2, size[2] / 2)
            points = [
                (cx - sx, cy - sy, cz - sz),
                (cx + sx, cy - sy, cz - sz),
                (cx + sx, cy + sy, cz - sz),
                (cx - sx, cy + sy, cz - sz),
                (cx - sx, cy - sy, cz + sz),
                (cx + sx, cy - sy, cz + sz),
                (cx + sx, cy + sy, cz + sz),
                (cx - sx, cy + sy, cz + sz),
            ]
            transformed = self._transform(points, pivot, angle)
            for face in (
                (0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
                (2, 3, 7, 6), (1, 2, 6, 5), (0, 3, 7, 4),
            ):
                polygon = [transformed[index] for index in face]
                depth = sum(point[2] for point in polygon) / 4
                base = self._colors.get(key, QColor("#999999"))
                # Simple directional lighting keeps the cuboids readable.
                shade = 1.0 if face in ((4, 5, 6, 7), (0, 1, 5, 4)) else 0.86
                color = QColor(
                    max(0, min(255, int(base.red() * shade))),
                    max(0, min(255, int(base.green() * shade))),
                    max(0, min(255, int(base.blue() * shade))),
                    int(235 * alpha_scale),
                )
                side = {
                    # Camera looks at the -Z side, so this is the skin front.
                    (0, 1, 2, 3): "front",
                    (4, 5, 6, 7): "back",
                    (0, 1, 5, 4): "bottom",
                    (2, 3, 7, 6): "top",
                    (1, 2, 6, 5): "left",
                    (0, 3, 7, 4): "right",
                }[face]
                legacy_key = key
                if self._skin.height() == 32:
                    # 64×32 skins mirror the left limbs from the right ones.
                    legacy_key = {
                        "left_arm": "right_arm",
                        "left_sleeve": "right_sleeve",
                        "left_leg": "right_leg",
                        "left_pants": "right_pants",
                    }.get(key, key)
                uv = SKIN_UV.get(legacy_key, {}).get(side)
                faces.append((depth, polygon, color, alpha_scale, uv))
        faces.sort(key=lambda item: item[0], reverse=True)
        for _depth, polygon, color, alpha_scale, uv in faces:
            screen = QPolygonF(
                [QPointF(p[0], p[1]) for p in polygon]
            )
            textured = False
            if uv is not None and not self._skin.isNull():
                x, y, w, h = uv
                if x + w <= self._skin.width() and y + h <= self._skin.height():
                    # Skin atlases are stored top-down while the cuboid face
                    # vertices start at the lower edge; this order keeps the
                    # face upright instead of mirroring it vertically.
                    texture = QPolygonF(
                        [
                            QPointF(x, y + h),
                            QPointF(x + w, y + h),
                            QPointF(x + w, y),
                            QPointF(x, y),
                        ]
                    )
                    transform = QTransform()
                    if QTransform.quadToQuad(texture, screen, transform):
                        painter.save()
                        painter.setTransform(transform)
                        painter.setClipRect(QRectF(x, y, w, h))
                        painter.setOpacity(1.0 if alpha_scale >= 1.0 else 0.72)
                        painter.drawImage(0, 0, self._skin)
                        painter.restore()
                        textured = True
            if not textured:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawPolygon(screen)
            pen_color = (
                QColor(255, 255, 255, 100)
                if alpha_scale < 1.0
                else QColor(255, 255, 255, 30)
            )
            painter.setPen(QPen(pen_color, 0.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(screen)
        if self._show_hint:
            painter.setPen(theme.text_muted)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(
                self.rect().adjusted(0, 14, 0, 0),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                "Базовый слой + внешний слой · перетащите для вращения · колесо — масштаб",
            )


class SkinViewerDialog(QDialog):
    def __init__(self, parent: QWidget, skin: QImage | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("3D-скин Fionix")
        self.setMinimumSize(720, 650)
        self.setStyleSheet(
            "QDialog { background-color: #0B0A12; } QLabel { color: #F5F3FF; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        title = QLabel("3D-просмотр скина")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(title)
        hint = QLabel(
            "Два слоя скина: базовый и внешний. Анимация ходьбы включена; "
            "нажмите и перетащите модель, чтобы осмотреть её."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #B9B4CE;")
        layout.addWidget(hint)
        self.view = Skin3DView(skin)
        layout.addWidget(self.view, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close = QPushButton("Закрыть")
        close.setObjectName("GhostButton")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)
