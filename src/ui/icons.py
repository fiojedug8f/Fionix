"""Hand-drawn vector icon set.

Fionix does not depend on an icon font or external SVG files: icons are drawn
with QPainter on a 24x24 grid.  That keeps them perfectly crisp, theme-aware
and trivial to recolor at paint time.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

GRID = 24.0


def _pen(painter: QPainter, color: QColor, width: float) -> None:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _fill(painter: QPainter, color: QColor) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)


def _line(painter: QPainter, x1: float, y1: float, x2: float, y2: float) -> None:
    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _arc_path(x: float, y: float, w: float, h: float, start: float, sweep: float) -> QPainterPath:
    path = QPainterPath()
    rect = QRectF(x, y, w, h)
    path.arcMoveTo(rect, start)
    path.arcTo(rect, start, sweep)
    return path


def draw_icon(
    painter: QPainter,
    name: str,
    rect: QRectF,
    color: QColor,
    stroke: float = 1.75,
) -> None:
    """Draw ``name`` into ``rect`` with a 24-unit design grid."""
    if rect.width() <= 0 or rect.height() <= 0:
        return

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scale = min(rect.width(), rect.height()) / GRID
    painter.translate(
        rect.left() + (rect.width() - GRID * scale) / 2,
        rect.top() + (rect.height() - GRID * scale) / 2,
    )
    painter.scale(scale, scale)
    _pen(painter, color, stroke)

    if name == "home":
        path = QPainterPath()
        path.moveTo(3.5, 10.6)
        path.lineTo(12, 3.6)
        path.lineTo(20.5, 10.6)
        path.moveTo(5.8, 9.2)
        path.lineTo(5.8, 20.2)
        path.lineTo(18.2, 20.2)
        path.lineTo(18.2, 9.2)
        path.moveTo(10.0, 20.2)
        path.lineTo(10.0, 14.4)
        path.lineTo(14.0, 14.4)
        path.lineTo(14.0, 20.2)
        painter.drawPath(path)

    elif name == "store":
        path = QPainterPath()
        path.moveTo(4.6, 8.4)
        path.lineTo(19.4, 8.4)
        path.lineTo(18.2, 20.2)
        path.lineTo(5.8, 20.2)
        path.closeSubpath()
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(8.8, 8.4)
        path.lineTo(8.8, 6.6)
        path.cubicTo(8.8, 3.9, 10.2, 3.0, 12.0, 3.0)
        path.cubicTo(13.8, 3.0, 15.2, 3.9, 15.2, 6.6)
        path.lineTo(15.2, 8.4)
        painter.drawPath(path)

    elif name == "settings":
        _line(painter, 3.8, 7.0, 20.2, 7.0)
        _line(painter, 3.8, 12.0, 20.2, 12.0)
        _line(painter, 3.8, 17.0, 20.2, 17.0)
        for x, y in ((8.8, 7.0), (15.4, 12.0), (6.6, 17.0)):
            _fill(painter, color)
            painter.drawEllipse(QPointF(x, y), 2.0, 2.0)

    elif name == "music":
        path = QPainterPath()
        path.moveTo(9.4, 18.0)
        path.lineTo(9.4, 6.8)
        path.lineTo(19.2, 4.4)
        path.lineTo(19.2, 15.4)
        painter.drawPath(path)
        _fill(painter, color)
        painter.drawEllipse(QPointF(7.1, 18.0), 2.3, 2.3)
        painter.drawEllipse(QPointF(16.9, 15.4), 2.3, 2.3)

    elif name == "minimize":
        _line(painter, 5.0, 12.0, 19.0, 12.0)

    elif name == "maximize":
        painter.drawRoundedRect(QRectF(5.5, 5.5, 13.0, 13.0), 2.0, 2.0)

    elif name == "restore":
        path = QPainterPath()
        path.moveTo(8.4, 8.4)
        path.lineTo(8.4, 5.0)
        path.lineTo(19.0, 5.0)
        path.lineTo(19.0, 15.6)
        path.lineTo(15.6, 15.6)
        painter.drawPath(path)
        painter.drawRoundedRect(QRectF(5.0, 8.4, 10.6, 10.6), 2.0, 2.0)

    elif name == "close":
        _line(painter, 6.0, 6.0, 18.0, 18.0)
        _line(painter, 18.0, 6.0, 6.0, 18.0)

    elif name == "plus":
        _line(painter, 12.0, 5.0, 12.0, 19.0)
        _line(painter, 5.0, 12.0, 19.0, 12.0)

    elif name == "minus":
        _line(painter, 5.5, 12.0, 18.5, 12.0)

    elif name == "user":
        painter.drawEllipse(QPointF(12.0, 8.2), 3.6, 3.6)
        path = QPainterPath()
        path.moveTo(4.6, 20.4)
        path.cubicTo(4.8, 16.3, 7.8, 14.0, 12.0, 14.0)
        path.cubicTo(16.2, 14.0, 19.2, 16.3, 19.4, 20.4)
        painter.drawPath(path)

    elif name == "forge":
        path = QPainterPath()
        path.moveTo(4.2, 6.8)
        path.lineTo(19.8, 6.8)
        path.lineTo(18.4, 11.0)
        path.lineTo(13.8, 11.0)
        path.lineTo(13.8, 14.0)
        path.lineTo(17.0, 16.0)
        path.lineTo(17.0, 19.2)
        path.lineTo(7.0, 19.2)
        path.lineTo(7.0, 16.0)
        path.lineTo(10.2, 14.0)
        path.lineTo(10.2, 11.0)
        path.lineTo(5.6, 11.0)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "neoforge":
        path = QPainterPath()
        path.moveTo(12.0, 2.8)
        path.lineTo(20.4, 7.6)
        path.lineTo(20.4, 16.4)
        path.lineTo(12.0, 21.2)
        path.lineTo(3.6, 16.4)
        path.lineTo(3.6, 7.6)
        path.closeSubpath()
        painter.drawPath(path)
        _line(painter, 8.0, 16.0, 8.0, 9.0)
        _line(painter, 8.0, 9.0, 15.8, 16.0)
        _line(painter, 15.8, 16.0, 15.8, 9.0)

    elif name == "quilt":
        painter.drawRoundedRect(QRectF(3.2, 3.2, 8.0, 8.0), 1.6, 1.6)
        painter.drawRoundedRect(QRectF(12.8, 3.2, 8.0, 8.0), 1.6, 1.6)
        painter.drawRoundedRect(QRectF(3.2, 12.8, 8.0, 8.0), 1.6, 1.6)
        painter.drawRoundedRect(QRectF(12.8, 12.8, 8.0, 8.0), 1.6, 1.6)
        _line(painter, 7.2, 7.2, 16.8, 16.8)

    elif name == "fabric":
        painter.drawEllipse(QPointF(18.0, 5.2), 2.2, 2.2)
        _line(painter, 16.5, 6.7, 8.8, 14.4)
        path = QPainterPath()
        path.moveTo(8.8, 14.4)
        path.cubicTo(4.0, 16.2, 8.5, 20.8, 3.6, 20.0)
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(15.0, 3.6)
        path.cubicTo(20.8, 2.2, 22.0, 8.0, 18.0, 10.0)
        painter.drawPath(path)

    elif name == "optifine":
        path = QPainterPath()
        path.moveTo(2.6, 12.0)
        path.cubicTo(6.4, 6.2, 17.6, 6.2, 21.4, 12.0)
        path.cubicTo(17.6, 17.8, 6.4, 17.8, 2.6, 12.0)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawEllipse(QPointF(12.0, 12.0), 3.3, 3.3)
        _fill(painter, color)
        painter.drawEllipse(QPointF(13.2, 10.8), 0.8, 0.8)
        _pen(painter, color, stroke)
        path = QPainterPath()
        path.moveTo(18.6, 3.4)
        path.lineTo(19.1, 5.0)
        path.lineTo(20.7, 5.5)
        path.lineTo(19.1, 6.0)
        path.lineTo(18.6, 7.6)
        path.lineTo(18.1, 6.0)
        path.lineTo(16.5, 5.5)
        path.lineTo(18.1, 5.0)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "puzzle":
        path = QPainterPath()
        path.moveTo(4.0, 8.0)
        path.lineTo(8.4, 8.0)
        path.cubicTo(7.4, 5.6, 9.0, 3.6, 11.2, 3.6)
        path.cubicTo(13.4, 3.6, 15.0, 5.6, 14.0, 8.0)
        path.lineTo(18.0, 8.0)
        path.lineTo(18.0, 12.0)
        path.cubicTo(20.4, 11.0, 22.4, 12.6, 22.4, 14.8)
        path.cubicTo(22.4, 17.0, 20.4, 18.6, 18.0, 17.6)
        path.lineTo(18.0, 20.4)
        path.lineTo(4.0, 20.4)
        path.lineTo(4.0, 17.2)
        path.cubicTo(6.4, 18.2, 8.4, 16.6, 8.4, 14.4)
        path.cubicTo(8.4, 12.2, 6.4, 10.6, 4.0, 11.6)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "shader":
        painter.drawEllipse(QPointF(12.0, 12.0), 3.6, 3.6)
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            x1 = 12 + math.cos(radians) * 6.7
            y1 = 12 + math.sin(radians) * 6.7
            x2 = 12 + math.cos(radians) * 9.4
            y2 = 12 + math.sin(radians) * 9.4
            _line(painter, x1, y1, x2, y2)

    elif name == "map":
        path = QPainterPath()
        path.moveTo(3.0, 6.0)
        path.lineTo(9.0, 3.8)
        path.lineTo(15.0, 6.0)
        path.lineTo(21.0, 3.8)
        path.lineTo(21.0, 18.0)
        path.lineTo(15.0, 20.2)
        path.lineTo(9.0, 18.0)
        path.lineTo(3.0, 20.2)
        path.closeSubpath()
        path.moveTo(9.0, 3.8)
        path.lineTo(9.0, 18.0)
        path.moveTo(15.0, 6.0)
        path.lineTo(15.0, 20.2)
        painter.drawPath(path)

    elif name == "archive":
        painter.drawRoundedRect(QRectF(4.0, 4.0, 16.0, 4.2), 1.2, 1.2)
        path = QPainterPath()
        path.moveTo(5.4, 8.2)
        path.lineTo(6.2, 20.2)
        path.lineTo(17.8, 20.2)
        path.lineTo(18.6, 8.2)
        painter.drawPath(path)
        _line(painter, 12.0, 11.0, 12.0, 17.5)
        _line(painter, 10.4, 13.0, 13.6, 13.0)
        _line(painter, 10.4, 15.4, 13.6, 15.4)

    elif name == "search":
        painter.drawEllipse(QPointF(10.6, 10.6), 6.6, 6.6)
        _line(painter, 15.5, 15.5, 20.6, 20.6)

    elif name == "cube":
        path = QPainterPath()
        path.moveTo(12.0, 3.2)
        path.lineTo(20.4, 7.8)
        path.lineTo(12.0, 12.4)
        path.lineTo(3.6, 7.8)
        path.closeSubpath()
        path.moveTo(3.6, 7.8)
        path.lineTo(3.6, 16.2)
        path.lineTo(12.0, 20.8)
        path.lineTo(12.0, 12.4)
        path.moveTo(20.4, 7.8)
        path.lineTo(20.4, 16.2)
        path.lineTo(12.0, 20.8)
        painter.drawPath(path)

    elif name == "moon":
        path = QPainterPath()
        path.moveTo(19.6, 15.0)
        path.cubicTo(13.8, 16.4, 8.2, 12.0, 9.4, 5.2)
        path.cubicTo(5.4, 7.0, 3.2, 10.4, 4.2, 14.1)
        path.cubicTo(5.3, 18.4, 10.2, 21.0, 14.4, 19.7)
        path.cubicTo(16.6, 19.0, 18.4, 17.3, 19.6, 15.0)
        path.closeSubpath()
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(15.2, 5.0)
        path.lineTo(15.8, 7.0)
        path.lineTo(17.8, 7.6)
        path.lineTo(15.8, 8.2)
        path.lineTo(15.2, 10.2)
        path.lineTo(14.6, 8.2)
        path.lineTo(12.6, 7.6)
        path.lineTo(14.6, 7.0)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "memory":
        painter.drawRoundedRect(QRectF(6.0, 6.0, 12.0, 12.0), 2.0, 2.0)
        painter.drawRoundedRect(QRectF(9.4, 9.4, 5.2, 5.2), 0.8, 0.8)
        for offset in (8.4, 12.0, 15.6):
            _line(painter, offset, 3.0, offset, 6.0)
            _line(painter, offset, 18.0, offset, 21.0)
            _line(painter, 3.0, offset, 6.0, offset)
            _line(painter, 18.0, offset, 21.0, offset)

    elif name == "java":
        path = QPainterPath()
        path.moveTo(5.8, 10.0)
        path.lineTo(16.6, 10.0)
        path.lineTo(16.6, 13.8)
        path.cubicTo(16.6, 17.2, 14.4, 19.6, 11.2, 19.6)
        path.cubicTo(8.0, 19.6, 5.8, 17.2, 5.8, 13.8)
        path.closeSubpath()
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(16.6, 11.4)
        path.lineTo(18.3, 11.4)
        path.cubicTo(20.0, 11.4, 20.7, 12.6, 20.5, 14.0)
        path.cubicTo(20.3, 15.4, 19.2, 16.2, 17.8, 16.2)
        path.lineTo(16.6, 16.2)
        painter.drawPath(path)
        for x, y1, y2 in ((8.6, 3.6, 7.2), (12.0, 3.0, 6.8), (15.2, 3.6, 7.2)):
            path = QPainterPath()
            path.moveTo(x, y1)
            path.cubicTo(x - 1.2, (y1 + y2) / 2, x + 1.2, (y1 + y2) / 2, x, y2)
            painter.drawPath(path)
        _line(painter, 4.0, 21.2, 19.6, 21.2)

    elif name == "globe":
        painter.drawEllipse(QPointF(12.0, 12.0), 8.2, 8.2)
        painter.drawEllipse(QPointF(12.0, 12.0), 3.8, 8.2)
        _line(painter, 4.0, 9.0, 20.0, 9.0)
        _line(painter, 4.0, 15.0, 20.0, 15.0)

    elif name == "folder":
        path = QPainterPath()
        path.moveTo(3.4, 6.6)
        path.cubicTo(3.4, 5.6, 4.2, 4.8, 5.2, 4.8)
        path.lineTo(9.2, 4.8)
        path.lineTo(11.2, 7.0)
        path.lineTo(18.8, 7.0)
        path.cubicTo(19.8, 7.0, 20.6, 7.8, 20.6, 8.8)
        path.lineTo(20.6, 17.4)
        path.cubicTo(20.6, 18.4, 19.8, 19.2, 18.8, 19.2)
        path.lineTo(5.2, 19.2)
        path.cubicTo(4.2, 19.2, 3.4, 18.4, 3.4, 17.4)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "check":
        path = QPainterPath()
        path.moveTo(5.0, 12.4)
        path.lineTo(9.8, 17.0)
        path.lineTo(19.2, 7.0)
        painter.drawPath(path)

    elif name == "loop":
        path = QPainterPath()
        path.moveTo(7.0, 6.0)
        path.cubicTo(13.0, 2.5, 20.5, 6.0, 20.0, 12.0)
        path.cubicTo(19.8, 15.0, 18.0, 17.0, 15.0, 17.5)
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(9.0, 6.0)
        path.lineTo(6.4, 3.4)
        path.moveTo(9.0, 6.0)
        path.lineTo(6.4, 8.6)
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(17.0, 18.0)
        path.cubicTo(11.0, 21.5, 3.5, 18.0, 4.0, 12.0)
        path.cubicTo(4.2, 9.0, 6.0, 7.0, 9.0, 6.5)
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(15.0, 18.0)
        path.lineTo(17.6, 20.6)
        path.moveTo(15.0, 18.0)
        path.lineTo(17.6, 15.4)
        painter.drawPath(path)

    elif name == "windows":
        for x, y in ((4, 4), (13, 4), (4, 13), (13, 13)):
            painter.drawRoundedRect(QRectF(x, y, 7, 7), 1.2, 1.2)

    elif name == "share":
        path = QPainterPath()
        path.moveTo(12.0, 3.0)
        path.lineTo(12.0, 15.0)
        path.moveTo(7.0, 8.0)
        path.lineTo(12.0, 3.0)
        path.lineTo(17.0, 8.0)
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(5.0, 12.0)
        path.lineTo(5.0, 20.0)
        path.lineTo(19.0, 20.0)
        path.lineTo(19.0, 12.0)
        painter.drawPath(path)

    elif name == "video":
        painter.drawRoundedRect(QRectF(3.0, 5.0, 13.0, 14.0), 2.0, 2.0)
        path = QPainterPath()
        path.moveTo(16.0, 9.0)
        path.lineTo(21.0, 6.5)
        path.lineTo(21.0, 17.5)
        path.lineTo(16.0, 15.0)
        painter.drawPath(path)

    elif name == "sparkle":
        _fill(painter, color)
        for cx, cy, size in ((12.0, 8.4, 5.6), (6.4, 16.0, 3.0), (17.6, 16.6, 2.4)):
            points = []
            for i in range(8):
                angle = math.pi / 2 * (i / 2)
                radius = size if i % 2 == 0 else size * 0.2
                points.append(
                    QPointF(
                        cx + math.cos(angle) * radius,
                        cy + math.sin(angle) * radius,
                    )
                )
            painter.drawPolygon(points)

    elif name == "lock":
        painter.drawRoundedRect(QRectF(5.0, 10.4, 14.0, 10.2), 2.4, 2.4)
        path = QPainterPath()
        path.moveTo(8.0, 10.4)
        path.lineTo(8.0, 7.8)
        path.cubicTo(8.0, 4.4, 9.8, 3.2, 12.0, 3.2)
        path.cubicTo(14.2, 3.2, 16.0, 4.4, 16.0, 7.8)
        path.lineTo(16.0, 10.4)
        painter.drawPath(path)
        _fill(painter, color)
        painter.drawEllipse(QPointF(12.0, 15.4), 1.2, 1.2)

    elif name == "play":
        _fill(painter, color)
        path = QPainterPath()
        path.moveTo(8.0, 5.2)
        path.lineTo(19.2, 12.0)
        path.lineTo(8.0, 18.8)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "pause":
        _fill(painter, color)
        painter.drawRoundedRect(QRectF(6.8, 5.2, 3.8, 13.6), 1.2, 1.2)
        painter.drawRoundedRect(QRectF(13.4, 5.2, 3.8, 13.6), 1.2, 1.2)

    elif name == "prev":
        _fill(painter, color)
        path = QPainterPath()
        path.moveTo(18.4, 5.6)
        path.lineTo(9.2, 12.0)
        path.lineTo(18.4, 18.4)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawRoundedRect(QRectF(5.0, 5.6, 2.2, 12.8), 1.0, 1.0)

    elif name == "next":
        _fill(painter, color)
        path = QPainterPath()
        path.moveTo(5.6, 5.6)
        path.lineTo(14.8, 12.0)
        path.lineTo(5.6, 18.4)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawRoundedRect(QRectF(16.8, 5.6, 2.2, 12.8), 1.0, 1.0)

    elif name == "volume":
        _fill(painter, color)
        path = QPainterPath()
        path.moveTo(4.0, 9.4)
        path.lineTo(7.4, 9.4)
        path.lineTo(12.2, 5.2)
        path.lineTo(12.2, 18.8)
        path.lineTo(7.4, 14.6)
        path.lineTo(4.0, 14.6)
        path.closeSubpath()
        painter.drawPath(path)
        _pen(painter, color, stroke)
        painter.drawPath(_arc_path(10.6, 7.4, 7.4, 9.2, -55, 110))
        painter.drawPath(_arc_path(10.6, 4.6, 12.4, 14.8, -48, 96))

    elif name == "chevron_down":
        path = QPainterPath()
        path.moveTo(6.6, 9.4)
        path.lineTo(12.0, 14.8)
        path.lineTo(17.4, 9.4)
        painter.drawPath(path)

    elif name == "chevron_right":
        path = QPainterPath()
        path.moveTo(9.4, 6.6)
        path.lineTo(14.8, 12.0)
        path.lineTo(9.4, 17.4)
        painter.drawPath(path)

    elif name == "chevron_left":
        path = QPainterPath()
        path.moveTo(14.6, 6.6)
        path.lineTo(9.2, 12.0)
        path.lineTo(14.6, 17.4)
        painter.drawPath(path)

    elif name == "clock":
        painter.drawEllipse(QPointF(12.0, 12.0), 8.4, 8.4)
        path = QPainterPath()
        path.moveTo(12.0, 6.8)
        path.lineTo(12.0, 12.2)
        path.lineTo(15.7, 14.2)
        painter.drawPath(path)

    elif name == "external":
        path = QPainterPath()
        path.moveTo(13.2, 4.6)
        path.lineTo(19.4, 4.6)
        path.lineTo(19.4, 10.8)
        path.moveTo(19.4, 4.6)
        path.lineTo(10.8, 13.2)
        path.moveTo(16.4, 13.6)
        path.lineTo(16.4, 18.2)
        path.cubicTo(16.4, 18.9, 15.9, 19.4, 15.2, 19.4)
        path.lineTo(5.8, 19.4)
        path.cubicTo(5.1, 19.4, 4.6, 18.9, 4.6, 18.2)
        path.lineTo(4.6, 8.8)
        path.cubicTo(4.6, 8.1, 5.1, 7.6, 5.8, 7.6)
        path.lineTo(10.4, 7.6)
        painter.drawPath(path)

    elif name == "reset":
        path = QPainterPath()
        path.moveTo(5.4, 10.0)
        path.cubicTo(6.3, 6.1, 9.8, 3.6, 13.8, 4.2)
        path.cubicTo(17.8, 4.8, 20.6, 8.4, 20.1, 12.4)
        path.cubicTo(19.6, 16.4, 16.0, 19.2, 12.0, 18.8)
        path.cubicTo(8.9, 18.5, 6.4, 16.6, 5.2, 14.0)
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(5.0, 5.2)
        path.lineTo(5.6, 10.4)
        path.lineTo(10.8, 9.8)
        painter.drawPath(path)

    elif name == "info":
        painter.drawEllipse(QPointF(12.0, 12.0), 8.4, 8.4)
        _fill(painter, color)
        painter.drawEllipse(QPointF(12.0, 7.8), 1.1, 1.1)
        _pen(painter, color, stroke)
        _line(painter, 12.0, 11.0, 12.0, 16.6)

    elif name == "shield":
        path = QPainterPath()
        path.moveTo(12.0, 3.2)
        path.cubicTo(14.4, 4.8, 16.8, 5.4, 19.2, 5.7)
        path.lineTo(19.2, 11.8)
        path.cubicTo(19.2, 16.0, 16.2, 19.2, 12.0, 20.8)
        path.cubicTo(7.8, 19.2, 4.8, 16.0, 4.8, 11.8)
        path.lineTo(4.8, 5.7)
        path.cubicTo(7.2, 5.4, 9.6, 4.8, 12.0, 3.2)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "image":
        painter.drawRoundedRect(QRectF(3.8, 4.8, 16.4, 14.4), 2.4, 2.4)
        _fill(painter, color)
        painter.drawEllipse(QPointF(8.6, 9.2), 1.5, 1.5)
        _pen(painter, color, stroke)
        path = QPainterPath()
        path.moveTo(4.8, 17.4)
        path.lineTo(9.6, 12.4)
        path.lineTo(12.8, 15.4)
        path.lineTo(15.8, 12.2)
        path.lineTo(19.2, 15.6)
        painter.drawPath(path)

    elif name == "download":
        _line(painter, 12.0, 3.8, 12.0, 15.0)
        path = QPainterPath()
        path.moveTo(7.0, 10.4)
        path.lineTo(12.0, 15.4)
        path.lineTo(17.0, 10.4)
        painter.drawPath(path)
        path = QPainterPath()
        path.moveTo(4.6, 16.6)
        path.lineTo(4.6, 18.4)
        path.cubicTo(4.6, 19.4, 5.4, 20.2, 6.4, 20.2)
        path.lineTo(17.6, 20.2)
        path.cubicTo(18.6, 20.2, 19.4, 19.4, 19.4, 18.4)
        path.lineTo(19.4, 16.6)
        painter.drawPath(path)

    else:  # graceful fallback: a dot
        _fill(painter, color)
        painter.drawEllipse(QPointF(12.0, 12.0), 2.4, 2.4)

    painter.restore()


def pixmap(
    name: str,
    size: int,
    color: QColor,
    *,
    stroke: float = 1.75,
    device_pixel_ratio: float = 1.0,
) -> QPixmap:
    """Rasterise an icon (with HiDPI support) for use in labels and buttons."""
    px_size = max(1, int(round(size * device_pixel_ratio)))
    canvas = QPixmap(px_size, px_size)
    canvas.fill(Qt.GlobalColor.transparent)
    canvas.setDevicePixelRatio(device_pixel_ratio)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw_icon(
            painter,
            name,
            QRectF(0, 0, size, size),
            color,
            stroke,
        )
    finally:
        painter.end()
    return canvas


def icon(name: str, color: QColor) -> QIcon:
    """QIcon assembled from several sizes for crisp window/tray usage."""
    result = QIcon()
    for size in (16, 20, 24, 32, 48):
        result.addPixmap(pixmap(name, size, color, device_pixel_ratio=2.0))
    return result
