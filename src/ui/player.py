"""QMediaPlayer-based music player popover."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl
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
    def __init__(self, anchor: QWidget) -> None:
        super().__init__(anchor.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self._anchor = anchor
        self._tracks: list[Path] = []
        self._current = -1
        self._loop = False
        self._closing = False
        self._advancing = False

        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.65)
        self._audio.setMuted(False)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(self._on_error)

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
        self.progress.sliderMoved.connect(self._player.setPosition)
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

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(3)
        controls.addStretch(1)
        self.prev_button = IconButton("prev", size=(34, 34), icon_size=16, radius=17, tooltip="Предыдущий")
        self.play_button = IconButton(
            "play", size=(42, 42), icon_size=18, radius=21, tooltip="Играть", bordered=True
        )
        self.next_button = IconButton("next", size=(34, 34), icon_size=16, radius=17, tooltip="Следующий")
        self.loop_button = IconButton("loop", size=(34, 34), icon_size=15, radius=17, tooltip="Повтор")
        self.loop_button.setCheckable(True)
        self.prev_button.clicked.connect(self.previous)
        self.play_button.clicked.connect(self.toggle_play)
        self.next_button.clicked.connect(self.next)
        self.loop_button.toggled.connect(self._set_loop)
        for button in (self.prev_button, self.play_button, self.next_button, self.loop_button):
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
        self._update_buttons()

    # ------------------------------------------------------------- tracks
    def add_tracks(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Добавить музыку",
            str(Path.home()),
            "Аудио (*.mp3 *.ogg *.wav *.flac *.m4a);;Все файлы (*)",
        )
        if not files:
            return
        for name in files:
            path = Path(name)
            self._tracks.append(path)
            item = QListWidgetItem(path.stem)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.track_list.addItem(item)
        if self._current < 0 and self._tracks:
            self._play_index(0)
        self.status_label.setText(f"Треков: {len(self._tracks)}")

    def _play_item(self, item: QListWidgetItem) -> None:
        self._play_index(self.track_list.row(item))

    def _play_index(self, index: int) -> None:
        if self._closing or not (0 <= index < len(self._tracks)):
            return
        self._current = index
        path = self._tracks[index]
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        logger.info(
            "Music: playing %s (audio muted=%s, volume=%.2f, state=%s)",
            path,
            self._audio.isMuted(),
            self._audio.volume(),
            self._player.playbackState(),
        )
        self.track_list.setCurrentRow(index)
        self.title_label.setText(path.stem)
        self.subtitle_label.setText(path.parent.name or "Локальный файл")
        self.status_label.setText("Загрузка аудио…")
        self._update_buttons()

    def toggle_play(self) -> None:
        if not self._tracks:
            self.add_tracks()
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif self._current >= 0:
            self._player.play()
        else:
            self._play_index(0)
        self._update_buttons()

    def next(self) -> None:
        if not self._tracks:
            return
        self._play_index((self._current + 1) % len(self._tracks))

    def previous(self) -> None:
        if not self._tracks:
            return
        self._play_index((self._current - 1) % len(self._tracks))

    def _set_loop(self, enabled: bool) -> None:
        self._loop = enabled
        self._player.setLoops(
            QMediaPlayer.Loops.Infinite if enabled else 1
        )
        self.loop_button.setToolTip("Повтор включён" if enabled else "Повтор выключен")

    # -------------------------------------------------------------- media
    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        logger.info("Music media status: %s", status)
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self.status_label.setText("Играет")
        if (
            status == QMediaPlayer.MediaStatus.EndOfMedia
            and not self._loop
            and not self._closing
            and not self._advancing
        ):
            self._advancing = True
            QTimer.singleShot(0, self._advance_after_end)

    def _advance_after_end(self) -> None:
        self._advancing = False
        if not self._closing and self._tracks:
            self.next()

    def _on_state(self, _state) -> None:
        self._update_buttons()

    def _update_buttons(self) -> None:
        playing = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.set_icon_name("pause" if playing else "play")
        self.play_button.setToolTip("Пауза" if playing else "Играть")

    def _on_duration(self, duration: int) -> None:
        self.progress.setMaximum(max(0, duration))
        self.duration_label.setText(_format_ms(duration))

    def _on_position(self, position: int) -> None:
        if not self.progress.isSliderDown():
            self.progress.setValue(position)
        self.position_label.setText(_format_ms(position))

    def _on_error(self, *args) -> None:
        logger.error("Music player error: %s", args)
        self.status_label.setText("Не удалось воспроизвести файл.")

    # ----------------------------------------------------------------- ui
    def show_at_anchor(self) -> None:
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
        self._closing = True
        self._advancing = False
        self._player.stop()
        self._player.setSource(QUrl())
        self._player.setAudioOutput(None)
        super().closeEvent(event)


def _format_ms(value: int) -> str:
    seconds = max(0, int(value or 0)) // 1000
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}"
