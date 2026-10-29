"""Tests for the pre-rendered skin viewer (no WebGL, no QtWebEngine)."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from src.ui.skin_viewer import (
        SKIN_UV,
        YAW_RING,
        Skin3DView,
        SkinRenderer,
        _cape_uv,
    )

    HAS_QT = True
except Exception:  # pragma: no cover - PySide6 is optional for core tests
    HAS_QT = False

SIDE_COLORS = {
    "front": QColor("#FF0000"),
    "back": QColor("#0000FF"),
    "left": QColor("#00FF00"),
    "right": QColor("#FFFF00"),
    "top": QColor("#FFFFFF"),
    "bottom": QColor("#000000"),
}


def _side_atlas() -> QImage:
    """Skin whose faces are colour-coded by side (transparent background)."""
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    for part in ("head", "body", "right_arm", "left_arm", "right_leg", "left_leg"):
        for face, (x, y, w, h) in SKIN_UV[part].items():
            painter.fillRect(x, y, w, h, SIDE_COLORS[face])
    painter.end()
    return image


def _dominant(color: QColor) -> str:
    red, green, blue = color.red(), color.green(), color.blue()
    if red > blue + 60 and green > blue + 60:
        return "yellow"
    if red > green + 40 and red > blue + 40:
        return "red"
    if blue > red + 40 and blue > green + 40:
        return "blue"
    if green > red + 40 and green > blue + 40:
        return "green"
    return "other"


@unittest.skipUnless(HAS_QT, "PySide6 is not available")
class SkinRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _head_colour(self, key: tuple) -> QColor:
        renderer = SkinRenderer()
        renderer.set_skin(_side_atlas())
        size = QSize(300, 380)
        image = renderer.image(key, size)
        return image.pixelColor(int(size.width() * 0.5), int(size.height() * 0.16))

    def test_front_view_shows_the_face(self) -> None:
        self.assertEqual(_dominant(self._head_colour(("yaw", 0))), "red")

    def test_left_view_shows_the_left_side(self) -> None:
        # YAW_RING[2] == 90 degrees -> camera on +X -> the model's LEFT side.
        self.assertEqual(YAW_RING[2], 90.0)
        self.assertEqual(_dominant(self._head_colour(("yaw", 2))), "green")

    def test_back_and_right_views(self) -> None:
        self.assertEqual(_dominant(self._head_colour(("yaw", 4))), "blue")
        self.assertEqual(_dominant(self._head_colour(("yaw", 6))), "yellow")

    def test_all_views_render_at_the_requested_size(self) -> None:
        renderer = SkinRenderer()
        renderer.set_skin(_side_atlas())
        size = QSize(200, 260)
        for index in range(len(YAW_RING)):
            image = renderer.image(("yaw", index), size)
            self.assertEqual(image.size(), size)
            self.assertFalse(image.isNull())
        for key in (("top",), ("bottom",)):
            image = renderer.image(key, size)
            self.assertEqual(image.size(), size)

    def test_views_are_cached(self) -> None:
        renderer = SkinRenderer()
        renderer.set_skin(_side_atlas())
        size = QSize(180, 220)
        first = renderer.image(("yaw", 0), size)
        second = renderer.image(("yaw", 0), size)
        self.assertIs(first, second)

    def test_cape_uses_its_own_texture(self) -> None:
        """The cape must be painted with the cape image, not with the skin."""
        renderer = SkinRenderer()
        renderer.set_skin(_side_atlas())
        cape = QImage(64, 32, QImage.Format.Format_ARGB32)
        cape.fill(QColor("#FF00FF"))              # magenta
        renderer.set_cape(cape)
        size = QSize(300, 380)
        back = renderer.image(("yaw", 4), size)   # сзади — плащ видно
        front = renderer.image(("yaw", 0), size)  # спереди — не видно

        def magenta(color: QColor) -> bool:
            return color.red() > 110 and color.blue() > 110 and color.green() < 90

        back_px = back.pixelColor(int(size.width() * 0.5), int(size.height() * 0.45))
        front_px = front.pixelColor(int(size.width() * 0.5), int(size.height() * 0.45))
        self.assertTrue(magenta(back_px), f"cape colour expected, got {back_px.name()}")
        self.assertFalse(magenta(front_px), "cape must not be visible from the front")

    def test_cape_uv_uses_the_box_offset(self) -> None:
        """Плащ — бокс 10x16x1, его лицевая грань начинается с (1, 1)."""
        atlas = QImage(64, 32, QImage.Format.Format_ARGB32)
        atlas.fill(Qt.GlobalColor.transparent)
        self.assertEqual(_cape_uv(atlas), (1, 1, 10, 16))

        legacy = QImage(22, 17, QImage.Format.Format_ARGB32)
        legacy.fill(Qt.GlobalColor.transparent)
        self.assertEqual(_cape_uv(legacy), (1, 1, 10, 16))

        shaped = QImage(20, 32, QImage.Format.Format_ARGB32)
        shaped.fill(Qt.GlobalColor.transparent)
        self.assertEqual(_cape_uv(shaped), (0, 0, 20, 32))

    def test_legacy_cape_is_stretched_over_the_whole_quad(self) -> None:
        renderer = SkinRenderer()
        renderer.set_skin(_side_atlas())
        legacy = QImage(22, 17, QImage.Format.Format_ARGB32)
        legacy.fill(QColor("#FF00FF"))
        renderer.set_cape(legacy)
        back = renderer.image(("yaw", 4), QSize(300, 380))
        color = back.pixelColor(150, int(380 * 0.45))
        self.assertTrue(color.red() > 110 and color.blue() > 110 and color.green() < 90)

    def test_hd_cape_uses_the_whole_image(self) -> None:
        """A 20x32 cape is the same 10:16 shape, only twice as big."""
        renderer = SkinRenderer()
        renderer.set_skin(_side_atlas())
        hd = QImage(20, 32, QImage.Format.Format_ARGB32)
        hd.fill(QColor("#FF00FF"))
        renderer.set_cape(hd)
        back = renderer.image(("yaw", 4), QSize(300, 380))
        color = back.pixelColor(150, int(380 * 0.45))
        self.assertTrue(color.red() > 110 and color.blue() > 110 and color.green() < 90)

    def test_atlas_uses_the_vanilla_10x16_block(self) -> None:
        """Real Mojang file: 64x32 atlas with extra art beside the 10x16 cape."""
        renderer = SkinRenderer()
        renderer.set_skin(_side_atlas())
        atlas = QImage(64, 32, QImage.Format.Format_ARGB32)
        atlas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(atlas)
        painter.fillRect(0, 0, 22, 17, QColor("#FF00FF"))    # плащ + запас
        painter.fillRect(34, 2, 11, 20, QColor("#00FFFF"))   # элитра
        painter.end()
        renderer.set_cape(atlas)
        back = renderer.image(("yaw", 4), QSize(300, 380))

        def sample(x_ratio: float) -> QColor:
            return back.pixelColor(
                int(300 * x_ratio), int(380 * 0.45)
            )

        colour = sample(0.5)
        self.assertTrue(
            colour.red() > 110 and colour.blue() > 110 and colour.green() < 90,
            f"cape colour expected, got {colour.name()}",
        )
        # Элитра (бирюза) не должна попадать на плащ.
        for ratio in (0.42, 0.58):
            pixel = sample(ratio)
            self.assertFalse(
                pixel.green() > 150 and pixel.blue() > 150 and pixel.red() < 90,
                f"elytra colour leaked at {ratio}: {pixel.name()}",
            )


@unittest.skipUnless(HAS_QT, "PySide6 is not available")
class SkinControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.view = Skin3DView()
        self.preview = self.view.preview

    def test_starts_at_the_front(self) -> None:
        self.assertEqual(self.preview.view_index, 0)
        self.assertEqual(self.preview.view_label(), "Спереди")

    def test_left_button_turns_to_the_left_side(self) -> None:
        self.preview.rotate_left()                 # 3/4 frame, shown instantly
        self.assertEqual(self.preview.view_index, 1)
        self.preview._finish_step(2)               # timer completes the step
        self.assertEqual(self.preview.view_index, 2)
        self.assertEqual(self.preview.view_label(), "Слева")

    def test_right_button_turns_to_the_right_side(self) -> None:
        self.preview.rotate_right()
        self.assertEqual(self.preview.view_index, len(YAW_RING) - 1)
        self.preview._finish_step(len(YAW_RING) - 2)
        self.assertEqual(self.preview.view_label(), "Справа")

    def test_up_and_down_toggle_top_and_bottom(self) -> None:
        self.preview.look_up()
        self.assertEqual(self.preview.view_label(), "Сверху")
        self.preview.look_up()
        self.assertEqual(self.preview.view_label(), "Спереди")
        self.preview.look_down()
        self.assertEqual(self.preview.view_label(), "Снизу")
        self.preview.look_down()
        self.assertEqual(self.preview.view_label(), "Спереди")

    def test_reset_returns_to_front(self) -> None:
        self.preview.rotate_left()
        self.preview._finish_step(2)
        self.view._set_yaw(0)
        self.assertEqual(self.preview.view_index, 0)

    def test_slim_variant_changes_nothing_structurally(self) -> None:
        self.view.set_variant("slim")
        self.assertEqual(self.view.variant, "slim")
        self.view.set_variant("classic")
        self.assertEqual(self.view.variant, "classic")

    def test_skin_and_cape_updates_do_not_raise(self) -> None:
        self.view.set_skin(_side_atlas())
        self.view.set_cape(None)
        self.view.set_show_hint(False)
        self.assertTrue(self.view.preview.pixmap().isNull() is False)


if __name__ == "__main__":
    unittest.main()
