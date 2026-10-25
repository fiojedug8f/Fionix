"""Reusable glassmorphism widgets and animated controls."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPointF,
    Property,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.app_paths import asset_path
from src.core.theme import FONT_FAMILY, current_theme
from src.ui import icons


def blend(first: QColor, second: QColor, amount: float) -> QColor:
    """Linear colour blend (``amount`` 0..1, clamped)."""
    amount = max(0.0, min(1.0, amount))
    return QColor(
        int(first.red() * (1 - amount) + second.red() * amount),
        int(first.green() * (1 - amount) + second.green() * amount),
        int(first.blue() * (1 - amount) + second.blue() * amount),
        int(first.alpha() * (1 - amount) + second.alpha() * amount),
    )


def with_alpha(color: QColor, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(max(0, min(255, alpha)))
    return result


def font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    value = QFont(FONT_FAMILY)
    value.setPixelSize(size)
    value.setWeight(weight)
    value.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return value


class HoverButton(QAbstractButton):
    """Base class with a smooth, paint-friendly hover animation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hover = 0.0
        self._hover_animation = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_animation.setDuration(170)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()
        self._on_hover_changed()

    def _on_hover_changed(self) -> None:
        """Hook for subclasses that animate something beside the painting."""

    hoverProgress = Property(float, _get_hover, _set_hover)

    def _animate_hover(self, target: float) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.isEnabled():
            self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.EnabledChange:
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if self.isEnabled()
                else Qt.CursorShape.ArrowCursor
            )
        super().changeEvent(event)


class PrimaryButton(HoverButton):
    """Flat Fluent accent action with a restrained hover state."""

    def __init__(
        self,
        text: str,
        icon_name: str = "plus",
        parent: QWidget | None = None,
        *,
        height: int = 54,
    ) -> None:
        super().__init__(parent)
        self.setText(text)
        self._icon_name = icon_name
        self.setFixedHeight(height)
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(text)

        self._shadow = None

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self.update()

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(font(15, QFont.Weight.DemiBold))
        return QSize(max(280, metrics.horizontalAdvance(self.text()) + 108), self.height())

    def _sync_shadow(self) -> None:
        # Fluent buttons are flat; no QGraphicsDropShadowEffect is kept.
        self._shadow = None

    def refresh_theme(self) -> None:
        self._sync_shadow()
        self.update()

    def _on_hover_changed(self) -> None:
        self._sync_shadow()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pressed = self.isDown()
        rect = QRectF(self.rect()).adjusted(2.0, 2.0, -2.0, -3.0)
        if pressed:
            rect.translate(0, 1)

        radius = 8.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        if pressed:
            fill = QColor(theme.accent_2)
        elif self._hover > 0.5:
            fill = QColor(theme.accent_light)
        else:
            fill = QColor(theme.accent)
        painter.fillPath(path, fill)
        painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        if self.hasFocus():
            painter.setPen(QPen(with_alpha(theme.accent_light, 190), 2))
            focus_rect = rect.adjusted(3, 3, -3, -3)
            painter.drawRoundedRect(focus_rect, radius - 3, radius - 3)

        # Icon + label composition, optically centred.
        text_font = font(15, QFont.Weight.DemiBold)
        painter.setFont(text_font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(self.text())
        icon_size = 19.0
        gap = 11.0
        total = icon_size + gap + text_width
        start_x = rect.center().x() - total / 2
        center_y = rect.center().y()

        base_color = QColor("#FFFFFF") if self.isEnabled() else QColor(255, 255, 255, 130)
        icon_rect = QRectF(start_x, center_y - icon_size / 2, icon_size, icon_size)
        icons.draw_icon(painter, self._icon_name, icon_rect, base_color, 2.1)

        painter.setPen(base_color)
        text_rect = QRectF(
            start_x + icon_size + gap,
            rect.top(),
            text_width + 2,
            rect.height(),
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )

        if not self.isEnabled():
            painter.fillPath(path, QColor(5, 5, 10, 90))


class IconButton(HoverButton):
    """A compact icon button used in the title bar and toolbars."""

    def __init__(
        self,
        icon_name: str,
        parent: QWidget | None = None,
        *,
        size: tuple[int, int] = (36, 36),
        icon_size: int = 18,
        radius: float = 10.0,
        tooltip: str = "",
        danger: bool = False,
        bordered: bool = False,
        accent_hover: bool = False,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_size = icon_size
        self._radius = radius
        self._danger = danger
        self._bordered = bordered
        self._accent_hover = accent_hover
        self.setFixedSize(*size)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if tooltip:
            self.setToolTip(tooltip)
            self.setAccessibleName(tooltip)

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        hovered = self._hover
        checked = self.isCheckable() and self.isChecked()
        if checked:
            background = with_alpha(theme.accent, 36)
            border = with_alpha(theme.accent, 80)
        elif self._danger and hovered > 0.01:
            background = with_alpha(theme.danger, int(38 * hovered))
            border = with_alpha(theme.danger, int(70 * hovered))
        elif self._accent_hover and hovered > 0.01:
            background = with_alpha(theme.accent, int(36 * hovered))
            border = with_alpha(theme.accent, int(70 * hovered))
        else:
            base_alpha = 10 if self._bordered else 0
            background = with_alpha(QColor(255, 255, 255), int(base_alpha + 26 * hovered))
            border = with_alpha(QColor(255, 255, 255), int((22 if self._bordered else 0) + 28 * hovered))

        if self.isDown():
            background = with_alpha(QColor(255, 255, 255), 42)

        if background.alpha() > 0 or self._bordered:
            painter.setPen(QPen(border, 1) if border.alpha() > 0 else Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(rect, self._radius, self._radius)

        if not self.isEnabled():
            color = with_alpha(theme.text_muted, 130)
        elif checked:
            color = theme.accent_light
        elif self._danger:
            color = blend(theme.text_secondary, theme.danger, self._hover)
        elif self._accent_hover:
            color = blend(theme.text_secondary, theme.accent_light, self._hover)
        else:
            color = blend(theme.text_secondary, theme.text, self._hover)

        icon_rect = QRectF(0, 0, self._icon_size, self._icon_size)
        icon_rect.moveCenter(rect.center())
        icons.draw_icon(painter, self._icon_name, icon_rect, color, 1.65)


class WindowButton(IconButton):
    """Windows-style caption button (minimise / maximise / close)."""

    def __init__(self, icon_name: str, tooltip: str, *, danger: bool = False) -> None:
        super().__init__(
            icon_name,
            size=(40, 30),
            icon_size=15,
            radius=8,
            tooltip=tooltip,
            danger=danger,
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class MusicButton(IconButton):
    def __init__(self) -> None:
        super().__init__(
            "music",
            size=(36, 36),
            icon_size=18,
            radius=18,
            tooltip="Музыкальный плеер",
            bordered=True,
            accent_hover=True,
        )


class NavButton(HoverButton):
    """Sidebar navigation item with an animated hover pill."""

    def __init__(self, text: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self._icon_name = icon_name
        self.setCheckable(True)
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(text)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        checked = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(0, 2, 0, -2)
        active = 1.0 if checked else 0.0
        fill = with_alpha(
            blend(theme.accent, theme.text, 0.0),
            int(20 + 18 * self._hover + 26 * active),
        )
        painter.setBrush(fill)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 12, 12)

        if active or self._hover:
            painter.save()
            path = QPainterPath()
            path.addRoundedRect(rect, 8, 8)
            painter.setClipPath(path)
            painter.fillPath(
                path,
                with_alpha(
                    theme.accent,
                    32 if active else max(0, int(10 * self._hover)),
                ),
            )
            painter.restore()

        if checked:
            painter.setBrush(theme.accent)
            painter.setPen(Qt.PenStyle.NoPen)
            indicator = QRectF(rect.left(), rect.center().y() - 9, 3, 18)
            painter.drawRoundedRect(indicator, 1.5, 1.5)

        if checked:
            icon_color = blend(theme.accent_light, theme.text, self._hover * 0.4)
            text_color = theme.text
        else:
            icon_color = blend(theme.text_muted, theme.text_secondary, self._hover)
            text_color = blend(theme.text_secondary, theme.text, self._hover)

        icon_rect = QRectF(14, rect.center().y() - 10, 20, 20)
        icons.draw_icon(painter, self._icon_name, icon_rect, icon_color, 1.7)

        painter.setFont(font(13, QFont.Weight.DemiBold if checked else QFont.Weight.Medium))
        painter.setPen(text_color)
        text_rect = QRectF(44, rect.top(), rect.width() - 52, rect.height())
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )

        if self.hasFocus() and not checked:
            painter.setPen(QPen(with_alpha(theme.accent_light, 90), 1))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 11, 11)


class ToggleSwitch(QAbstractButton):
    """A small animated toggle used by the proxy settings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(44, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._progress = 0.0
        self._animation = QPropertyAnimation(self, b"progress", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt API
        # Programmatic updates (loading the config) should not animate;
        # interactive toggles animate via the ``toggled`` signal.
        blocked = self.blockSignals(True)
        try:
            super().setChecked(checked)
        finally:
            self.blockSignals(blocked)
        self._progress = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2

        if self._progress > 0.01:
            painter.setBrush(theme.accent)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, radius, radius)
            if self._progress < 1.0:
                painter.setBrush(QColor(255, 255, 255, int(60 * (1 - self._progress))))
                painter.drawRoundedRect(rect, radius, radius)
        else:
            painter.setBrush(QColor(255, 255, 255, 30))
            painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
            painter.drawRoundedRect(rect, radius, radius)

        knob_radius = rect.height() / 2 - 4
        start = rect.left() + knob_radius + 4
        end = rect.right() - knob_radius - 4
        x = start + (end - start) * self._progress
        knob = QRectF(
            x - knob_radius,
            rect.center().y() - knob_radius,
            knob_radius * 2,
            knob_radius * 2,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawEllipse(knob.translated(0, 1.4))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(knob)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(with_alpha(theme.accent_light, 120), 1.4))
            painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)


class GlassComboBox(QComboBox):
    """Combo box with a hand-drawn chevron that follows the theme."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(170)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        size = 14.0
        rect = QRectF(self.width() - 28, (self.height() - size) / 2, size, size)
        icons.draw_icon(painter, "chevron_down", rect, theme.text_muted, 1.7)


class CapsLabel(QWidget):
    """Letter-spaced uppercase micro label (eyebrow text)."""

    def __init__(
        self,
        text: str,
        parent: QWidget | None = None,
        *,
        size: int = 10,
        spacing: float = 1.7,
        accent: bool = False,
        muted: bool = False,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._size = size
        self._spacing = spacing
        self._accent = accent
        self._muted = muted
        self._font = font(size, QFont.Weight.Bold)
        metrics = QFontMetrics(self._font)
        width = metrics.horizontalAdvance(text) + spacing * max(0, len(text) - 1) + 2
        self.setFixedSize(int(width) + 2, metrics.height() + 2)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._text = text
        self.setFixedSize(self.sizeHint())
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self._font)
        width = (
            metrics.horizontalAdvance(self._text)
            + self._spacing * max(0, len(self._text) - 1)
            + 2
        )
        return QSize(int(width) + 2, metrics.height() + 2)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        color = (
            theme.accent_3
            if self._accent
            else theme.text_muted if self._muted else theme.text_secondary
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self._font)
        painter.setPen(color)
        x = 0.0
        metrics = QFontMetrics(self._font)
        baseline = (self.height() + metrics.ascent() - metrics.descent()) / 2
        for index, character in enumerate(self._text):
            painter.drawText(QPointF(x, baseline), character)
            x += metrics.horizontalAdvance(character)
            if index < len(self._text) - 1:
                x += self._spacing


class GradientLabel(QLabel):
    """A large display label painted with a theme gradient."""

    def __init__(
        self,
        text: str,
        parent: QWidget | None = None,
        *,
        size: int = 36,
        weight: QFont.Weight = QFont.Weight.DemiBold,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
    ) -> None:
        super().__init__(text, parent)
        self._size = size
        self._weight = weight
        self._align = align
        self._paint_font = font(size, weight)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self._paint_font)
        return QSize(metrics.horizontalAdvance(self.text()) + 8, metrics.height() + 8)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self._paint_font)
        rect = self.rect().adjusted(0, 0, 0, 0)
        painter.setPen(QPen(theme.text, 1))
        painter.drawText(rect, int(self._align | Qt.AlignmentFlag.AlignVCenter), self.text())


class IconBadge(QWidget):
    """Rounded icon tile used by empty states and feature cards."""

    def __init__(
        self,
        icon_name: str,
        parent: QWidget | None = None,
        *,
        size: int = 52,
        icon_size: int = 23,
        radius: int = 15,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_size = icon_size
        self._radius = radius
        self.setFixedSize(size, size)

    def set_icon(self, icon_name: str) -> None:
        self._icon_name = icon_name
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        painter.setBrush(with_alpha(theme.accent, 26))
        painter.setPen(QPen(with_alpha(theme.accent, 54), 1))
        painter.drawRoundedRect(rect, self._radius, self._radius)

        icon_rect = QRectF(0, 0, self._icon_size, self._icon_size)
        icon_rect.moveCenter(rect.center())
        icons.draw_icon(painter, self._icon_name, icon_rect, theme.accent_light, 1.65)


class AvatarWidget(QWidget):
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None, *, size: int = 44) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skin: QPixmap | None = None

    def set_image(self, image: QPixmap | None) -> None:
        self._skin = image if image is not None and not image.isNull() else None
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addEllipse(rect)
        painter.save()
        painter.setClipPath(clip)
        if self._skin is not None:
            source = QRectF(self._skin.rect())
            if self._skin.width() >= 64 and self._skin.height() >= 32:
                source = QRectF(8, 8, 8, 8)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawPixmap(rect, self._skin, source)
        else:
            painter.fillRect(rect, theme.accent)
            silhouette = QRectF(
                rect.center().x() - rect.width() * 0.25,
                rect.center().y() - rect.height() * 0.28,
                rect.width() * 0.5,
                rect.height() * 0.5,
            )
            painter.setBrush(with_alpha(QColor("#FFFFFF"), 210))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(silhouette)
            shoulders = QPainterPath()
            shoulders.moveTo(rect.left() + rect.width() * 0.22, rect.bottom() - 6)
            shoulders.cubicTo(
                rect.left() + rect.width() * 0.28,
                rect.bottom() - rect.height() * 0.32,
                rect.right() - rect.width() * 0.28,
                rect.bottom() - rect.height() * 0.32,
                rect.right() - rect.width() * 0.22,
                rect.bottom() - 6,
            )
            painter.drawPath(shoulders)
        painter.restore()
        painter.setPen(QPen(with_alpha(theme.text, 40), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)

        status_radius = max(4.5, rect.width() * 0.12)
        status = QRectF(
            rect.right() - status_radius * 2 + 1,
            rect.bottom() - status_radius * 2 + 1,
            status_radius * 2,
            status_radius * 2,
        )
        painter.setBrush(theme.panel_solid)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(status.adjusted(-2, -2, 2, 2))
        painter.setBrush(theme.success)
        painter.drawEllipse(status)


class LogoWidget(QWidget):
    """Fionix wordmark with a hand-painted mark."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        mark_size = 40.0
        mark = QRectF(0, (self.height() - mark_size) / 2, mark_size, mark_size)
        logo = QPixmap(str(asset_path("icons", "fionix.png")))
        if not logo.isNull():
            painter.drawPixmap(
                mark.toRect(),
                logo.scaled(
                    mark.size().toSize(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )
        else:
            path = QPainterPath()
            path.addRoundedRect(mark, 8, 8)
            painter.setPen(QPen(with_alpha(QColor("#FFFFFF"), 40), 1))
            painter.setBrush(theme.accent)
            painter.drawPath(path)

        painter.setPen(theme.text)
        wordmark_font = font(22, QFont.Weight.Bold)
        wordmark_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.4)
        painter.setFont(wordmark_font)
        painter.drawText(
            QRectF(mark.right() + 11, 9, self.width() - mark.right() - 14, 26),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            "Fionix",
        )

        caption_font = font(8, QFont.Weight.DemiBold)
        caption_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        painter.setFont(caption_font)
        painter.setPen(theme.text_muted)
        painter.drawText(
            QRectF(mark.right() + 12, 31, self.width() - mark.right() - 16, 12),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            "MINECRAFT LAUNCHER",
        )


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class EmptyState(QFrame):
    """Reusable empty-state panel."""

    def __init__(
        self,
        icon_name: str,
        title: str,
        description: str,
        parent: QWidget | None = None,
        *,
        badge_size: int = 52,
        description_width: int = 420,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.badge = IconBadge(icon_name, size=badge_size, icon_size=int(badge_size * 0.45))
        self.title_label = QLabel(title)
        self.title_label.setObjectName("EmptyTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("EmptyText")
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label.setWordWrap(True)
        self.description_label.setMaximumWidth(description_width)

        layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(2)
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.description_label, 0, Qt.AlignmentFlag.AlignCenter)
