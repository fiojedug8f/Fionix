"""Regression tests for the in-game overlay.

These do not launch Minecraft: they verify the parts that used to be broken --
the panels must be real, visible, always-on-top windows, and enabling the
overlay must never leave an empty transparent window on screen.
"""

from __future__ import annotations

import os
import shutil
import time
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import QApplication, QWidget

    from src.core.config_manager import ConfigManager
    from src.ui import overlay as overlay_module
    from src.ui.player import MusicPlayer
    from src.ui.screenshot_gallery import ScreenshotGallery, screenshot_files

    HAS_QT = True
except Exception:  # pragma: no cover - PySide6 is optional for core tests
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 is not available")
class OverlayVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        # Chromium cannot start in a headless test run; the browser view is
        # irrelevant for the window/visibility logic under test.
        cls._original_ensure_view = overlay_module.OverlayBrowser.ensure_view
        overlay_module.OverlayBrowser.ensure_view = lambda self: None
        cls._original_borderless = overlay_module.make_borderless
        overlay_module.make_borderless = lambda pid: True

    @classmethod
    def tearDownClass(cls) -> None:
        overlay_module.OverlayBrowser.ensure_view = cls._original_ensure_view
        overlay_module.make_borderless = cls._original_borderless

    def setUp(self) -> None:
        root = Path(__file__).resolve().parent / ".tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.root = root / f"overlay-{uuid.uuid4().hex}"
        self.data = self.root / "data"
        self.data.mkdir(parents=True)
        self.config = ConfigManager(self.data)
        self.config.update({"overlay_enabled": True})
        self.config.set_overlay_positions({})
        self.overlay = None

    def tearDown(self) -> None:
        if self.overlay is not None:
            self.overlay.shutdown()
        shutil.rmtree(self.root, ignore_errors=True)

    def _attach(self) -> "overlay_module.OverlayWindow":
        self.overlay = overlay_module.OverlayWindow(self.config)
        self.overlay.set_enabled(True)
        self.overlay.attach_game(4242, "Test 1.21.5", self.data)
        self.app.processEvents()
        return self.overlay

    def test_controller_has_no_window_of_its_own(self) -> None:
        self.overlay = overlay_module.OverlayWindow(self.config)
        self.assertNotIsInstance(self.overlay, QWidget)

    def test_panels_are_visible_windows_after_attach(self) -> None:
        overlay = self._attach()
        for panel in (overlay.browser, overlay.player, overlay.info):
            self.assertTrue(panel.isWindow(), "panel must be its own window")
            self.assertTrue(panel.isVisible(), "panel must be visible")
            self.assertTrue(
                panel.windowFlags() & Qt.WindowType.WindowStaysOnTopHint,
                "panel must stay above the game",
            )
            self.assertTrue(
                panel.windowFlags() & Qt.WindowType.FramelessWindowHint,
                "panel must be frameless",
            )

    def test_panel_geometry_is_persisted(self) -> None:
        overlay = self._attach()
        overlay.save_positions_now()
        stored = self.config.overlay_positions
        self.assertEqual(sorted(stored), ["browser", "info", "player"])
        for value in stored.values():
            self.assertEqual(len(value), 4)

    def test_toggle_hides_and_shows_panels(self) -> None:
        overlay = self._attach()
        overlay.toggle()
        self.assertFalse(overlay.panels_visible())
        overlay._last_toggle = 0.0  # bypass the anti-repeat debounce
        overlay.toggle()
        self.assertTrue(overlay.panels_visible())

    def test_repeated_hotkey_does_not_flap(self) -> None:
        """Holding Shift+F1 must not toggle twice in a row."""
        overlay = self._attach()             # panels are open after attach
        overlay._last_toggle = 0.0
        overlay.toggle()                     # closes
        self.assertFalse(overlay.panels_visible())
        overlay._last_toggle = 0.0
        overlay.toggle()                     # opens
        self.assertTrue(overlay.panels_visible())
        overlay.toggle()                     # key repeat right after: ignored
        self.assertTrue(overlay.panels_visible())

    def test_focus_watch_closes_when_another_window_wins(self) -> None:
        overlay = self._attach()
        overlay._hwnd = 12345               # pretend the game window is known
        overlay._focus_guard_until = 0.0
        original = overlay_module._foreground_window
        overlay_module._foreground_window = lambda: 999
        try:
            overlay._watch_focus()
        finally:
            overlay_module._foreground_window = original
        self.assertFalse(overlay.panels_visible())

    def test_focus_watch_keeps_overlay_while_a_panel_is_active(self) -> None:
        overlay = self._attach()
        overlay._hwnd = 12345
        overlay._focus_guard_until = 0.0
        handle = int(overlay.browser.winId())
        original = overlay_module._foreground_window
        overlay_module._foreground_window = lambda: handle
        try:
            overlay._watch_focus()
        finally:
            overlay_module._foreground_window = original
        self.assertTrue(overlay.panels_visible())

    def test_focus_watch_keeps_overlay_for_own_dialogs(self) -> None:
        """A file picker opened from the overlay must not close it."""
        overlay = self._attach()
        overlay._hwnd = 12345
        overlay._focus_guard_until = 0.0
        original_fg = overlay_module._foreground_window
        original_pid = overlay_module._window_process_id
        overlay_module._foreground_window = lambda: 777
        overlay_module._window_process_id = lambda hwnd: os.getpid()
        try:
            overlay._watch_focus()
        finally:
            overlay_module._foreground_window = original_fg
            overlay_module._window_process_id = original_pid
        self.assertTrue(overlay.panels_visible())

    def test_disabled_overlay_never_shows(self) -> None:
        self.overlay = overlay_module.OverlayWindow(self.config)
        self.overlay.set_enabled(False)
        self.overlay.attach_game(4242, "Test", self.data)
        self.overlay.toggle()
        self.assertFalse(self.overlay.panels_visible())

    def test_overlay_disabled_in_settings_is_respected(self) -> None:
        self.config.update({"overlay_enabled": False})
        self.overlay = overlay_module.OverlayWindow(self.config)
        self.overlay.attach_game(4242, "Test", self.data)
        self.overlay.show_panels()
        self.assertFalse(self.overlay.panels_visible())


@unittest.skipUnless(HAS_QT, "PySide6 is not available")
class BorderlessOptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parent / ".tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.root = root / f"options-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_overlay_requirements_are_written(self) -> None:
        options = self.root / "options.txt"
        options.write_text(
            "version:1\nfullscreen:true\nfov:0.5\npauseOnLostFocus:true\n",
            encoding="utf-8",
        )
        overlay_module.prepare_borderless_options(self.root)
        text = options.read_text(encoding="utf-8")
        self.assertIn("fullscreen:false", text)
        self.assertIn("pauseOnLostFocus:false", text)
        self.assertIn("fov:0.5", text)
        self.assertEqual(text.count("fullscreen:"), 1)

    def test_options_are_created_when_missing(self) -> None:
        overlay_module.prepare_borderless_options(self.root)
        text = (self.root / "options.txt").read_text(encoding="utf-8")
        self.assertIn("fullscreen:false", text)
        self.assertIn("pauseOnLostFocus:false", text)

    def test_repeated_calls_are_idempotent(self) -> None:
        overlay_module.prepare_borderless_options(self.root)
        first = (self.root / "options.txt").read_text(encoding="utf-8")
        overlay_module.prepare_borderless_options(self.root)
        second = (self.root / "options.txt").read_text(encoding="utf-8")
        self.assertEqual(first, second)


class _PlayerSpy:
    """Records calls made on the shared QMediaPlayer."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def duration(self) -> int:
        return 0

    def position(self) -> int:
        return 0

    def playbackState(self):  # noqa: N802 - Qt naming
        from PySide6.QtMultimedia import QMediaPlayer

        return QMediaPlayer.PlaybackState.StoppedState

    def pause(self) -> None:
        self.calls.append("pause")

    def play(self) -> None:
        self.calls.append("play")

    def stop(self) -> None:
        self.calls.append("stop")


@unittest.skipUnless(HAS_QT, "PySide6 is not available")
class SharedMusicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls._original_borderless = overlay_module.make_borderless
        overlay_module.make_borderless = lambda pid: True
        overlay_module.OverlayBrowser.ensure_view = lambda self: None

    @classmethod
    def tearDownClass(cls) -> None:
        overlay_module.make_borderless = cls._original_borderless

    def setUp(self) -> None:
        root = Path(__file__).resolve().parent / ".tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.root = root / f"music-{uuid.uuid4().hex}"
        self.data = self.root / "data"
        self.data.mkdir(parents=True)
        self.config = ConfigManager(self.data)
        self.config.update({"overlay_enabled": True})
        self.config.set_overlay_positions({})
        self.music = MusicPlayer()
        self.overlay = None

    def tearDown(self) -> None:
        if self.overlay is not None:
            self.overlay.shutdown()
        shutil.rmtree(self.root, ignore_errors=True)

    def _attach(self):
        self.overlay = overlay_module.OverlayWindow(self.config, music=self.music)
        self.overlay.set_enabled(True)
        self.overlay.attach_game(4242, "Test", self.data)
        self.app.processEvents()
        return self.overlay

    def test_overlay_player_uses_the_launcher_player(self) -> None:
        overlay = self._attach()
        self.assertIs(overlay.player.music, self.music)
        self.assertIs(overlay.music, self.music)

    def test_hiding_the_overlay_keeps_the_music_running(self) -> None:
        spy = _PlayerSpy()
        self.music.player = spy  # type: ignore[assignment]
        overlay = self._attach()
        overlay.hide_panels()
        overlay.show_panels()
        overlay.hide_panels()
        self.assertEqual(spy.calls, [], "hiding must not pause/stop the music")

    def test_panel_mirrors_the_shared_state(self) -> None:
        overlay = self._attach()
        self.music.player.setPosition(0)
        overlay.player._on_track("Song", "Album")
        self.assertEqual(overlay.player.title_label.text(), "Song")


@unittest.skipUnless(HAS_QT, "PySide6 is not available")
class ScreenshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls._original_borderless = overlay_module.make_borderless
        overlay_module.make_borderless = lambda pid: True
        overlay_module.OverlayBrowser.ensure_view = lambda self: None

    @classmethod
    def tearDownClass(cls) -> None:
        overlay_module.make_borderless = cls._original_borderless

    def setUp(self) -> None:
        root = Path(__file__).resolve().parent / ".tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.root = root / f"shot-{uuid.uuid4().hex}"
        self.data = self.root / "data"
        self.data.mkdir(parents=True)
        self.instance = self.root / "instances" / "Test Pack"
        self.instance.mkdir(parents=True)
        self.config = ConfigManager(self.data)
        self.config.update({"overlay_enabled": True})
        self.config.set_overlay_positions({})
        self.overlay = None

    def tearDown(self) -> None:
        if self.overlay is not None:
            self.overlay.shutdown()
        shutil.rmtree(self.root, ignore_errors=True)

    def _pixmap(self) -> QPixmap:
        pixmap = QPixmap(320, 180)
        pixmap.fill(QColor("#123456"))
        return pixmap

    def test_screenshot_is_saved_into_the_instance_folder(self) -> None:
        self.overlay = overlay_module.OverlayWindow(self.config)
        self.overlay.set_enabled(True)
        self.overlay.attach_game(4242, "Test Pack", self.instance)
        saved: list[str] = []
        self.overlay.screenshot_saved.connect(saved.append)
        original = overlay_module._grab_screen
        overlay_module._grab_screen = lambda screen: self._pixmap()
        try:
            path = self.overlay.take_screenshot()
        finally:
            overlay_module._grab_screen = original
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.instance / "screenshots")
        self.assertEqual(path.suffix, ".png")
        self.assertEqual(saved, [str(path)])

    def test_second_screenshot_does_not_overwrite_the_first(self) -> None:
        self.overlay = overlay_module.OverlayWindow(self.config)
        self.overlay.set_enabled(True)
        self.overlay.attach_game(4242, "Test Pack", self.instance)
        original = overlay_module._grab_screen
        overlay_module._grab_screen = lambda screen: self._pixmap()
        try:
            first = self.overlay.take_screenshot()
            second = self.overlay.take_screenshot()
        finally:
            overlay_module._grab_screen = original
        self.assertNotEqual(first, second)
        self.assertTrue(first is not None and first.is_file())
        self.assertTrue(second is not None and second.is_file())

    def test_screenshot_without_attached_instance_is_skipped(self) -> None:
        self.overlay = overlay_module.OverlayWindow(self.config)
        self.assertIsNone(self.overlay.take_screenshot())

    def test_gallery_lists_newest_first(self) -> None:
        folder = self.instance / "screenshots"
        folder.mkdir(parents=True)
        old = folder / "2026-01-01_10-00-00.png"
        new = folder / "2026-02-02_10-00-00.png"
        for path in (old, new):
            path.write_bytes(b"png")
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (2_000_000, 2_000_000))
        (folder / "notes.txt").write_text("ignore me", encoding="utf-8")
        files = screenshot_files(self.instance)
        self.assertEqual([path.name for path in files], [new.name, old.name])

    def test_gallery_counts_the_instance_screenshots(self) -> None:
        folder = self.instance / "screenshots"
        folder.mkdir(parents=True)
        for name in ("a.png", "b.png"):
            (folder / name).write_bytes(b"png")
        gallery = ScreenshotGallery()
        gallery.load(self.instance, "Test Pack")
        self.assertEqual(gallery.count_label.text(), "2")
        self.assertEqual(len(gallery._tiles), 2)
        self.assertTrue(gallery.scroll.isHidden() is False)
        gallery.deleteLater()

    def test_gallery_shows_overlay_and_game_screenshots(self) -> None:
        """Overlay shots and Minecraft F2 shots live in the same folder."""
        folder = self.instance / "screenshots"
        folder.mkdir(parents=True)
        (folder / "2026-10-29_12-00-00.png").write_bytes(b"overlay")
        (folder / "2026-10-29_12.30.45.png").write_bytes(b"minecraft-f2")
        files = screenshot_files(self.instance)
        self.assertEqual(len(files), 2)

    def test_gallery_looks_into_nested_minecraft_folder(self) -> None:
        nested = self.instance / ".minecraft" / "screenshots"
        nested.mkdir(parents=True)
        (nested / "2026-10-29_13.00.00.png").write_bytes(b"png")
        files = screenshot_files(self.instance)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent, nested)

    def test_gallery_does_not_duplicate_the_same_file(self) -> None:
        folder = self.instance / "screenshots"
        folder.mkdir(parents=True)
        (folder / "one.png").write_bytes(b"png")
        files = screenshot_files(self.instance)
        self.assertEqual(len(files), 1)



if __name__ == "__main__":
    unittest.main()
