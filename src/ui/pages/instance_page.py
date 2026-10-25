"""Detail page for a single Minecraft instance."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.launcher import (
    CONTENT_CATEGORIES,
    LOADER_ICONS,
    Instance,
    format_last_played,
    format_playtime,
)
from src.ui.pages import Page
from src.ui.widgets import CapsLabel, IconBadge, IconButton, PrimaryButton


def format_session_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class StatChip(QFrame):
    def __init__(self, label: str, value: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatChip")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(4)
        caption = QLabel(label)
        caption.setObjectName("Caption")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("FieldLabel")
        self.value_label.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class ContentTile(QPushButton):
    """Square-ish button for one content category."""

    def __init__(
        self,
        key: str,
        title: str,
        icon_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("ContentTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"Открыть раздел {title}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(IconBadge(icon_name, size=40, icon_size=19, radius=11))
        top.addStretch(1)
        self.count_label = QLabel("0")
        self.count_label.setObjectName("ContentTileCount")
        top.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        layout.addStretch(1)

        title_label = QLabel(title)
        title_label.setObjectName("ContentTileTitle")
        layout.addWidget(title_label)
        layout.addSpacing(3)
        self.hint_label = QLabel("Открыть")
        self.hint_label.setObjectName("ContentFileMeta")
        layout.addWidget(self.hint_label)

        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_count(self, count: int) -> None:
        self.count_label.setText(str(max(0, int(count))))
        self.hint_label.setText("файлов нет" if count == 0 else "открыть раздел")


class InstancePage(Page):
    back_requested = Signal()
    play_requested = Signal()
    settings_requested = Signal()
    backup_requested = Signal()
    share_requested = Signal()
    delete_requested = Signal()
    open_folder_requested = Signal()
    content_requested = Signal(str)
    modpack_update_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, margins=(30, 20, 30, 26), spacing=16)
        self._instance: Instance | None = None
        self._memory_mb = 4096
        self._java_hint = ""

        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        self.back_button = IconButton(
            "chevron_left",
            size=(36, 36),
            icon_size=18,
            radius=10,
            tooltip="Назад к библиотеке",
        )
        self.back_button.clicked.connect(self.back_requested.emit)
        header_row.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignTop)
        self.header_icon = QLabel()
        self.header_icon.setFixedSize(44, 44)
        self.header_icon.setStyleSheet("border-radius: 8px;")
        self.header_icon.hide()
        header_row.addWidget(self.header_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(3)
        self.title_label = QLabel("Экземпляр")
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel("Minecraft Java Edition")
        self.subtitle_label.setObjectName("PageSubtitle")
        title_column.addWidget(self.title_label)
        title_column.addWidget(self.subtitle_label)
        header_row.addLayout(title_column, 1)

        self.run_state = QLabel("● Готов к запуску")
        self.run_state.setObjectName("RunState")
        self.run_state.setProperty("state", "ready")
        header_row.addWidget(self.run_state, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addWidget(header)

        hero = QFrame()
        hero.setObjectName("InstanceHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(26, 22, 26, 22)
        hero_layout.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(16)
        self.hero_badge = IconBadge("cube", size=64, icon_size=29, radius=18)
        top.addWidget(self.hero_badge, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setContentsMargins(0, 1, 0, 0)
        info.setSpacing(4)
        info.addWidget(CapsLabel("MINECRAFT JAVA EDITION", size=9, spacing=1.7, accent=True))
        self.hero_title = QLabel("Vanilla")
        self.hero_title.setObjectName("InstanceHeroTitle")
        info.addWidget(self.hero_title)
        self.hero_meta = QLabel("Ванильная сборка")
        self.hero_meta.setObjectName("FieldHint")
        info.addWidget(self.hero_meta)
        top.addLayout(info, 1)

        playtime_column = QVBoxLayout()
        playtime_column.setContentsMargins(0, 2, 0, 0)
        playtime_column.setSpacing(3)
        playtime_caption = QLabel("НАИГРАНО")
        playtime_caption.setObjectName("Caption")
        playtime_caption.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.playtime_value = QLabel("0 мин")
        self.playtime_value.setObjectName("InstancePlaytime")
        self.playtime_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        playtime_column.addWidget(playtime_caption)
        playtime_column.addWidget(self.playtime_value)
        top.addLayout(playtime_column)
        hero_layout.addLayout(top)
        hero_layout.addSpacing(20)

        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        hero_layout.addWidget(divider)
        hero_layout.addSpacing(18)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        self.play_button = PrimaryButton("Играть", "play", height=56)
        self.play_button.setMinimumWidth(270)
        self.play_button.clicked.connect(self.play_requested.emit)
        actions.addWidget(self.play_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setTextVisible(False)
        self.download_progress.setFixedWidth(220)
        self.download_progress.setFixedHeight(8)
        self.download_progress.hide()
        actions.addWidget(self.download_progress, 0, Qt.AlignmentFlag.AlignVCenter)

        self.settings_button = QPushButton("Настройки экземпляра")
        self.settings_button.setObjectName("GhostButton")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setFixedHeight(46)
        self.settings_button.clicked.connect(self.settings_requested.emit)
        actions.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignVCenter)
        actions.addStretch(1)
        hero_layout.addLayout(actions)
        hero_layout.addSpacing(12)

        self.status_label = QLabel(
            "Игра скачана. Java нужной версии будет проверена автоматически."
        )
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        hero_layout.addWidget(self.status_label)

        self.timer_label = QLabel("")
        self.timer_label.setObjectName("InstanceTimer")
        self.timer_label.hide()
        hero_layout.addSpacing(5)
        hero_layout.addWidget(self.timer_label)
        self.body.addWidget(hero)

        self.modpack_card = QFrame()
        self.modpack_card.setObjectName("InstallInfo")
        modpack_layout = QHBoxLayout(self.modpack_card)
        modpack_layout.setContentsMargins(16, 10, 16, 10)
        modpack_layout.setSpacing(12)
        modpack_text = QVBoxLayout()
        modpack_text.setSpacing(2)
        self.modpack_title = QLabel("")
        self.modpack_title.setObjectName("FieldLabel")
        modpack_text.addWidget(self.modpack_title)
        self.modpack_meta = QLabel("")
        self.modpack_meta.setObjectName("Caption")
        modpack_text.addWidget(self.modpack_meta)
        modpack_layout.addLayout(modpack_text, 1)
        self.modpack_update_button = QPushButton("Проверить обновления")
        self.modpack_update_button.setObjectName("GhostButton")
        self.modpack_update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.modpack_update_button.clicked.connect(
            self.modpack_update_requested.emit
        )
        modpack_layout.addWidget(self.modpack_update_button)
        self.modpack_card.hide()
        self.body.addWidget(self.modpack_card)

        content_header = QHBoxLayout()
        content_header.setContentsMargins(2, 2, 2, 0)
        content_header.setSpacing(10)
        content_title = QLabel("Содержимое")
        content_title.setObjectName("SectionTitle")
        content_header.addWidget(content_title)
        content_header.addStretch(1)
        content_hint = QLabel("Включайте и отключайте файлы внутри разделов")
        content_hint.setObjectName("Muted")
        content_header.addWidget(content_hint)
        self.body.addLayout(content_header)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(10)
        self.content_tiles: dict[str, ContentTile] = {}
        for key, category in CONTENT_CATEGORIES.items():
            tile = ContentTile(key, category.title, category.icon)
            tile.clicked.connect(
                lambda _checked=False, value=key: self.content_requested.emit(value)
            )
            self.content_tiles[key] = tile
            content_row.addWidget(tile)
        self.body.addLayout(content_row)

        maintenance = QHBoxLayout()
        maintenance.setContentsMargins(0, 0, 0, 0)
        maintenance.setSpacing(10)
        self.backup_button = QPushButton("Бэкап")
        self.backup_button.setObjectName("GhostButton")
        self.backup_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.backup_button.setFixedHeight(40)
        self.backup_button.clicked.connect(self.backup_requested.emit)
        maintenance.addWidget(self.backup_button)

        self.open_folder_button = QPushButton("Открыть папку")
        self.open_folder_button.setObjectName("GhostButton")
        self.open_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_button.setFixedHeight(40)
        self.open_folder_button.clicked.connect(self.open_folder_requested.emit)
        maintenance.addWidget(self.open_folder_button)

        self.share_button = QPushButton("Поделиться")
        self.share_button.setObjectName("GhostButton")
        self.share_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.share_button.setFixedHeight(40)
        self.share_button.setToolTip("Экспортировать сборку в .fionixpack")
        self.share_button.clicked.connect(self.share_requested.emit)
        maintenance.addWidget(self.share_button)
        maintenance.addStretch(1)

        self.delete_button = QPushButton("Удалить экземпляр")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.setFixedHeight(40)
        self.delete_button.setToolTip("Полностью удалить папку этого экземпляра")
        self.delete_button.clicked.connect(self.delete_requested.emit)
        maintenance.addWidget(self.delete_button)
        self.body.addLayout(maintenance)

        stats = QHBoxLayout()
        stats.setContentsMargins(0, 2, 0, 0)
        stats.setSpacing(12)
        self.java_chip = StatChip("JAVA", "Проверится при запуске")
        self.memory_chip = StatChip("ПАМЯТЬ", "4 ГБ")
        self.last_played_chip = StatChip("ПОСЛЕДНИЙ ЗАПУСК", "Ещё не запускался")
        stats.addWidget(self.java_chip)
        stats.addWidget(self.memory_chip)
        stats.addWidget(self.last_played_chip)
        self.body.addLayout(stats)

        path_row = QFrame()
        path_row.setObjectName("InstallInfo")
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(14, 10, 14, 10)
        path_layout.setSpacing(10)
        folder_caption = QLabel("ПАПКА")
        folder_caption.setObjectName("Caption")
        self.path_label = QLabel("—")
        self.path_label.setObjectName("FieldHint")
        self.path_label.setWordWrap(True)
        path_layout.addWidget(folder_caption)
        path_layout.addWidget(self.path_label, 1)
        self.body.addWidget(path_row)

        note = QLabel(
            "Запуск выполняется под выбранным аккаунтом. "
            "Лаунчер свернётся в трей и вернётся после закрытия Minecraft."
        )
        note.setObjectName("Caption")
        note.setWordWrap(True)
        self.body.addWidget(note)
        self.body.addStretch(1)

    # ---------------------------------------------------------------- data
    def load_instance(
        self,
        instance: Instance,
        *,
        java_hint: str = "",
        memory_mb: int = 4096,
        content_counts: dict[str, int] | None = None,
    ) -> None:
        self._instance = instance
        self._java_hint = java_hint
        self._memory_mb = int(memory_mb)
        self.title_label.setText(instance.name)
        icon = QPixmap(instance.icon_path) if instance.icon_path else QPixmap()
        if icon.isNull():
            self.header_icon.hide()
        else:
            self.header_icon.setPixmap(
                icon.scaled(
                    44,
                    44,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.header_icon.show()
        self.subtitle_label.setText(
            f"{instance.loader_name} · Minecraft {instance.version}"
        )
        self.hero_badge.set_icon(LOADER_ICONS.get(instance.loader, "cube"))
        self.hero_title.setText(instance.name)
        loader_meta = instance.loader_name
        if instance.loader_version:
            loader_meta += f" {instance.loader_version}"
        self.hero_meta.setText(f"{loader_meta} · Minecraft {instance.version}")
        self.playtime_value.setText(format_playtime(instance.playtime_seconds))
        self.memory_chip.set_value(f"{self._memory_mb // 1024} ГБ")
        self.java_chip.set_value(java_hint or f"Java {instance.java_major} · автоматически")
        self.last_played_chip.set_value(format_last_played(instance.last_played_at))
        path_parts = instance.path.parts
        short_path = (
            f"…{os.sep}{os.sep.join(path_parts[-2:])}"
            if len(path_parts) >= 2
            else str(instance.path)
        )
        self.path_label.setText(short_path)
        self.path_label.setToolTip(str(instance.path))
        self.set_content_counts(content_counts or {})
        if instance.modpack_name:
            self.modpack_title.setText(instance.modpack_name)
            author = instance.modpack_author or "неизвестный автор"
            version = instance.modpack_version or "версия не указана"
            source = instance.modpack_source or "modpack"
            self.modpack_meta.setText(f"{author} · {version} · {source}")
            self.modpack_card.show()
        else:
            self.modpack_card.hide()
        if instance.pending:
            self.set_download_required()
            return
        self._set_state("ready", "● Готов к запуску")
        self.status_label.setText(
            "Игра скачана. Java нужной версии будет проверена автоматически."
        )
        self.timer_label.hide()
        self.play_button.setEnabled(True)
        self.play_button.setText("Играть")
        self.play_button.set_icon_name("play")
        self.download_progress.hide()
        self._set_maintenance_enabled(True)

    def set_download_required(self) -> None:
        self._set_state("busy", "● Ожидает загрузки")
        self.status_label.setText(
            "Экземпляр уже в списке. Нажмите «Загрузить», чтобы скачать игру и ядро."
        )
        self.timer_label.hide()
        self.play_button.setEnabled(True)
        self.play_button.setText("Загрузить")
        self.play_button.set_icon_name("download")
        self.download_progress.hide()
        # The metadata and folders exist immediately, so management and
        # content tabs must remain usable while the base game downloads.
        self.settings_button.setEnabled(True)
        self.backup_button.setEnabled(False)
        self.open_folder_button.setEnabled(True)
        self.share_button.setEnabled(False)
        self.delete_button.setEnabled(True)
        for tile in self.content_tiles.values():
            tile.setEnabled(True)

    def set_downloading(self, percent: int, detail: str = "") -> None:
        value = max(0, min(100, int(percent)))
        self._set_state("busy", f"● Загрузка {value}%")
        self.play_button.setEnabled(False)
        self.play_button.setText(f"Загрузка {value}%")
        self.play_button.set_icon_name("download")
        self.download_progress.setValue(value)
        self.download_progress.show()
        if detail:
            self.status_label.setText(detail)

    def set_content_counts(self, counts: dict[str, int]) -> None:
        for key, tile in self.content_tiles.items():
            tile.set_count(int(counts.get(key, 0)))

    def update_java_hint(self, hint: str) -> None:
        self._java_hint = hint
        if self._instance is not None:
            self.java_chip.set_value(
                hint or f"Java {self._instance.java_major} · автоматически"
            )

    def update_memory(self, memory_mb: int) -> None:
        self._memory_mb = int(memory_mb)
        self.memory_chip.set_value(f"{self._memory_mb // 1024} ГБ")

    def set_busy(self, message: str) -> None:
        self._set_state("busy", f"● {message}")
        self.play_button.setEnabled(False)
        self._set_maintenance_enabled(False)
        self.status_label.setText(message)
        self.timer_label.hide()

    def set_game_running(self) -> None:
        self._set_state("playing", "● Minecraft запущен")
        self.play_button.setEnabled(False)
        self.play_button.setText("Игра запущена")
        self.play_button.set_icon_name("check")
        self._set_maintenance_enabled(False)
        self.status_label.setText(
            "Лаунчер свёрнут в системный трей и вернётся после закрытия игры."
        )
        self.timer_label.setText("00:00:00")
        self.timer_label.show()

    def update_running(self, session_seconds: int, total_seconds: int) -> None:
        self.timer_label.setText(format_session_time(session_seconds))
        self.playtime_value.setText(format_playtime(total_seconds))

    def set_game_finished(self, instance: Instance, exit_code: int) -> None:
        self._instance = instance
        self.playtime_value.setText(format_playtime(instance.playtime_seconds))
        self.last_played_chip.set_value(format_last_played(instance.last_played_at))
        self.timer_label.hide()
        self.play_button.setEnabled(True)
        self.play_button.setText("Играть")
        self.play_button.set_icon_name("play")
        self._set_maintenance_enabled(True)
        if exit_code == 0:
            self._set_state("ready", "● Готов к запуску")
            self.status_label.setText(
                f"Minecraft закрыт. Всего наиграно: {format_playtime(instance.playtime_seconds)}."
            )
        else:
            self._set_state("error", f"● Игра завершилась с кодом {exit_code}")
            self.status_label.setText(
                "Игра завершилась с ошибкой. Подробности — в логе экземпляра "
                "в папке logs."
            )

    def set_error(self, message: str) -> None:
        self._set_state("error", "● Ошибка запуска")
        self.status_label.setText(message)
        self.play_button.setEnabled(True)
        self.play_button.setText("Играть")
        self.play_button.set_icon_name("play")
        self._set_maintenance_enabled(True)

    def set_operation_note(self, message: str, *, error: bool = False) -> None:
        self._set_state(
            "error" if error else "ready", "● " + ("Ошибка" if error else "Готово")
        )
        self.status_label.setText(message)

    def set_install_required(self, message: str) -> None:
        self._set_state("error", "● Требуется установка")
        self.status_label.setText(message)

    def current_instance(self) -> Instance | None:
        return self._instance

    # -------------------------------------------------------------- helpers
    def _set_maintenance_enabled(self, enabled: bool) -> None:
        self.settings_button.setEnabled(enabled)
        self.backup_button.setEnabled(enabled)
        self.open_folder_button.setEnabled(enabled)
        self.share_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        for tile in self.content_tiles.values():
            tile.setEnabled(enabled)

    def _set_state(self, state: str, text: str) -> None:
        self.run_state.setText(text)
        self.run_state.setProperty("state", state)
        self.run_state.style().unpolish(self.run_state)
        self.run_state.style().polish(self.run_state)
        self.run_state.update()
