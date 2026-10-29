"""Static, pre-rendered Minecraft skin preview.

The launcher no longer runs a realtime 3D scene for skins.  Every skin is
rendered **once per viewing angle** with QPainter -- the 64x64 skin atlas is
mapped onto the six faces of each body box and projected with a plain
orthographic camera -- and the UI only swaps ready-made images.

There is no WebGL, no QtWebEngine and no per-frame work, so the preview can not
lag: opening the profile costs one render (~10 ms), every other angle is
cached.

Angles (all pre-rendered, "8 views" of the spec plus the 45-degree steps used
while rotating):

    front, 3/4 front, left, 3/4 back, back, 3/4 back-right, right,
    3/4 front-right, top, bottom
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.theme import current_theme

logger = logging.getLogger(__name__)

ATLAS_SIZE = 64

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
    image = QImage(ATLAS_SIZE, ATLAS_SIZE, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    for part, faces in SKIN_UV.items():
        for x, y, w, h in faces.values():
            painter.fillRect(QRect(x, y, w, h), _DEFAULT_COLORS[part])
    painter.end()
    return image


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Box:
    """One body part: axis-aligned box in Minecraft units (feet at y=0)."""

    part: str
    center: tuple[float, float, float]
    size: tuple[float, float, float]


# The character faces +Z.  In a right-handed frame (x right, y up, z forward)
# the model's own right hand is at -X, so:
#   camera at +X  -> we see the LEFT side
#   camera at -X  -> we see the RIGHT side
# That mapping is what the Влево/Вправо buttons rely on.
_BASE_PARTS: tuple[_Box, ...] = (
    _Box("right_leg", (-2.0, 6.0, 0.0), (4.0, 12.0, 4.0)),
    _Box("left_leg", (2.0, 6.0, 0.0), (4.0, 12.0, 4.0)),
    _Box("right_arm", (-6.0, 18.0, 0.0), (4.0, 12.0, 4.0)),
    _Box("left_arm", (6.0, 18.0, 0.0), (4.0, 12.0, 4.0)),
    _Box("body", (0.0, 18.0, 0.0), (8.0, 12.0, 4.0)),
    _Box("head", (0.0, 28.0, 0.0), (8.0, 8.0, 8.0)),
)

_SLIM_PARTS: tuple[_Box, ...] = (
    _Box("right_leg", (-2.0, 6.0, 0.0), (4.0, 12.0, 4.0)),
    _Box("left_leg", (2.0, 6.0, 0.0), (4.0, 12.0, 4.0)),
    _Box("right_arm", (-5.5, 18.0, 0.0), (3.0, 12.0, 4.0)),
    _Box("left_arm", (5.5, 18.0, 0.0), (3.0, 12.0, 4.0)),
    _Box("body", (0.0, 18.0, 0.0), (8.0, 12.0, 4.0)),
    _Box("head", (0.0, 28.0, 0.0), (8.0, 8.0, 8.0)),
)


def _overlay_parts(slim: bool) -> tuple[_Box, ...]:
    arm = 3.6 if slim else 4.6
    arm_x = 5.5 if slim else 6.0
    return (
        _Box("right_pants", (-2.0, 6.0, 0.0), (4.6, 12.4, 4.6)),
        _Box("left_pants", (2.0, 6.0, 0.0), (4.6, 12.4, 4.6)),
        _Box("right_sleeve", (-arm_x, 18.0, 0.0), (arm, 12.4, 4.6)),
        _Box("left_sleeve", (arm_x, 18.0, 0.0), (arm, 12.4, 4.6)),
        _Box("jacket", (0.0, 18.0, 0.0), (8.6, 12.4, 4.6)),
        _Box("hat", (0.0, 28.0, 0.0), (8.6, 8.6, 8.6)),
    )


# key, normal, texture +u direction, texture +v direction (world space)
_FACES: tuple[tuple[str, tuple[float, float, float],
                    tuple[float, float, float], tuple[float, float, float]], ...] = (
    ("front", (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    ("back", (0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    ("left", (1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, -1.0, 0.0)),
    ("right", (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
    ("top", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    ("bottom", (0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),
)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalize(v):
    length = math.sqrt(_dot(v, v)) or 1.0
    return (v[0] / length, v[1] / length, v[2] / length)


def _camera(yaw_deg: float, pitch_deg: float):
    """Orthographic camera: (to_camera, forward, right, up)."""
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    to_camera = (
        math.sin(yaw) * math.cos(pitch),
        math.sin(pitch),
        math.cos(yaw) * math.cos(pitch),
    )
    forward = (-to_camera[0], -to_camera[1], -to_camera[2])
    up_hint = (0.0, 1.0, 0.0)
    if abs(forward[1]) > 0.95:
        up_hint = (0.0, 0.0, -1.0)
    right = _normalize(_cross(forward, up_hint))
    up = _normalize(_cross(right, forward))
    return to_camera, forward, right, up


def _affine_transform(
    uv: tuple[int, int, int, int], p0: QPointF, p1: QPointF, p3: QPointF
) -> QTransform | None:
    """Affine map from the texture rect onto the projected quad.

    The camera is orthographic, so the texture->screen mapping is affine; that
    keeps the code exact and avoids a projective solve.
    """
    u0, v0, w, h = uv
    if w <= 0 or h <= 0:
        return None
    ux = (p1.x() - p0.x()) / w
    uy = (p1.y() - p0.y()) / w
    vx = (p3.x() - p0.x()) / h
    vy = (p3.y() - p0.y()) / h
    # QTransform: x' = m11*x + m21*y + dx ; y' = m12*x + m22*y + dy
    m11, m12 = ux, uy
    m21, m22 = vx, vy
    dx = p0.x() - (m11 * u0 + m21 * v0)
    dy = p0.y() - (m12 * u0 + m22 * v0)
    return QTransform(m11, m12, m21, m22, dx, dy)


def _cape_uv(cape: QImage) -> tuple[int, int, int, int]:
    """UV-блок плаща — ровно как в модели, а не «с нуля».

    Плащ в игре — это бокс 10x16x1, и его лицевая грань (+Z) в стандартной
    развёртке box-UV начинается со смещения на глубину: (1, 1)-(11, 17).
    Если брать (0, 0)-(10, 16), вся картинка уезжает на 1 тексель влево/вверх —
    именно это выглядело как «плащ смещён на пару пикселей».
    """
    width, height = cape.width(), cape.height()
    if width <= 0 or height <= 0:
        return (0, 0, 0, 0)
    # Отдельный файл, который сам имеет форму плаща: масштаб не нужен.
    if abs(width / float(height) - 10.0 / 16.0) <= 0.12:
        return (0, 0, width, height)
    # Масштаб текстуры — как в skinview3d: 22x17 (легаси), 64x32, 46x22.
    if 17 * width == 22 * height:
        scale = width / 22.0
    elif 11 * width == 23 * height:
        scale = width / 46.0
    else:
        scale = width / 64.0
    unit = max(1, int(round(scale)))
    block_w = max(1, int(round(10 * scale)))
    block_h = max(1, int(round(16 * scale)))
    offset_x = min(unit, max(0, width - block_w))
    offset_y = min(unit, max(0, height - block_h))
    return (offset_x, offset_y, block_w, block_h)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

# yaw ring: 8 stops of 45 degrees (0 = front).  Cardinal sides are even
# indices; the odd ones are the 3/4 views used as rotation steps.
YAW_RING: tuple[float, ...] = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)

VIEW_LABELS: dict[int, str] = {
    0: "Спереди",
    1: "3/4 спереди",
    2: "Слева",
    3: "3/4 сзади",
    4: "Сзади",
    5: "3/4 сзади",
    6: "Справа",
    7: "3/4 спереди",
}
TOP_LABEL = "Сверху"
BOTTOM_LABEL = "Снизу"


class SkinRenderer:
    """Renders the skin atlas into a few static orthographic views."""

    def __init__(self) -> None:
        self._skin = _default_skin()
        self._cape: QImage | None = None
        self._slim = False
        self._cache: dict[tuple, QImage] = {}

    # -- inputs ---------------------------------------------------------
    def set_skin(self, skin: QImage | None) -> None:
        self._skin = skin if skin is not None and not skin.isNull() else _default_skin()
        self._cache.clear()

    def set_cape(self, cape: QImage | None) -> None:
        self._cape = cape if cape is not None and not cape.isNull() else None
        self._cache.clear()

    def set_slim(self, slim: bool) -> None:
        if slim != self._slim:
            self._slim = slim
            self._cache.clear()

    # -- rendering ------------------------------------------------------
    def image(self, key: tuple, size: QSize) -> QImage:
        cached = self._cache.get(key)
        if cached is not None and cached.size() == size:
            return cached
        yaw, pitch = self._angles_for(key)
        image = self._render(yaw, pitch, size)
        self._cache[key] = image
        return image

    @staticmethod
    def _angles_for(key: tuple) -> tuple[float, float]:
        if key[0] == "top":
            return 0.0, 68.0
        if key[0] == "bottom":
            return 0.0, -68.0
        return YAW_RING[int(key[1])], 0.0

    def _render(self, yaw: float, pitch: float, size: QSize) -> QImage:
        width = max(64, int(size.width()))
        height = max(64, int(size.height()))
        canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QPainter(canvas)
        # Deliberately *no* SmoothPixmapTransform: a 64x64 skin must be sampled
        # with nearest-neighbour, otherwise every face turns into a blurry mess.
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
        )
        self._paint_backdrop(painter, width, height)

        to_camera, forward, right, up = _camera(yaw, pitch)
        light = _normalize(
            (
                to_camera[0] * 0.55,
                to_camera[1] * 0.55 + 0.75,
                to_camera[2] * 0.55,
            )
        )

        parts = list(_SLIM_PARTS if self._slim else _BASE_PARTS)
        parts += list(_overlay_parts(self._slim))

        faces: list[tuple[float, list[QPointF], tuple[int, int, int, int], float]] = []
        for box in parts:
            for face_key, normal, u_dir, v_dir in _FACES:
                if _dot(normal, to_camera) <= 0.001:
                    continue
                uv = SKIN_UV.get(box.part, {}).get(face_key)
                if uv is None:
                    continue
                quad = self._face_quad(box, normal, u_dir, v_dir)
                projected = [self._project(p, right, up, forward) for p in quad]
                depth = sum(p[2] for p in projected) / 4.0
                shade = 0.62 + 0.38 * max(0.0, _dot(normal, light))
                faces.append((depth, projected, uv, shade, self._skin))

        if self._cape is not None:
            for item in self._cape_faces(right, up, forward, to_camera, light):
                faces.append(item)

        # Grid: fixed scale keeps the model the same size in every view; the
        # fit scale only shrinks it when the view would not fit.
        scale = min(width * 0.92 / 22.0, height * 0.90 / 34.0)
        xs = [p[0] for face in faces for p in face[1]]
        ys = [p[1] for face in faces for p in face[1]]
        if xs and ys:
            span_x = max(xs) - min(xs) or 1.0
            span_y = max(ys) - min(ys) or 1.0
            scale = min(scale, (width * 0.88) / span_x, (height * 0.88) / span_y)
        # Minecraft textures are pixel art: one texel is exactly one model unit,
        # so an integer scale maps every texel to a whole number of pixels and
        # the preview stays sharp instead of being resampled into mush.
        scale = max(1.0, float(int(scale)))
        if xs and ys:
            offset_x = round(width / 2.0 - (min(xs) + max(xs)) / 2.0 * scale)
            offset_y = round(height / 2.0 - (min(ys) + max(ys)) / 2.0 * scale)
        else:
            offset_x = round(width / 2.0)
            offset_y = round(height / 2.0)

        faces.sort(key=lambda item: item[0], reverse=True)  # far -> near
        for _depth, quad, uv, shade, texture in faces:
            points = [
                QPointF(p[0] * scale + offset_x, p[1] * scale + offset_y)
                for p in quad
            ]
            self._draw_face(painter, points, uv, shade, texture)

        painter.end()
        return canvas

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _face_quad(box: _Box, normal, u_dir, v_dir) -> list[tuple]:
        cx, cy, cz = box.center
        sx, sy, sz = box.size
        half = (
            sx / 2.0 if abs(normal[0]) > 0.5 else sz / 2.0,
            sy / 2.0 if abs(normal[1]) > 0.5 else sz / 2.0,
            sz / 2.0 if abs(normal[2]) > 0.5 else sz / 2.0,
        )
        # Extents along the face's own axes.
        extent_u = abs(u_dir[0]) * sx + abs(u_dir[1]) * sy + abs(u_dir[2]) * sz
        extent_v = abs(v_dir[0]) * sx + abs(v_dir[1]) * sy + abs(v_dir[2]) * sz
        center = (
            cx + normal[0] * half[0],
            cy + normal[1] * half[1],
            cz + normal[2] * half[2],
        )
        hu = extent_u / 2.0
        hv = extent_v / 2.0
        corners = []
        for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            corners.append(
                (
                    center[0] + u_dir[0] * hu * du + v_dir[0] * hv * dv,
                    center[1] + u_dir[1] * hu * du + v_dir[1] * hv * dv,
                    center[2] + u_dir[2] * hu * du + v_dir[2] * hv * dv,
                )
            )
        return corners

    @staticmethod
    def _project(point, right, up, forward):
        return (
            _dot(point, right),
            -_dot(point, up),
            _dot(point, forward),
        )

    def _cape_faces(self, right, up, forward, to_camera, light):
        """The cape quad plus the *cape* texture as its source.

        A cape is a separate image (64x32 with the cape at 0,0 10x16, or a
        22x17 legacy image).  It must be drawn with its own texture -- drawing
        it with the skin atlas was the bug that painted the skin over the cape.
        """
        cape = self._cape
        if cape is None:
            return []
        normal = (0.0, 0.0, -1.0)
        if _dot(normal, to_camera) <= 0.001:      # только со стороны спины
            return []
        width = 10.0
        top_y = 24.0
        bottom_y = 8.0
        # В игре плащ висит под углом: верх прижат к спине, низ отходит назад.
        z_top = -2.05
        z_bottom = -3.4
        # Камера сзади смотрит вдоль +Z, её screen-right = -X, поэтому текстура
        # (u0 -> левый край картинки) должна попадать на +X, иначе плащ зеркалится.
        corners = [
            (width / 2, top_y, z_top),           # uv (u0, v0)
            (-width / 2, top_y, z_top),          # uv (u1, v0)
            (-width / 2, bottom_y, z_bottom),    # uv (u1, v1)
            (width / 2, bottom_y, z_bottom),     # uv (u0, v1)
        ]
        projected = [self._project(p, right, up, forward) for p in corners]
        depth = sum(p[2] for p in projected) / 4.0
        uv = _cape_uv(cape)
        shade = 0.62 + 0.38 * max(0.0, _dot(normal, light))
        return [(depth, projected, uv, shade, cape)]

    @staticmethod
    def _draw_face(painter, points, uv, shade, texture):
        u0, v0, w, h = uv
        transform = _affine_transform(uv, points[0], points[1], points[3])
        if transform is None:
            return
        painter.save()
        painter.setTransform(transform)
        painter.drawImage(
            QRectF(u0, v0, w, h), texture, QRectF(u0, v0, w, h)
        )
        painter.restore()
        if shade < 0.995:
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, int((1.0 - shade) * 190)))
            painter.drawPolygon(QPolygonF(points))
            painter.restore()

    @staticmethod
    def _paint_backdrop(painter, width, height) -> None:
        theme = current_theme()
        base = QColor(theme.panel_solid)
        top = QColor(base).lighter(128)
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, base)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), 14, 14)
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.drawPath(path)


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class SkinPreview(QLabel):
    """Shows one pre-rendered angle; renders on demand, never per frame."""

    def __init__(self, skin: QImage | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SkinPreview")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(260, 260)
        self.renderer = SkinRenderer()
        self.renderer.set_skin(skin)
        self._index = 0            # position on YAW_RING
        self._pitch = "level"      # level | top | bottom
        self._remembered = 0
        self._pending: QTimer | None = None

    # -- state -----------------------------------------------------------
    @property
    def view_index(self) -> int:
        return self._index

    def view_label(self) -> str:
        if self._pitch == "top":
            return TOP_LABEL
        if self._pitch == "bottom":
            return BOTTOM_LABEL
        return VIEW_LABELS.get(self._index, "Спереди")

    def _key(self) -> tuple:
        if self._pitch in ("top", "bottom"):
            return (self._pitch,)
        return ("yaw", self._index)

    # -- public API ------------------------------------------------------
    def set_skin(self, skin: QImage | None) -> None:
        self.renderer.set_skin(skin)
        self._refresh()

    def set_cape(self, cape: QImage | None) -> None:
        self.renderer.set_cape(cape)
        self._refresh()

    def set_variant(self, variant: str) -> None:
        self.renderer.set_slim(variant == "slim")
        self._refresh()

    def rotate_left(self) -> None:
        if self._pitch != "level":
            self._pitch = "level"
        self._step(+1)

    def rotate_right(self) -> None:
        if self._pitch != "level":
            self._pitch = "level"
        self._step(-1)

    def look_up(self) -> None:
        if self._pitch == "top":
            self._pitch = "level"
            self._index = self._remembered
        else:
            self._remembered = self._index
            self._pitch = "top"
        self._refresh()

    def look_down(self) -> None:
        if self._pitch == "bottom":
            self._pitch = "level"
            self._index = self._remembered
        else:
            self._remembered = self._index
            self._pitch = "bottom"
        self._refresh()

    def set_yaw(self, degrees: float) -> None:
        """Legacy API: jump to the closest pre-rendered angle."""
        normalized = degrees % 360.0
        self._pitch = "level"
        self._index = min(
            range(len(YAW_RING)),
            key=lambda i: min(
                abs(YAW_RING[i] - normalized),
                360.0 - abs(YAW_RING[i] - normalized),
            ),
        )
        self._refresh()

    # -- rendering -------------------------------------------------------
    def _step(self, direction: int) -> None:
        """Rotate by one cardinal side, showing the 3/4 frame on the way."""
        target = (self._index + direction * 2) % len(YAW_RING)
        middle = (self._index + direction) % len(YAW_RING)
        self._cancel_pending()
        self._index = middle
        self._refresh()
        self._pending = QTimer(self)
        self._pending.setSingleShot(True)
        self._pending.setInterval(90)
        self._pending.timeout.connect(lambda: self._finish_step(target))
        self._pending.start()

    def _finish_step(self, target: int) -> None:
        self._pending = None
        self._index = target
        self._refresh()

    def _cancel_pending(self) -> None:
        if self._pending is not None:
            self._pending.stop()
            self._pending = None

    def _refresh(self) -> None:
        image = self.renderer.image(self._key(), self._render_size())
        if image.isNull():
            return
        self._image = image
        pixmap = QPixmap.fromImage(image)
        # The image is already rendered at device resolution; telling Qt the
        # ratio makes the label blit it 1:1 instead of resampling it again.
        pixmap.setDevicePixelRatio(self._device_scale())
        self.setPixmap(pixmap)

    def _device_scale(self) -> float:
        window = self.window()
        if window is None:
            return 1.0
        return float(window.devicePixelRatioF() or 1.0)

    def _render_size(self) -> QSize:
        scale = self._device_scale()
        width = max(160, int(self.width() * scale))
        height = max(160, int(self.height() * scale))
        return QSize(width, height)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._refresh()


class Skin3DView(QWidget):
    """Pre-rendered skin preview with left/right/up/down controls.

    Kept the old class name and public API so existing call sites keep working.
    """

    def __init__(self, skin: QImage | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._available = True
        self._cape_url = ""
        self._yaw = 0.0
        self.preview = SkinPreview(skin, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.preview, 1)

        controls = QHBoxLayout()
        controls.setContentsMargins(8, 0, 8, 4)
        controls.setSpacing(6)
        self._left_button = QPushButton("◀")
        self._right_button = QPushButton("▶")
        self._up_button = QPushButton("▲")
        self._down_button = QPushButton("▼")
        self._reset_button = QPushButton("Сброс")
        for button in (
            self._left_button,
            self._right_button,
            self._up_button,
            self._down_button,
            self._reset_button,
        ):
            button.setObjectName("ViewerNavButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(28)
        self._left_button.setToolTip("Повернуть влево (левый бок)")
        self._right_button.setToolTip("Повернуть вправо (правый бок)")
        self._up_button.setToolTip("Вид сверху")
        self._down_button.setToolTip("Вид снизу")
        self._reset_button.setToolTip("Вернуться к виду спереди")

        self._left_button.clicked.connect(self._rotate_left)
        self._right_button.clicked.connect(self._rotate_right)
        self._up_button.clicked.connect(self._look_up)
        self._down_button.clicked.connect(self._look_down)
        self._reset_button.clicked.connect(lambda: self._set_yaw(0))

        controls.addWidget(self._left_button)
        controls.addWidget(self._right_button)
        controls.addStretch(1)
        self.view_label = QLabel("Спереди")
        self.view_label.setObjectName("Caption")
        self.view_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.addWidget(self.view_label)
        controls.addStretch(1)
        controls.addWidget(self._up_button)
        controls.addWidget(self._down_button)
        controls.addWidget(self._reset_button)
        layout.addLayout(controls)

        self.hint_label = QLabel("Готовые ракурсы — без рендера в реальном времени")
        self.hint_label.setObjectName("Caption")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint_label)
        self.setMinimumSize(420, 360)

    # -- controls --------------------------------------------------------
    def _rotate_left(self) -> None:
        self.preview.rotate_left()
        self._sync_label()

    def _rotate_right(self) -> None:
        self.preview.rotate_right()
        self._sync_label()

    def _look_up(self) -> None:
        self.preview.look_up()
        self._sync_label()

    def _look_down(self) -> None:
        self.preview.look_down()
        self._sync_label()

    def _set_yaw(self, degrees: float) -> None:
        self._yaw = degrees % 360
        self.preview.set_yaw(self._yaw)
        self._sync_label()

    def _sync_label(self) -> None:
        self.view_label.setText(self.preview.view_label())
        self._yaw = YAW_RING[self.preview.view_index]

    # -- public API ------------------------------------------------------
    def set_skin(self, skin: QImage | None) -> None:
        self.preview.set_skin(skin)
        self._sync_label()

    def set_cape(self, cape: QImage | None, url: str = "") -> None:
        self._cape_url = url if cape is not None else ""
        self.preview.set_cape(cape)

    def set_variant(self, variant: str) -> None:
        self.preview.set_variant(variant)
        self._sync_label()

    def set_show_hint(self, visible: bool) -> None:
        self.hint_label.setVisible(bool(visible))

    def set_yaw(self, degrees: float) -> None:
        self._set_yaw(degrees)

    @property
    def variant(self) -> str:
        return "slim" if self.preview.renderer._slim else "classic"

    @property
    def cape_url(self) -> str:
        return self._cape_url


class SkinViewerDialog(QDialog):
    def __init__(self, parent: QWidget, skin: QImage | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Скин Fionix")
        self.setMinimumSize(720, 650)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        title = QLabel("Просмотр скина")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        self.view = Skin3DView(skin)
        layout.addWidget(self.view, 1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
