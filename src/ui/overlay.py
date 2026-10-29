"""Fionix in-game overlay.

Three independent floating panels (mini-browser, mini-player and an
info/clock panel) that stay above the Minecraft window while the game runs.

Why the panels are separate windows
-----------------------------------
An earlier revision painted the panels *inside* one full-screen transparent
window.  That approach cannot work: a full-screen window either swallows every
mouse click meant for the game (``WA_TransparentForMouseEvents`` off) or is
click-through as a whole (attribute on).  Worse, the panels were created with
``parent=None`` and never shown, so the overlay was an empty, fully
transparent window -- visibly nothing happened when it was "enabled".

Each panel is now its own small frameless, always-on-top tool window.  The game
keeps receiving mouse input everywhere outside a panel, and showing a panel is
enough for it to be visible.

``OverlayWindow`` is the controller: a ``QObject`` without a window of its own.
It owns the panels, the global ``Shift+F1`` hotkey and the persisted geometry.

The hotkey is registered with the Win32 ``RegisterHotKey`` API (an OS-level
hotkey that also fires while the game has focus) and falls back to the
``keyboard`` module when that is unavailable.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.core.theme import current_theme
from src.ui.player import MusicPlayer, format_ms
from src.ui.widgets import IconButton

logger = logging.getLogger(__name__)

HOTKEY_LABEL = "Shift+F1"

# pywin32 is installed into .deps during development; PyInstaller bundles the
# same modules under _MEIPASS/win32.
for _candidate in (
    Path(__file__).resolve().parents[2] / ".deps" / "win32",
    Path(__file__).resolve().parents[2] / ".deps" / "win32" / "lib",
    Path(getattr(sys, "_MEIPASS", "")) / "win32",
):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
for _dll_dir in (
    Path(__file__).resolve().parents[2] / ".deps" / "pywin32_system32",
    Path(getattr(sys, "_MEIPASS", "")) / "pywin32_system32",
):
    if _dll_dir.is_dir():
        try:
            import os

            os.add_dll_directory(str(_dll_dir))
        except (ImportError, OSError):
            pass


def _win32_modules():
    try:
        import win32con
        import win32gui
        import win32process

        return win32gui, win32con, win32process
    except Exception:
        return None, None, None


def prepare_borderless_options(instance_path: Path) -> None:
    """Write the options Minecraft needs for a usable overlay.

    * ``fullscreen:false`` -- exclusive fullscreen cannot be overlaid.
    * ``pauseOnLostFocus:false`` -- clicking an overlay panel must not pause
      the single-player game.
    """
    options = Path(instance_path) / "options.txt"
    try:
        lines = options.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    wanted = {"fullscreen": "false", "pauseOnLostFocus": "false"}
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.split(":", 1)[0] if ":" in line else ""
        if key in wanted:
            result.append(f"{key}:{wanted[key]}")
            seen.add(key)
        else:
            result.append(line)
    for key, value in wanted.items():
        if key not in seen:
            result.append(f"{key}:{value}")
    try:
        options.write_text("\n".join(result) + "\n", encoding="utf-8")
    except OSError:
        logger.warning(
            "Could not write options.txt for borderless mode", exc_info=True
        )


def _find_window_for_pid(pid: int):
    win32gui, _, win32process = _win32_modules()
    if not win32gui or not win32process:
        return None
    found: list[int] = []

    def callback(hwnd, _extra):
        try:
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if window_pid == pid and win32gui.IsWindowVisible(hwnd):
                found.append(hwnd)
                return False
        except Exception:
            pass
        return True

    win32gui.EnumWindows(callback, None)
    return found[0] if found else None


def make_borderless(pid: int) -> bool:
    """Turn the Minecraft window into a borderless windowed game.

    The window is deliberately **not** topmost: a topmost full-screen window
    swallows every other application (Alt+Tab looks broken, because the game
    stays on top of the window you switch to).  Only the overlay panels are
    topmost; the game is a normal maximized window.

    Returns ``False`` when the game window is not ready yet (the caller
    retries) or when pywin32 is unavailable.
    """
    hwnd = _find_window_for_pid(pid)
    if not hwnd:
        return False
    win32gui, win32con, _ = _win32_modules()
    if not win32gui:
        return False
    try:
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        borderless = style & ~(
            win32con.WS_CAPTION
            | win32con.WS_THICKFRAME
            | win32con.WS_MINIMIZEBOX
            | win32con.WS_MAXIMIZEBOX
            | win32con.WS_SYSMENU
        )
        if borderless != style:
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, borderless)
        area = QGuiApplication.primaryScreen().availableGeometry()
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_NOTOPMOST,
            area.x(),
            area.y(),
            area.width(),
            area.height(),
            win32con.SWP_FRAMECHANGED | win32con.SWP_NOACTIVATE,
        )
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        return True
    except Exception:
        logger.exception("Could not enable borderless Minecraft")
        return False


def _force_foreground(hwnd: int) -> bool:
    """Bring ``hwnd`` to the foreground from a background process.

    Windows refuses ``SetForegroundWindow`` for a process that does not own the
    foreground window, so the calling thread is temporarily attached to the
    foreground thread's input queue.  Without this the overlay cannot take the
    mouse away from the game (the game would keep rotating the camera under
    the visible overlay cursor).
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.IsWindow(hwnd):
            return False
        foreground = user32.GetForegroundWindow()
        if foreground == hwnd:
            user32.BringWindowToTop(hwnd)
            return True
        target_thread = user32.GetWindowThreadProcessId(
            wintypes.HWND(foreground), None
        )
        current_thread = kernel32.GetCurrentThreadId()
        attached = False
        if target_thread and target_thread != current_thread:
            attached = bool(
                user32.AttachThreadInput(target_thread, current_thread, True)
            )
        try:
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
            user32.BringWindowToTop(wintypes.HWND(hwnd))
            user32.SetActiveWindow(wintypes.HWND(hwnd))
            user32.SetFocus(wintypes.HWND(hwnd))
        finally:
            if attached:
                user32.AttachThreadInput(target_thread, current_thread, False)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        logger.debug("Could not change the foreground window", exc_info=True)
        return False


def _grab_screen(screen):
    """Capture the whole screen (indirection keeps this testable)."""
    return screen.grabWindow(0)


def _foreground_window() -> int:
    """HWND of the current foreground window (0 when unknown)."""
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _window_process_id(hwnd: int) -> int:
    """Process id that owns ``hwnd`` (0 when unknown)."""
    try:
        import ctypes
        from ctypes import wintypes

        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(
            wintypes.HWND(hwnd), ctypes.byref(pid)
        )
        return int(pid.value)
    except Exception:
        return 0


def _window_rect(hwnd: int):
    """Physical ``QRect`` of a window, or ``None``."""
    win32gui, _, _ = _win32_modules()
    if not win32gui or not hwnd:
        return None
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if right - left <= 0 or bottom - top <= 0:
            return None
        return QRect(int(left), int(top), int(right - left), int(bottom - top))
    except Exception:
        return None



# ---------------------------------------------------------------------------
# Global hotkey
# ---------------------------------------------------------------------------


class _GlobalHotkey(QObject):
    """OS-level ``Shift+F1`` via ``RegisterHotKey`` (works over games)."""

    activated = Signal()

    _MOD_SHIFT = 0x0004
    _VK_F1 = 0x70
    _WM_HOTKEY = 0x0312
    _WM_QUIT = 0x0012
    _ID = 0xF10A

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        modifier: int = _MOD_SHIFT,
        key: int = _VK_F1,
    ) -> None:
        super().__init__(parent)
        self._modifier = modifier
        self._key = key
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._stop = threading.Event()
        self._ready = threading.Event()
        self.registered = False

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import ctypes  # noqa: F401  (probe only)
        except Exception:
            return False
        self._thread = threading.Thread(
            target=self._run, name="fionix-overlay-hotkey", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return self.registered

    def stop(self) -> None:
        self._stop.set()
        if self._thread_id:
            try:
                import ctypes

                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, self._WM_QUIT, 0, 0
                )
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _run(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            self._ready.set()
            return
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        # hWnd == NULL makes WM_HOTKEY land in *this* thread's message queue.
        if not user32.RegisterHotKey(None, self._ID, self._modifier, self._key):
            logger.info("RegisterHotKey failed (shortcut busy?); trying fallback")
            self._ready.set()
            return
        self.registered = True
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while not self._stop.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                if msg.message == self._WM_HOTKEY:
                    try:
                        self.activated.emit()
                    except RuntimeError:
                        break
        except Exception:
            logger.exception("Overlay hotkey loop failed")
        finally:
            try:
                user32.UnregisterHotKey(None, self._ID)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

_PANEL_FLAGS = (
    Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.Tool
    | Qt.WindowType.NoDropShadowWindowHint
)


class OverlayPanel(QFrame):
    """A draggable, resizable floating window shown above the game."""

    CORNER_RADIUS = 10.0

    def __init__(
        self,
        key: str,
        title: str,
        overlay: "OverlayWindow",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self.overlay = overlay
        self._drag: QPoint | None = None
        self.setWindowFlags(_PANEL_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("OverlayPanel")
        self.setWindowTitle(f"Fionix · {title}")
        self.setMinimumSize(260, 150)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = QFrame()
        self.header.setObjectName("OverlayPanelHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 5, 8, 5)
        header_layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("OverlayPanelTitle")
        title_label.setToolTip(f"{HOTKEY_LABEL} — скрыть оверлей")
        header_layout.addWidget(title_label, 1)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("OverlayClose")
        self.close_button.setFixedSize(22, 22)
        self.close_button.setToolTip("Скрыть панель")
        self.close_button.clicked.connect(self.hide)
        header_layout.addWidget(self.close_button)
        root.addWidget(self.header)
        # A fixed header height is required: the body of some panels cannot
        # grow (e.g. only a toolbar row), and a stretchy header would then
        # swallow the free space and push the content to the bottom.
        self.header.setFixedHeight(34)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(10, 8, 10, 8)
        self.body.setSpacing(6)
        root.addLayout(self.body, 1)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(16, 16)
        self.grip.setStyleSheet("background: transparent;")
        root.addWidget(self.grip, 0, Qt.AlignmentFlag.AlignRight)
        self.header.installEventFilter(self)

    # -- window behaviour ---------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        """Paint the panel surface.

        A translucent top-level window does not paint stylesheet backgrounds
        (verified on Windows: the panel stayed fully transparent), so the
        rounded surface is drawn explicitly.
        """
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
        painter.fillPath(path, theme.panel_solid)
        pen = QPen(theme.accent)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()
        super().paintEvent(event)

    def present(self) -> None:
        """Show the panel and let it take keyboard/mouse focus.

        ``WA_ShowWithoutActivating`` used to keep the game focused, which is
        exactly what caused the "double mouse" bug: the overlay cursor was
        visible while Minecraft kept rotating the camera underneath it.
        """
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        # The × button hides the panel; closing must never destroy it.
        event.ignore()
        self.hide()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self.overlay.save_positions_later()

    # -- dragging -----------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self.header:
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._drag = event.globalPosition().toPoint()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag is not None:
                delta = event.globalPosition().toPoint() - self._drag
                self.move(self.pos() + delta)
                self._drag = event.globalPosition().toPoint()
                return True
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and self._drag is not None
            ):
                self._drag = None
                self.overlay.save_positions_later()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.overlay.save_positions_later()


class OverlayBrowser(OverlayPanel):
    def __init__(self, overlay: "OverlayWindow") -> None:
        super().__init__("browser", "Браузер", overlay)
        self.view: QWebEngineView | None = None
        row = QHBoxLayout()
        row.setSpacing(4)
        back = QPushButton("←")
        forward = QPushButton("→")
        reload = QPushButton("⟳")
        for button in (back, forward, reload):
            button.setObjectName("OverlayButton")
            button.setFixedSize(28, 28)
            row.addWidget(button)
        self.url = QLineEdit()
        self.url.setPlaceholderText("URL или поиск…")
        self.url.setObjectName("OverlayUrl")
        row.addWidget(self.url, 1)
        self.body.addLayout(row)
        self._nav = (back, forward, reload)
        self.url.returnPressed.connect(self._navigate)

    def ensure_view(self) -> QWebEngineView:
        """Create the web view on first use so game launch stays cheap."""
        if self.view is not None:
            return self.view
        view = QWebEngineView(self)
        settings = view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True
        )
        self.body.addWidget(view, 1)
        back, forward, reload = self._nav
        back.clicked.connect(view.back)
        forward.clicked.connect(view.forward)
        reload.clicked.connect(view.reload)
        view.urlChanged.connect(self._url_changed)
        view.load(QUrl("https://www.google.com/"))
        self.view = view
        return view

    def present(self) -> None:
        self.ensure_view()
        super().present()

    def suspend(self) -> None:
        if self.view is not None:
            self.view.page().setLifecycleState(
                QWebEnginePage.LifecycleState.Frozen
            )

    def resume(self) -> None:
        if self.view is not None:
            self.view.page().setLifecycleState(
                QWebEnginePage.LifecycleState.Active
            )

    def _navigate(self) -> None:
        text = self.url.text().strip()
        if not text:
            return
        if "://" not in text:
            if " " not in text and "." in text:
                text = "https://" + text
            else:
                text = (
                    "https://www.google.com/search?q="
                    + bytes(QUrl.toPercentEncoding(text)).decode()
                )
        self.ensure_view().load(QUrl(text))

    def _url_changed(self, url: QUrl) -> None:
        if not self.url.hasFocus():
            self.url.setText(url.toString())


class OverlayPlayer(OverlayPanel):
    """Music controls bound to the shared :class:`MusicPlayer`.

    The panel never owns a ``QMediaPlayer``: it is a second view on the same
    instance the launcher popover uses.  A track started in the launcher is
    therefore already playing here, and it keeps playing while the overlay is
    hidden.
    """

    def __init__(
        self, overlay: "OverlayWindow", music: MusicPlayer | None
    ) -> None:
        super().__init__("player", "Музыка", overlay)
        self.music = music

        self.title_label = QLabel("Ничего не играет")
        self.title_label.setObjectName("OverlayTrackTitle")
        self.title_label.setWordWrap(True)
        self.subtitle_label = QLabel("Добавьте музыку в лаунчере")
        self.subtitle_label.setObjectName("OverlayHint")
        self.subtitle_label.setWordWrap(True)
        self.body.addWidget(self.title_label)
        self.body.addWidget(self.subtitle_label)

        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 0)
        self.progress.setObjectName("OverlaySeek")
        self.body.addWidget(self.progress)

        times = QHBoxLayout()
        times.setContentsMargins(0, 0, 0, 0)
        self.position_label = QLabel("0:00")
        self.position_label.setObjectName("OverlayHint")
        self.duration_label = QLabel("0:00")
        self.duration_label.setObjectName("OverlayHint")
        times.addWidget(self.position_label)
        times.addStretch(1)
        times.addWidget(self.duration_label)
        self.body.addLayout(times)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 6, 0, 0)
        controls.setSpacing(8)
        controls.addStretch(1)
        self.prev_button = IconButton(
            "prev", size=(32, 32), icon_size=15, radius=16, tooltip="Предыдущий трек"
        )
        self.play_button = IconButton(
            "play",
            size=(40, 40),
            icon_size=18,
            radius=20,
            tooltip="Играть",
            bordered=True,
        )
        self.next_button = IconButton(
            "next", size=(32, 32), icon_size=15, radius=16, tooltip="Следующий трек"
        )
        for button in (self.prev_button, self.play_button, self.next_button):
            controls.addWidget(button)
        controls.addStretch(1)
        self.body.addLayout(controls)

        volume_row = QHBoxLayout()
        volume_row.setContentsMargins(0, 6, 0, 0)
        volume_row.setSpacing(8)
        volume_caption = QLabel("Громкость")
        volume_caption.setObjectName("OverlayHint")
        volume_row.addWidget(volume_caption)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedHeight(16)
        self.volume.setObjectName("OverlaySeek")
        volume_row.addWidget(self.volume, 1)
        self.volume_label = QLabel("65%")
        self.volume_label.setObjectName("OverlayHint")
        self.volume_label.setFixedWidth(34)
        volume_row.addWidget(self.volume_label)
        self.body.addLayout(volume_row)

        self.track_list = QListWidget()
        self.track_list.setObjectName("OverlayPlaylist")
        self.track_list.setMinimumHeight(56)
        self.track_list.itemDoubleClicked.connect(self._on_item)
        self.body.addWidget(self.track_list, 1)

        self.add_button = QPushButton("＋ Добавить треки")
        self.add_button.setObjectName("OverlayButton")
        self.add_button.setFixedHeight(26)
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self._add_tracks)
        self.body.addWidget(self.add_button)

        if music is not None:
            self.prev_button.clicked.connect(music.previous_track)
            self.play_button.clicked.connect(music.toggle_play)
            self.next_button.clicked.connect(music.next_track)
            self.progress.sliderMoved.connect(music.seek)
            self.volume.valueChanged.connect(music.set_volume)
            music.track_changed.connect(self._on_track)
            music.tracks_changed.connect(self._sync_playlist)
            music.position_changed.connect(self._on_position)
            music.duration_changed.connect(self._on_duration)
            music.state_changed.connect(self._on_state)
            music.volume_changed.connect(self._on_volume_changed)
            self._sync()

    # ------------------------------------------------------------- syncing
    def _sync(self) -> None:
        music = self.music
        if music is None:
            return
        self._sync_playlist()
        self.title_label.setText(music.track_title())
        self.subtitle_label.setText(music.track_subtitle())
        duration = max(0, music.duration())
        self.progress.setMaximum(duration)
        self.progress.setValue(min(music.position(), duration))
        self.position_label.setText(format_ms(music.position()))
        self.duration_label.setText(format_ms(duration))
        self.volume.blockSignals(True)
        self.volume.setValue(music.volume())
        self.volume.blockSignals(False)
        self.volume_label.setText(f"{music.volume()}%")
        self._on_state(music.is_playing())

    def _sync_playlist(self) -> None:
        if self.music is None:
            return
        self.track_list.clear()
        for path in self.music.tracks:
            self.track_list.addItem(QListWidgetItem(path.stem))
        index = self.music.current_index
        if index >= 0:
            self.track_list.setCurrentRow(index)

    # ------------------------------------------------------------- actions
    def _add_tracks(self) -> None:
        if self.music is None:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Добавить музыку",
            str(Path.home()),
            "Аудио (*.mp3 *.ogg *.wav *.flac *.m4a);;Все файлы (*)",
        )
        if files:
            self.music.add_tracks(Path(name) for name in files)
            self._sync()

    def _on_item(self, item: QListWidgetItem) -> None:
        if self.music is not None:
            self.music.play_index(self.track_list.row(item))

    def _on_volume_changed(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self.volume.blockSignals(True)
        self.volume.setValue(value)
        self.volume.blockSignals(False)
        self.volume_label.setText(f"{value}%")

    def _on_track(self, title: str, _subtitle: str) -> None:
        self.title_label.setText(title)
        if self.music is None:
            return
        self.subtitle_label.setText(self.music.track_subtitle())
        self._sync_playlist()

    def present(self) -> None:
        # The playlist may have grown while the overlay was hidden.
        self._sync()
        super().present()

    def _on_state(self, playing: bool) -> None:
        self.play_button.set_icon_name("pause" if playing else "play")
        self.play_button.setToolTip("Пауза" if playing else "Играть")

    def _on_duration(self, duration: int) -> None:
        self.progress.setMaximum(max(0, int(duration)))
        self.duration_label.setText(format_ms(duration))

    def _on_position(self, position: int) -> None:
        if not self.progress.isSliderDown():
            self.progress.setValue(max(0, int(position)))
        self.position_label.setText(format_ms(position))


class OverlayInfo(OverlayPanel):
    screenshot_requested = Signal()

    def __init__(self, overlay: "OverlayWindow") -> None:
        super().__init__("info", "Игра", overlay)
        self.instance_label = QLabel("Minecraft")
        self.instance_label.setObjectName("OverlayInfoTitle")
        self.time_label = QLabel("00:00:00")
        self.time_label.setObjectName("OverlayInfoTime")
        self.clock_label = QLabel("--:--:--")
        self.clock_label.setObjectName("OverlayClock")
        self.hint_label = QLabel(f"{HOTKEY_LABEL} — скрыть · заголовок — перетащить")
        self.hint_label.setObjectName("OverlayHint")
        self.screenshot_button = QPushButton("Сделать скриншот")
        self.screenshot_button.setObjectName("OverlayButton")
        self.screenshot_button.setFixedHeight(28)
        self.screenshot_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.screenshot_button.setToolTip(
            "Сохранить снимок в папку screenshots текущего экземпляра"
        )
        self.screenshot_button.clicked.connect(self.screenshot_requested.emit)
        self.status_label = QLabel("")
        self.status_label.setObjectName("OverlayHint")
        self.body.addWidget(self.instance_label)
        self.body.addWidget(self.time_label)
        self.body.addStretch(1)
        self.body.addWidget(self.screenshot_button)
        self.body.addWidget(self.status_label)
        self.body.addWidget(self.hint_label)
        self.body.addWidget(self.clock_label)

    def set_instance(self, name: str) -> None:
        self.instance_label.setText(name or "Minecraft")

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)



# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class OverlayWindow(QObject):
    """Owns the overlay panels, the hotkey and their persisted geometry."""

    hotkey_pressed = Signal()
    screenshot_saved = Signal(str)

    def __init__(
        self,
        config,
        parent: QObject | None = None,
        *,
        music: MusicPlayer | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.music = music
        self._enabled = bool(getattr(config, "overlay_enabled", False))
        self._attached = False
        self._pid = 0
        self._hwnd = 0
        self._instance_name = ""
        self._instance_path: Path | None = None
        self._started_at: datetime | None = None
        self._panels: list[OverlayPanel] = []
        self.browser: OverlayBrowser | None = None
        self.player: OverlayPlayer | None = None
        self.info: OverlayInfo | None = None
        self._positions_restored = False
        self._overlay_open = False
        self._last_toggle = 0.0
        self._focus_guard_until = 0.0
        self._hotkey: _GlobalHotkey | None = None
        self._keyboard_handle = None
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)
        # The overlay must never float above other applications: this watcher
        # closes it as soon as the foreground window is neither the game nor
        # one of the overlay panels.
        self._focus_watch = QTimer(self)
        self._focus_watch.setInterval(400)
        self._focus_watch.timeout.connect(self._watch_focus)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_positions_now)
        self.hotkey_pressed.connect(self.toggle)
        self._install_hotkey()

    # -- hotkey -------------------------------------------------------------
    def _install_hotkey(self) -> None:
        hotkey = _GlobalHotkey(self)
        if hotkey.start():
            hotkey.activated.connect(self.hotkey_pressed)
            self._hotkey = hotkey
            logger.info(
                "Overlay hotkey registered via RegisterHotKey (%s)", HOTKEY_LABEL
            )
            return
        # No fallback: the old ``keyboard`` hook fired on unrelated keys
        # (WASD while sprinting) and made the toggle feel random. The tray menu
        # stays available when the OS hotkey cannot be registered.
        self._hotkey = hotkey
        logger.warning(
            "Global overlay hotkey unavailable (%s is taken by another app?); "
            "use the tray menu",
            HOTKEY_LABEL,
        )

    # -- public API ---------------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        logger.info("Overlay %s", "enabled" if self._enabled else "disabled")
        if not self._enabled:
            self.hide_panels()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def is_attached(self) -> bool:
        return self._attached

    def panels_visible(self) -> bool:
        return any(panel.isVisible() for panel in self._panels)

    def attach_game(
        self, pid: int, instance_name: str, instance_path: Path
    ) -> bool:
        """Bind the overlay to a running game and make it visible."""
        new_game = int(pid) != self._pid
        self._pid = int(pid)
        self._instance_name = instance_name
        self._instance_path = Path(instance_path)
        self._attached = True
        if new_game or not self._hwnd:
            self._hwnd = _find_window_for_pid(self._pid) or 0
        self._ensure_panels()
        if self.info is not None:
            self.info.set_instance(instance_name)
        if new_game or self._started_at is None:
            self._started_at = datetime.now()
        borderless = make_borderless(self._pid)
        if borderless:
            self._hwnd = _find_window_for_pid(self._pid) or self._hwnd
        logger.info(
            "Overlay attached: pid=%s hwnd=%s borderless=%s enabled=%s",
            self._pid,
            self._hwnd,
            borderless,
            self._enabled,
        )
        if self._enabled:
            self.show_panels()
        self._focus_watch.start()
        return borderless

    def show_panels(self) -> None:
        if not self._enabled:
            logger.info("Overlay show skipped: disabled in settings")
            return
        self._ensure_panels()
        self.apply_theme()
        for panel in self._panels:
            panel.present()
        if self.browser is not None:
            self.browser.resume()
        self._clock.start()
        self._overlay_open = True
        # Give the foreground transfer a moment before the focus watcher may
        # close the overlay again.
        self._focus_guard_until = time.monotonic() + 1.2
        self._focus_overlay()
        logger.info("Overlay panels shown (%s)", self.describe())

    def hide_panels(self, *, restore_focus: bool = True) -> None:
        for panel in self._panels:
            panel.hide()
        if self.browser is not None:
            self.browser.suspend()
        # The music belongs to the shared player: hiding the overlay must not
        # stop it.
        self._clock.stop()
        self._overlay_open = False
        self.save_positions_now()
        if self._panels and restore_focus:
            self._focus_game()
        if self._panels:
            logger.info("Overlay panels hidden")

    def _focus_overlay(self) -> None:
        """Give the mouse/keyboard to the overlay and take it from the game."""
        target = self.browser or (self._panels[0] if self._panels else None)
        if target is None:
            return
        target.activateWindow()
        target.raise_()
        if _force_foreground(int(target.winId())):
            logger.info("Overlay took focus")
        else:
            logger.info("Overlay could not take the foreground")

    def _focus_game(self) -> None:
        """Return input to Minecraft after the overlay is hidden."""
        if not self._attached:
            return
        hwnd = self._hwnd or (_find_window_for_pid(self._pid) or 0)
        if hwnd and _force_foreground(int(hwnd)):
            logger.info("Overlay returned focus to the game")

    def take_screenshot(self) -> Path | None:
        """Save a screenshot of the game into the instance folder."""
        if self._instance_path is None:
            logger.info("Screenshot skipped: no instance attached")
            return None
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        hwnd = self._hwnd or (_find_window_for_pid(self._pid) or 0)
        window_rect = _window_rect(hwnd) if hwnd else None
        visible = [panel for panel in self._panels if panel.isVisible()]
        # The panels are always on top, so they would end up inside the shot.
        for panel in visible:
            panel.hide()
        QApplication.processEvents()
        try:
            shot = _grab_screen(screen)
        finally:
            for panel in visible:
                panel.present()
            if visible:
                self._focus_overlay()
        if shot.isNull():
            logger.warning("Screenshot failed: could not grab the screen")
            return None
        if window_rect is not None:
            # GetWindowRect and QPixmap pixels are both physical pixels, so the
            # window rectangle is used as-is (no devicePixelRatio scaling).
            if QRect(0, 0, shot.width(), shot.height()).contains(window_rect):
                shot = shot.copy(window_rect)
        folder = Path(self._instance_path) / "screenshots"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.exception("Could not create the screenshots folder")
            return None
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target = folder / f"{stamp}.png"
        index = 1
        while target.exists():
            target = folder / f"{stamp}_{index}.png"
            index += 1
        if not shot.save(str(target), "PNG"):
            logger.warning("Screenshot failed: could not write %s", target)
            return None
        logger.info("Screenshot saved: %s", target)
        if self.info is not None:
            self.info.set_status(f"Скриншот: {target.name}")
        self.screenshot_saved.emit(str(target))
        return target

    def toggle(self) -> None:
        # One physical press = one toggle. RegisterHotKey repeats WM_HOTKEY
        # while the keys are held, which made the overlay flicker open/closed.
        now_ts = time.monotonic()
        if now_ts - self._last_toggle < 0.45:
            logger.info("Overlay toggle ignored: debounce")
            return
        self._last_toggle = now_ts
        if not self._enabled:
            logger.info("Overlay toggle ignored: disabled in settings")
            return
        if not self._attached:
            logger.info("Overlay toggle ignored: no game attached yet")
            return
        if self._overlay_open:
            self.hide_panels()
        else:
            self.show_panels()

    def _panel_handles(self) -> set[int]:
        handles: set[int] = set()
        for panel in self._panels:
            if not panel.isVisible():
                continue
            try:
                handles.add(int(panel.winId()))
            except Exception:
                continue
        return handles

    def _watch_focus(self) -> None:
        """Close the overlay when it is not the focused application.

        Without this the panels (always-on-top windows) kept floating above
        the browser or Explorer after the user switched away from the game.
        """
        if not self._overlay_open or not self._panels:
            return
        if not self._hwnd:
            # No game window known (windowed game, pywin32 missing): there is
            # nothing to switch back to, so keep the current behaviour.
            return
        if time.monotonic() < self._focus_guard_until:
            return
        foreground = _foreground_window()
        if not foreground:
            return
        if foreground in self._panel_handles():
            return
        # Our own dialogs (file picker, previews) and popups keep the overlay
        # alive even though they are separate windows.
        if _window_process_id(foreground) == os.getpid():
            return
        logger.info("Overlay closed: foreground window changed")
        self.hide_panels(restore_focus=False)

    def shutdown(self) -> None:
        self.hide_panels(restore_focus=False)
        self._focus_watch.stop()
        if self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None
        for panel in self._panels:
            panel.deleteLater()
        self._panels = []
        self.browser = None
        self.player = None
        self.info = None
        self._attached = False

    # -- panels -------------------------------------------------------------
    def _ensure_panels(self) -> None:
        if self._panels:
            return
        self.browser = OverlayBrowser(self)
        self.player = OverlayPlayer(self, self.music)
        self.info = OverlayInfo(self)
        self.info.screenshot_requested.connect(self.take_screenshot)
        self._panels = [self.browser, self.player, self.info]
        self._restore_positions()
        self.apply_theme()

    def _restore_positions(self) -> None:
        if self._positions_restored:
            return
        self._positions_restored = True
        screen = QGuiApplication.primaryScreen().availableGeometry()
        defaults = {
            "browser": (40, 40, 620, 460),
            "player": (680, 40, 340, 300),
            "info": (40, 520, 420, 170),
        }
        stored: dict = {}
        try:
            stored = dict(self.config.overlay_positions or {})
        except Exception:
            logger.debug("Could not read overlay positions", exc_info=True)
        for key, panel in zip(
            ("browser", "player", "info"),
            (self.browser, self.player, self.info),
        ):
            if panel is None:
                continue
            value = stored.get(key) or defaults[key]
            try:
                x, y, w, h = (int(part) for part in value)
            except (TypeError, ValueError):
                x, y, w, h = defaults[key]
            x = max(screen.left(), min(x, screen.right() - 280))
            y = max(screen.top(), min(y, screen.bottom() - 160))
            panel.setGeometry(x, y, max(280, w), max(160, h))

    def save_positions_later(self) -> None:
        self._save_timer.start()

    def save_positions_now(self) -> None:
        data = {}
        for key, panel in (
            ("browser", self.browser),
            ("player", self.player),
            ("info", self.info),
        ):
            if panel is not None:
                data[key] = [
                    panel.x(),
                    panel.y(),
                    panel.width(),
                    panel.height(),
                ]
        if not data:
            return
        try:
            if self.config.overlay_positions != data:
                self.config.set_overlay_positions(data)
        except Exception:
            logger.debug("Could not persist overlay positions", exc_info=True)

    # -- theme --------------------------------------------------------------
    def apply_theme(self) -> None:
        theme = current_theme()
        accent = theme.accent.name()
        text = theme.text.name()
        muted = theme.text_secondary.name()
        sheet = f"""
            QFrame#OverlayPanelHeader {{
                background: rgba(255, 255, 255, 10);
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
            QLabel#OverlayPanelTitle, QLabel#OverlayInfoTitle {{
                color: {text}; font-weight: 600; font-size: 12px;
            }}
            QLabel#OverlayInfoTime {{
                color: {accent}; font-size: 22px; font-weight: 700;
            }}
            QLabel#OverlayClock {{
                color: {muted}; font-size: 18px; font-weight: 600;
            }}
            QLabel#OverlayTrackTitle {{
                color: {text}; font-size: 13px; font-weight: 600;
            }}
            QLabel#OverlayHint {{
                color: {muted}; font-size: 10px;
            }}
            QPushButton#OverlayButton, QPushButton#OverlayClose {{
                background: rgba(255, 255, 255, 12);
                border: 1px solid rgba(255, 255, 255, 28);
                border-radius: 6px;
                color: {text};
                padding: 0 8px;
            }}
            QPushButton#OverlayButton:hover {{
                background: rgba(255, 255, 255, 24);
            }}
            QLineEdit#OverlayUrl, QListWidget#OverlayPlaylist {{
                background: rgba(255, 255, 255, 8);
                border: 1px solid rgba(255, 255, 255, 24);
                border-radius: 6px;
                color: {text};
                padding: 4px;
            }}
            QListWidget#OverlayPlaylist::item {{
                padding: 3px 6px;
                border-radius: 4px;
            }}
            QListWidget#OverlayPlaylist::item:selected {{
                background: rgba(255, 255, 255, 22);
            }}
            QSlider#OverlaySeek::groove:horizontal {{
                background: rgba(255, 255, 255, 26); height: 4px;
                border-radius: 2px;
            }}
            QSlider#OverlaySeek::sub-page:horizontal {{
                background: {accent}; height: 4px; border-radius: 2px;
            }}
            QSlider#OverlaySeek::handle:horizontal {{
                background: {text}; width: 12px; margin: -4px 0;
                border-radius: 6px;
            }}
            QSlider::groove:horizontal {{
                background: rgba(255, 255, 255, 20); height: 4px;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {accent}; width: 12px; margin: -4px 0;
                border-radius: 6px;
            }}
        """
        for panel in self._panels:
            panel.setStyleSheet(sheet)

    # -- timers -------------------------------------------------------------
    def _tick(self) -> None:
        if self.info is None:
            return
        self.info.clock_label.setText(datetime.now().strftime("%H:%M:%S"))
        if self._started_at is None:
            self._started_at = datetime.now()
        seconds = int((datetime.now() - self._started_at).total_seconds())
        hours, rem = divmod(max(0, seconds), 3600)
        minutes, secs = divmod(rem, 60)
        self.info.time_label.setText(f"{hours:02d}:{minutes:02d}:{secs:02d}")

    # -- diagnostics --------------------------------------------------------
    def describe(self) -> str:
        if not self._panels:
            return "no panels"
        parts = []
        for panel in self._panels:
            geometry = panel.geometry()
            parts.append(
                f"{panel.key}={geometry.x()},{geometry.y()} "
                f"{geometry.width()}x{geometry.height()} "
                f"visible={panel.isVisible()}"
            )
        return "; ".join(parts)
