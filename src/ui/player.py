"""QMediaPlayer-based music playback shared by the launcher and the overlay.

``MusicPlayer`` owns the only ``QMediaPlayer``/``QAudioOutput`` instance of the
application.  ``MusicPopover`` (title bar) and the overlay player panel are thin
views on top of it, so a track started in one place keeps playing in the other
and survives both the popover being closed and the overlay being hidden.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.core.theme import current_theme
from src.ui import icons
from src.ui.widgets import CapsLabel, IconBadge, IconButton

logger = logging.getLogger(__name__)

AUDIO_FILTER = "Аудио (*.mp3 *.ogg *.wav *.flac *.m4a);;Все файлы (*)"

REPEAT_LABELS = {
    "off": "Повтор: выкл",
    "one": "Повтор: один раз",
    "all": "Повтор: бесконечно",
}


def format_ms(value: int) -> str:
    seconds = max(0, int(value or 0)) // 1000
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}"


class MusicPlayer(QObject):
    """The single shared music player of the application."""

    track_changed = Signal(str, str)  # title, subtitle
    tracks_changed = Signal()
    position_changed = Signal(int)
    duration_changed = Signal(int)
    state_changed = Signal(bool)  # is_playing
    volume_changed = Signal(int)  # 0..100
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tracks: list[Path] = []
        self._current = -1
        self._shuffle = False
        self._repeat = "off"
        self._advancing = False

        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.65)
        self.audio.setMuted(False)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.positionChanged.connect(self._emit_position)
        self.player.durationChanged.connect(self._emit_duration)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(self._on_error)

    # ------------------------------------------------------------- state
    @property
    def tracks(self) -> list[Path]:
        return list(self._tracks)

    @property
    def current_index(self) -> int:
        return self._current

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    @property
    def repeat(self) -> str:
        return self._repeat

    def is_playing(self) -> bool:
        return (
            self.player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        )

    def has_tracks(self) -> bool:
        return bool(self._tracks)

    def position(self) -> int:
        return int(self.player.position())

    def duration(self) -> int:
        return int(self.player.duration())

    def volume(self) -> int:
        return max(0, min(100, int(round(self.audio.volume() * 100))))

    def track_title(self) -> str:
        if 0 <= self._current < len(self._tracks):
            return self._tracks[self._current].stem
        return "Ничего не играет"

    def track_subtitle(self) -> str:
        if 0 <= self._current < len(self._tracks):
            return self._tracks[self._current].parent.name or "Локальный файл"
        return "Добавьте MP3, чтобы начать"

    # ----------------------------------------------------------- actions
    def add_tracks(self, paths: Iterable[Path | str]) -> int:
        added = 0
        for raw in paths:
            path = Path(raw)
            if path in self._tracks:
                continue
            self._tracks.append(path)
            added += 1
        if added:
            self.tracks_changed.emit()
            if self._current < 0:
                self.play_index(0)
        return added

    def play_index(self, index: int) -> None:
        if not (0 <= index < len(self._tracks)):
            return
        self._current = index
        path = self._tracks[index]
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self.player.play()
        logger.info("Music: playing %s", path)
        self.track_changed.emit(self.track_title(), self.track_subtitle())

    def toggle_play(self) -> None:
        if not self._tracks:
            return
        if self.is_playing():
            self.player.pause()
        elif self._current >= 0:
            self.player.play()
        else:
            self.play_index(0)

    def _next_index(self, step: int) -> int:
        if self._shuffle and len(self._tracks) > 1:
            choices = [
                index
                for index in range(len(self._tracks))
                if index != self._current
            ]
            return random.choice(choices)
        return (self._current + step) % len(self._tracks)

    def next_track(self) -> None:
        if self._tracks:
            self.play_index(self._next_index(1))

    def previous_track(self) -> None:
        if self._tracks:
            self.play_index(self._next_index(-1))

    def seek(self, position_ms: int) -> None:
        self.player.setPosition(max(0, int(position_ms)))

    def set_volume(self, value: int) -> None:
        level = max(0, min(100, int(value)))
        self.audio.setVolume(level / 100.0)
        self.volume_changed.emit(level)

    def set_shuffle(self, enabled: bool) -> None:
        self._shuffle = bool(enabled)

    def cycle_repeat(self) -> str:
        self._repeat = {"off": "one", "one": "all", "all": "off"}[self._repeat]
        return self._repeat

    def stop(self) -> None:
        self.player.stop()

    # ------------------------------------------------------------- media
    def _emit_position(self, value: int) -> None:
        # QMediaPlayer emits qlonglong; the views use a plain int signal.
        self.position_changed.emit(int(value))

    def _emit_duration(self, value: int) -> None:
        self.duration_changed.emit(int(value))

    def _on_state(self, _state) -> None:
        self.state_changed.emit(self.is_playing())

    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if self._advancing:
            return
        self._advancing = True
        QTimer.singleShot(0, self._advance_after_end)

    def _advance_after_end(self) -> None:
        self._advancing = False
        if not self._tracks:
            return
        if self._repeat == "one" and self._current >= 0:
            self.play_index(self._current)
        elif self._repeat == "all":
            self.next_track()
        else:
            self.state_changed.emit(False)

    def _on_error(self, *args) -> None:
        logger.error("Music player error: %s", args)
        self.error_occurred.emit("Не удалось воспроизвести файл.")


class MusicArt(QWidget):
    def __init__(self, parent: QWidget | None = None, *, size: int = 58) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        painter.fillPath(path, theme.accent)
        icons.draw_icon(
            painter,
            "music",
            rect.adjusted(15, 15, -15, -15),
            QColor(255, 255, 255, 235),
            1.8,
        )


class MusicPopover(QWidget):
    """Title-bar music popover -- a view on :class:`MusicPlayer`."""

    def __init__(self, anchor: QWidget, music: MusicPlayer) -> None:
        # Qt.Popup closes when a modal QFileDialog takes focus; with
        # WA_DeleteOnClose this destroyed the player before tracks were added.
        super().__init__(
            anchor.window(),
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self._anchor = anchor
        self.music = music

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 18)
        panel = QFrame()
        panel.setObjectName("Popover")
        panel.setFixedWidth(358)
        outer.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(17, 14, 17, 15)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(CapsLabel("FIONIX PLAYER", size=9, spacing=1.8, accent=True))
        header.addStretch(1)
        close = IconButton("close", size=(26, 26), icon_size=12, radius=8, tooltip="Закрыть плеер")
        close.clicked.connect(self.close)
        header.addWidget(close)
        layout.addLayout(header)
        layout.addSpacing(12)

        track_row = QHBoxLayout()
        track_row.setContentsMargins(0, 0, 0, 0)
        track_row.setSpacing(12)
        track_row.addWidget(MusicArt(size=58))
        info = QVBoxLayout()
        info.setContentsMargins(0, 2, 0, 0)
        info.setSpacing(3)
        self.title_label = QLabel("Ничего не играет")
        self.title_label.setObjectName("PopoverTitle")
        self.title_label.setWordWrap(True)
        self.subtitle_label = QLabel("Добавьте MP3, чтобы начать")
        self.subtitle_label.setObjectName("FieldHint")
        info.addWidget(self.title_label)
        info.addWidget(self.subtitle_label)
        info.addStretch(1)
        track_row.addLayout(info, 1)
        layout.addLayout(track_row)
        layout.addSpacing(10)
        self.add_tracks_button = QPushButton("＋  Добавить треки")
        self.add_tracks_button.setObjectName("SoftButton")
        self.add_tracks_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_tracks_button.setFixedHeight(36)
        self.add_tracks_button.clicked.connect(self.add_tracks)
        layout.addWidget(self.add_tracks_button)
        layout.addSpacing(10)

        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 0)
        self.progress.sliderMoved.connect(self.music.seek)
        layout.addWidget(self.progress)
        times = QHBoxLayout()
        times.setContentsMargins(0, 1, 0, 0)
        self.position_label = QLabel("0:00")
        self.position_label.setObjectName("Caption")
        self.duration_label = QLabel("0:00")
        self.duration_label.setObjectName("Caption")
        times.addWidget(self.position_label)
        times.addStretch(1)
        times.addWidget(self.duration_label)
        layout.addLayout(times)
        layout.addSpacing(8)

        volume_row = QHBoxLayout()
        volume_row.setContentsMargins(0, 0, 0, 0)
        volume_row.setSpacing(8)
        volume_row.addWidget(QLabel("Громкость"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.music.volume())
        self.volume_slider.setFixedHeight(18)
        self.volume_slider.valueChanged.connect(self.music.set_volume)
        volume_row.addWidget(self.volume_slider, 1)
        self.volume_label = QLabel(f"{self.music.volume()}%")
        self.volume_label.setObjectName("Caption")
        self.volume_label.setFixedWidth(34)
        volume_row.addWidget(self.volume_label)
        layout.addLayout(volume_row)
        layout.addSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(6)
        self.shuffle_button = QPushButton(
            "Перемешать: вкл" if self.music.shuffle else "Перемешать: выкл"
        )
        self.shuffle_button.setObjectName("SoftButton")
        self.shuffle_button.setCheckable(True)
        self.shuffle_button.setChecked(self.music.shuffle)
        self.shuffle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.shuffle_button.setFixedHeight(27)
        self.shuffle_button.toggled.connect(self._set_shuffle)
        self.repeat_button = QPushButton(REPEAT_LABELS[self.music.repeat])
        self.repeat_button.setObjectName("SoftButton")
        self.repeat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.repeat_button.setFixedHeight(27)
        self.repeat_button.clicked.connect(self._cycle_repeat)
        mode_row.addWidget(self.shuffle_button, 1)
        mode_row.addWidget(self.repeat_button, 1)
        layout.addLayout(mode_row)
        layout.addSpacing(8)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(3)
        controls.addStretch(1)
        self.prev_button = IconButton("prev", size=(34, 34), icon_size=16, radius=17, tooltip="Предыдущий")
        self.play_button = IconButton(
            "play", size=(42, 42), icon_size=18, radius=21, tooltip="Играть", bordered=True
        )
        self.next_button = IconButton("next", size=(34, 34), icon_size=16, radius=17, tooltip="Следующий")
        self.prev_button.clicked.connect(self.music.previous_track)
        self.play_button.clicked.connect(self.music.toggle_play)
        self.next_button.clicked.connect(self.music.next_track)
        for button in (self.prev_button, self.play_button, self.next_button):
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        layout.addSpacing(10)

        list_header = QHBoxLayout()
        list_header.addWidget(CapsLabel("ПЛЕЙЛИСТ", size=8, spacing=1.2, muted=True))
        list_header.addStretch(1)
        layout.addLayout(list_header)
        layout.addSpacing(5)

        self.track_list = QListWidget()
        self.track_list.setObjectName("Playlist")
        self.track_list.setMinimumHeight(120)
        self.track_list.setMaximumHeight(160)
        self.track_list.itemDoubleClicked.connect(self._play_item)
        layout.addWidget(self.track_list)
        self.status_label = QLabel("Поддерживаются MP3 и другие аудиофайлы")
        self.status_label.setObjectName("Caption")
        self.status_label.setWordWrap(True)
        layout.addSpacing(6)
        layout.addWidget(self.status_label)

        self.music.track_changed.connect(self._on_track_changed)
        self.music.tracks_changed.connect(self._sync_playlist)
        self.music.position_changed.connect(self._on_position)
        self.music.duration_changed.connect(self._on_duration)
        self.music.state_changed.connect(self._on_state)
        self.music.volume_changed.connect(self._on_volume_changed)
        self.music.error_occurred.connect(self._on_error)
        self._sync_all()

    # ------------------------------------------------------------- sync
    def _sync_all(self) -> None:
        self._sync_playlist()
        self.title_label.setText(self.music.track_title())
        self.subtitle_label.setText(self.music.track_subtitle())
        self.progress.setMaximum(max(0, self.music.duration()))
        self.progress.setValue(min(self.music.position(), self.progress.maximum()))
        self.duration_label.setText(format_ms(self.music.duration()))
        self.position_label.setText(format_ms(self.music.position()))
        if self.music.has_tracks():
            self.status_label.setText(f"Треков: {len(self.music.tracks)}")
        self._on_state(self.music.is_playing())

    def _sync_playlist(self) -> None:
        self.track_list.clear()
        for path in self.music.tracks:
            item = QListWidgetItem(path.stem)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.track_list.addItem(item)
        if self.music.current_index >= 0:
            self.track_list.setCurrentRow(self.music.current_index)

    # ------------------------------------------------------------- tracks
    def add_tracks(self) -> None:
        parent = self.parentWidget()
        files, _ = QFileDialog.getOpenFileNames(
            parent if parent is not None else None,
            "Добавить музыку",
            str(Path.home()),
            AUDIO_FILTER,
        )
        if not files:
            return
        self.music.add_tracks(Path(name) for name in files)
        self._sync_playlist()
        self.status_label.setText(f"Треков: {len(self.music.tracks)}")

    def _play_item(self, item: QListWidgetItem) -> None:
        self.music.play_index(self.track_list.row(item))

    def _set_shuffle(self, enabled: bool) -> None:
        self.music.set_shuffle(enabled)
        self.shuffle_button.setText(
            "Перемешать: вкл" if enabled else "Перемешать: выкл"
        )

    def _cycle_repeat(self) -> None:
        self.repeat_button.setText(REPEAT_LABELS[self.music.cycle_repeat()])

    def _on_volume_changed(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(value)
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(f"{value}%")

    # -------------------------------------------------------------- media
    def _on_track_changed(self, title: str, subtitle: str) -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.status_label.setText("Играет")
        self._sync_playlist()

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

    def _on_error(self, message: str) -> None:
        self.status_label.setText(message)

    # ----------------------------------------------------------------- ui
    def show_at_anchor(self) -> None:
        self._sync_all()
        self.adjustSize()
        anchor_rect = self._anchor.mapToGlobal(QPoint(0, self._anchor.height()))
        x = anchor_rect.x() + self._anchor.width() - self.width() + 14
        y = anchor_rect.y() + 6
        screen = QGuiApplication.screenAt(anchor_rect)
        if screen is not None:
            available = screen.availableGeometry()
            x = max(available.left() + 8, min(x, available.right() - self.width() - 8))
            y = max(available.top() + 8, min(y, available.bottom() - self.height() - 8))
        self.move(x, y)
        self.show()
        self.raise_()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        # Playback belongs to the shared MusicPlayer: closing the popover (or
        # starting the game) must not interrupt the music.
        super().closeEvent(event)
