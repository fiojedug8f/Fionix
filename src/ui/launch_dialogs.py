"""Dialogs for creating instances, downloading files and preparing Java."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QThreadPool,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.launcher import (
    LOADER_ICONS,
    JavaRuntime,
    LauncherService,
    VersionEntry,
    format_playtime,
    loader_label,
)
from src.core.launcher import Instance
from src.ui.tasks import (
    FetchVersionsSignals,
    FetchVersionsTask,
    InstallTask,
    JavaTask,
)
from src.ui.widgets import CapsLabel, GlassComboBox, IconBadge, IconButton


class OverlayDialog(QDialog):
    """Frameless modal card over a dimmed launcher window."""

    def __init__(self, parent: QWidget, card_width: int) -> None:
        super().__init__(parent)
        self._parent_window = parent.window()
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.card = QFrame()
        self.card.setObjectName("DialogCard")
        self.card.setFixedWidth(card_width)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(54)
        shadow.setOffset(0, 18)
        shadow.setColor(QColor(0, 0, 0, 190))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)

        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(28, 24, 28, 26)
        self.card_layout.setSpacing(0)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(150)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.setGeometry(self._parent_window.geometry())
        self.setWindowOpacity(0.0)
        super().showEvent(event)
        self._fade.start()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(4, 4, 10, 132))

    def _on_escape(self) -> None:
        self.reject()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape:
            self._on_escape()
            return
        super().keyPressEvent(event)


class CoreTile(QPushButton):
    """Large selectable card for a Minecraft core."""

    def __init__(self, loader: str, title: str, subtitle: str, badge: str) -> None:
        super().__init__()
        self.loader = loader
        self.setCheckable(True)
        self.setObjectName("CoreTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(94)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"Ядро {title}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(IconBadge(LOADER_ICONS[loader], size=30, icon_size=16, radius=9))
        top.addStretch(1)
        badge_label = QLabel(badge)
        badge_label.setObjectName("Tag")
        top.addWidget(badge_label, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        layout.addSpacing(5)

        title_label = QLabel(title)
        title_label.setObjectName("CoreTileTitle")
        layout.addWidget(title_label)
        layout.addSpacing(2)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("CoreTileSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)

        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)


class CreateInstanceDialog(OverlayDialog):
    """Version and core selection with a live compatibility summary."""

    def __init__(
        self,
        service: LauncherService,
        parent: QWidget,
        *,
        auto_fetch: bool = True,
    ) -> None:
        super().__init__(parent, card_width=668)
        self._service = service
        self._entries: dict[str, VersionEntry] = {}
        self.selected_version: str | None = None
        self.selected_loader = "vanilla"
        self.selected_optimize = False
        self._fetch_task: FetchVersionsTask | None = None
        self._fetch_signals: FetchVersionsSignals | None = None
        self._user_selected = False
        self._core_tiles: dict[str, CoreTile] = {}
        self._core_group = QButtonGroup(self)
        self._core_group.setExclusive(True)

        self._build_ui()
        self._set_catalog(service.default_catalog())
        self._core_tiles["vanilla"].setChecked(True)
        self._update_summary()
        if auto_fetch:
            self._fetch_versions()
        else:
            self.fetch_status.setText("Популярные версии")

    # ------------------------------------------------------------------ ui
    def _build_ui(self) -> None:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(IconBadge("cube", size=48, icon_size=22, radius=14))
        header.addStretch(1)
        close = IconButton("close", size=(30, 30), icon_size=13, radius=9, tooltip="Закрыть")
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.card_layout.addLayout(header)
        self.card_layout.addSpacing(10)

        self.card_layout.addWidget(CapsLabel("НОВЫЙ ЭКЗЕМПЛЯР", size=9, spacing=2.0, accent=True))
        self.card_layout.addSpacing(6)
        title = QLabel("Соберите новую сборку")
        title.setObjectName("DialogTitle")
        self.card_layout.addWidget(title)
        self.card_layout.addSpacing(5)
        subtitle = QLabel(
            "Выберите версию Minecraft и ядро. Игра и нужная Java "
            "устанавливаются в отдельную папку экземпляра."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        self.card_layout.addWidget(subtitle)
        self.card_layout.addSpacing(10)

        version_label = QLabel("Версия Minecraft")
        version_label.setObjectName("FieldLabel")
        self.card_layout.addWidget(version_label)
        self.card_layout.addSpacing(6)
        self.versions_combo = GlassComboBox()
        self.versions_combo.setAccessibleName("Версия Minecraft")
        self.versions_combo.setMinimumHeight(38)
        self.versions_combo.currentIndexChanged.connect(self._on_version_changed)
        self.versions_combo.activated.connect(self._mark_user_selection)
        self.card_layout.addWidget(self.versions_combo)
        self.card_layout.addSpacing(10)

        core_label = QLabel("Ядро сборки")
        core_label.setObjectName("FieldLabel")
        self.card_layout.addWidget(core_label)
        self.card_layout.addSpacing(6)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        specs = (
            ("vanilla", "Vanilla", "Чистая игра", "АВТО"),
            ("forge", "Forge", "Модпаки · Embeddium", "АВТО"),
            ("neoforge", "NeoForge", "Современный Forge", "АВТО"),
            ("fabric", "Fabric", "Моды · Sodium", "АВТО"),
            ("quilt", "Quilt", "Моды · QSL", "АВТО"),
            ("optifine", "OptiFine", "Шейдеры · вручную", "ВРУЧНУЮ"),
        )
        for index, (loader, title_text, subtitle_text, badge) in enumerate(specs):
            tile = CoreTile(loader, title_text, subtitle_text, badge)
            tile.clicked.connect(
                lambda _checked=False, value=loader: self._on_core_clicked(value)
            )
            self._core_group.addButton(tile)
            self._core_tiles[loader] = tile
            grid.addWidget(tile, index // 3, index % 3)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        self.card_layout.addLayout(grid)
        self.card_layout.addSpacing(8)

        optimize_row = QHBoxLayout()
        optimize_row.setContentsMargins(0, 0, 0, 0)
        optimize_row.setSpacing(8)
        self.optimize_checkbox = QCheckBox("Установить моды для оптимизации?")
        self.optimize_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.optimize_checkbox.setToolTip(
            "Fabric: Sodium + Lithium + FerriteCore\nForge: Embeddium + Oculus"
        )
        optimize_row.addWidget(self.optimize_checkbox)
        self.optimize_hint = QLabel("")
        self.optimize_hint.setObjectName("Caption")
        optimize_row.addWidget(self.optimize_hint, 1)
        self.card_layout.addLayout(optimize_row)
        self.card_layout.addSpacing(8)

        info = QFrame()
        info.setObjectName("InstallInfo")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(14, 9, 14, 9)
        info_layout.setSpacing(3)
        self.info_title = QLabel("Vanilla")
        self.info_title.setObjectName("FieldLabel")
        self.info_detail = QLabel("")
        self.info_detail.setObjectName("FieldHint")
        self.info_detail.setWordWrap(True)
        self.info_state = QLabel("")
        self.info_state.setObjectName("Caption")
        self.info_state.setWordWrap(True)
        info_layout.addWidget(self.info_title)
        info_layout.addWidget(self.info_detail)
        info_layout.addWidget(self.info_state)
        self.card_layout.addWidget(info)
        self.card_layout.addSpacing(9)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)
        self.fetch_status = QLabel("Загружаем список версий…")
        self.fetch_status.setObjectName("Caption")
        self.fetch_status.setWordWrap(True)
        footer.addWidget(self.fetch_status, 1)
        cancel = QPushButton("Отмена")
        cancel.setObjectName("GhostButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setFixedHeight(40)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.create_button = QPushButton("Создать экземпляр")
        self.create_button.setObjectName("SoftButton")
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.setFixedHeight(40)
        self.create_button.setMinimumWidth(154)
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self._accept)
        footer.addWidget(self.create_button)
        self.card_layout.addLayout(footer)

    # -------------------------------------------------------------- catalog
    def _set_catalog(self, entries: list[VersionEntry]) -> None:
        previous = self.versions_combo.currentData()
        self._entries = {entry.version: entry for entry in entries}
        self.versions_combo.blockSignals(True)
        self.versions_combo.clear()
        for entry in entries:
            date = entry.release_time.date().strftime("%d.%m.%Y") if entry.release_time else ""
            self.versions_combo.addItem(entry.version, entry.version)
            index = self.versions_combo.count() - 1
            if date:
                self.versions_combo.setItemData(index, f"Релиз {date}", Qt.ItemDataRole.ToolTipRole)
        if self._user_selected and previous in self._entries:
            target = previous
        else:
            target = next(iter(self._entries), None)
        if target is not None:
            index = self.versions_combo.findData(target)
            if index >= 0:
                self.versions_combo.setCurrentIndex(index)
        self.versions_combo.blockSignals(False)
        self._update_summary()

    def _mark_user_selection(self, _index: int) -> None:
        self._user_selected = True

    def _on_core_clicked(self, loader: str) -> None:
        self.selected_loader = loader
        self._update_summary()

    def _on_version_changed(self) -> None:
        self._update_summary()

    def _update_summary(self) -> None:
        version = self.versions_combo.currentData()
        if not isinstance(version, str):
            return
        loader = self.selected_loader
        label = loader_label(loader)
        existing = self._service.instance_for(version, loader)
        self.info_title.setText(f"{label} {version}")

        optimize_supported = loader in ("fabric", "forge")
        self.optimize_checkbox.setEnabled(optimize_supported and existing is None)
        if not optimize_supported:
            self.optimize_checkbox.setChecked(False)
        self.optimize_hint.setText(
            {
                "fabric": "Sodium + Lithium + FerriteCore",
                "forge": "Embeddium + Oculus",
            }.get(loader, "Только для Fabric и Forge")
        )

        if loader == "optifine":
            self.info_detail.setText(
                "OptiFine не поддерживает автоматическую установку: у него нет "
                "официального тихого установщика."
            )
            self.info_state.setText(
                "Выберите Vanilla, Fabric, Forge, NeoForge или Quilt."
            )
            self.create_button.setText("Недоступно")
            self.create_button.setEnabled(False)
            return

        descriptions = {
            "vanilla": "Minecraft Java Edition · чистая ванильная установка",
            "fabric": "Fabric Loader · лёгкие моды",
            "forge": "Forge · модпаки и Embeddium",
            "neoforge": "NeoForge · современная ветка Forge",
            "quilt": "Quilt Loader · совместимость с Fabric-модами",
        }
        if existing is not None:
            self.info_detail.setText(descriptions.get(loader, ""))
            self.info_state.setText(
                f"Экземпляр уже установлен · наиграно {format_playtime(existing.playtime_seconds)}"
            )
            self.create_button.setText("Открыть экземпляр")
        else:
            self.info_detail.setText(
                f"{descriptions.get(loader, '')} · Minecraft {version}"
            )
            self.info_state.setText(
                "Игра, ядро и Java будут скачаны в отдельную папку экземпляра."
            )
            self.create_button.setText("Создать экземпляр")
        self.create_button.setEnabled(True)

    def _accept(self) -> None:
        version = self.versions_combo.currentData()
        if not isinstance(version, str) or self.selected_loader == "optifine":
            return
        self.selected_version = version
        self.selected_optimize = self.optimize_checkbox.isChecked()
        self.accept()

    # ----------------------------------------------------------------- fetch
    def _fetch_versions(self) -> None:
        task = FetchVersionsTask(self._service)
        signals = task.signals
        signals.finished.connect(self._on_fetch_finished)
        signals.failed.connect(self._on_fetch_failed)
        self._fetch_task = task
        self._fetch_signals = signals
        QThreadPool.globalInstance().start(task)

    def _on_fetch_finished(self, fetched: object) -> None:
        if not isinstance(fetched, list):
            return
        entries = self._service.merge_catalog(
            entry for entry in fetched if isinstance(entry, VersionEntry)
        )
        self._set_catalog(entries)
        self.fetch_status.setText("Список версий обновлён")
        self._fetch_task = None
        self._fetch_signals = None

    def _on_fetch_failed(self, _message: str) -> None:
        self.fetch_status.setText("Нет связи с Mojang — доступны популярные версии")
        self._fetch_task = None
        self._fetch_signals = None


# Compatibility alias for older imports.
VersionSelectDialog = CreateInstanceDialog


class InstallProgressDialog(OverlayDialog):
    """Show download progress and keep the worker alive until it finishes."""

    def __init__(
        self,
        service: LauncherService,
        version: str,
        parent: QWidget,
        *,
        loader: str = "vanilla",
        optimize: bool = False,
        auto_start: bool = True,
    ) -> None:
        super().__init__(parent, card_width=492)
        self._service = service
        self._version = version
        self._loader = loader
        self._optimize = optimize
        self._auto_start = auto_start
        self._worker: InstallTask | None = None
        self._running = False
        self._started_once = False
        self._outcome = ""
        self._cancel_requested = False
        self.installed_instance: Instance | None = None
        self.error_message = ""

        self._build_ui()
        self.setWindowTitle(f"Установка {loader_label(loader)} {version}")

    def _build_ui(self) -> None:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(IconBadge("download", size=48, icon_size=22, radius=14))
        header.addStretch(1)
        self.close_button = IconButton(
            "close", size=(30, 30), icon_size=13, radius=9, tooltip="Отменить установку"
        )
        self.close_button.clicked.connect(self._request_cancel)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        self.card_layout.addLayout(header)
        self.card_layout.addSpacing(18)

        self.card_layout.addWidget(CapsLabel("УСТАНОВКА", size=9, spacing=2.0, accent=True))
        self.card_layout.addSpacing(6)
        self.title_label = QLabel(f"{loader_label(self._loader)} {self._version}")
        self.title_label.setObjectName("DialogTitle")
        self.card_layout.addWidget(self.title_label)
        self.card_layout.addSpacing(5)
        subtitle = QLabel(
            "Скачиваем Minecraft и ядро в отдельную папку экземпляра. "
            "Это может занять несколько минут."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        self.card_layout.addWidget(subtitle)
        self.card_layout.addSpacing(24)

        progress_header = QHBoxLayout()
        progress_header.setContentsMargins(0, 0, 0, 0)
        self.phase_label = QLabel("Подготовка установки")
        self.phase_label.setObjectName("ProgressPhase")
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("ValueLabel")
        progress_header.addWidget(self.phase_label, 1)
        progress_header.addWidget(self.percent_label, 0, Qt.AlignmentFlag.AlignRight)
        self.card_layout.addLayout(progress_header)
        self.card_layout.addSpacing(9)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Прогресс установки Minecraft")
        self.card_layout.addWidget(self.progress)
        self.card_layout.addSpacing(8)

        self.detail_label = QLabel("Получаем список файлов…")
        self.detail_label.setObjectName("ProgressDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setMinimumHeight(18)
        self.card_layout.addWidget(self.detail_label)
        self.card_layout.addSpacing(6)

        self.error_label = QLabel("")
        self.error_label.setObjectName("DialogError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.card_layout.addWidget(self.error_label)
        self.card_layout.addSpacing(14)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(
            CapsLabel("НЕ ЗАКРЫВАЙТЕ ЛАУНЧЕР", size=9, spacing=1.4, muted=True),
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        footer.addStretch(1)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setObjectName("GhostButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setFixedHeight(40)
        self.cancel_button.clicked.connect(self._handle_action)
        footer.addWidget(self.cancel_button)
        self.card_layout.addLayout(footer)

    # --------------------------------------------------------------- worker
    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self._auto_start and not self._started_once:
            self._started_once = True
            self._start_worker()

    def _start_worker(self) -> None:
        worker = InstallTask(
            self._service,
            self._version,
            self._loader,
            self,
            optimize=self._optimize,
        )
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_thread_finished)
        self._worker = worker
        self._running = True
        worker.start()

    def _on_progress(self, percent: int, title: str, detail: str) -> None:
        self.progress.setValue(max(0, min(100, int(percent))))
        self.percent_label.setText(f"{max(0, min(100, int(percent)))}%")
        self.phase_label.setText(title)
        if detail:
            self.detail_label.setText(detail)

    def _on_succeeded(self, instance: object) -> None:
        if isinstance(instance, Instance):
            self.installed_instance = instance
        self._outcome = "success"
        self.progress.setValue(100)
        self.percent_label.setText("100%")
        self.phase_label.setText("Готово")
        self.detail_label.setText("Экземпляр создан — открываем страницу игры.")
        self.error_label.hide()
        self.cancel_button.setEnabled(False)

    def _on_failed(self, message: str, cancelled: bool) -> None:
        self._outcome = "cancelled" if cancelled else "error"
        self.error_message = message
        self.phase_label.setText("Установка отменена" if cancelled else "Установка не завершена")
        self.detail_label.setText("")
        if cancelled:
            self.cancel_button.setEnabled(False)
        else:
            self.error_label.setText(message)
            self.error_label.show()
            self.progress.setValue(0)
            self.percent_label.setText("—")
            self.cancel_button.setText("Закрыть")
            self.cancel_button.setEnabled(True)

    def _on_thread_finished(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._outcome == "success":
            QTimer.singleShot(700, self.accept)
        elif self._outcome == "cancelled":
            self.reject()
        # Errors stay open so the user can read the message.

    def _request_cancel(self) -> None:
        if self._running and self._worker is not None:
            self._cancel_requested = True
            self.phase_label.setText("Отменяем установку…")
            self.percent_label.setText("—")
            self.cancel_button.setEnabled(False)
            self.close_button.setEnabled(False)
            self._worker.cancel()
        elif not self._running:
            self.reject()

    def _handle_action(self) -> None:
        if self._running:
            self._request_cancel()
        else:
            self.reject()

    def _on_escape(self) -> None:
        self._request_cancel()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._running:
            self._request_cancel()
            event.ignore()
            return
        super().closeEvent(event)

    def set_preview(self, percent: int, title: str, detail: str) -> None:
        """Used by documentation tooling to render a deterministic screenshot."""
        self._on_progress(percent, title, detail)


class LaunchLoadingDialog(OverlayDialog):
    """Small pre-launch screen with cancel support."""

    cancelled = Signal()

    def __init__(self, parent: QWidget, subtitle: str = "") -> None:
        super().__init__(parent, card_width=470)
        self._cancelled = False
        self.setWindowTitle("Запуск Minecraft")
        layout = self.card_layout
        layout.addWidget(IconBadge("play", size=48, icon_size=22, radius=14))
        layout.addSpacing(12)
        title = QLabel("Загрузка Minecraft…")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        hint = QLabel(subtitle or "Проверяем файлы и готовим запуск.")
        hint.setObjectName("PageSubtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(16)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        layout.addSpacing(14)
        cancel = QPushButton("Отменить")
        cancel.setObjectName("GhostButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self._cancel)
        layout.addWidget(cancel, 0, Qt.AlignmentFlag.AlignRight)

    @property
    def was_cancelled(self) -> bool:
        return self._cancelled

    def _cancel(self) -> None:
        self._cancelled = True
        self.cancelled.emit()
        self.reject()


class JavaProgressDialog(OverlayDialog):
    """Download a managed JRE before the first launch."""

    def __init__(
        self,
        service: LauncherService,
        major: int,
        parent: QWidget,
        *,
        auto_start: bool = True,
    ) -> None:
        super().__init__(parent, card_width=474)
        self._service = service
        self._major = major
        self._auto_start = auto_start
        self._worker: JavaTask | None = None
        self._running = False
        self._started_once = False
        self._outcome = ""
        self.java_runtime: JavaRuntime | None = None
        self.error_message = ""

        self._build_ui()
        self.setWindowTitle(f"Java {major}")

    def _build_ui(self) -> None:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(IconBadge("java", size=48, icon_size=22, radius=14))
        header.addStretch(1)
        self.close_button = IconButton(
            "close", size=(30, 30), icon_size=13, radius=9, tooltip="Отменить загрузку"
        )
        self.close_button.clicked.connect(self._request_cancel)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        self.card_layout.addLayout(header)
        self.card_layout.addSpacing(18)

        self.card_layout.addWidget(CapsLabel("ПОДГОТОВКА JAVA", size=9, spacing=2.0, accent=True))
        self.card_layout.addSpacing(6)
        title = QLabel(f"Java {self._major}")
        title.setObjectName("DialogTitle")
        self.card_layout.addWidget(title)
        self.card_layout.addSpacing(5)
        subtitle = QLabel(
            "Fionix скачает Eclipse Temurin JRE и будет использовать её при запуске."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        self.card_layout.addWidget(subtitle)
        self.card_layout.addSpacing(24)

        progress_header = QHBoxLayout()
        progress_header.setContentsMargins(0, 0, 0, 0)
        self.phase_label = QLabel("Проверка Java")
        self.phase_label.setObjectName("ProgressPhase")
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("ValueLabel")
        progress_header.addWidget(self.phase_label, 1)
        progress_header.addWidget(self.percent_label, 0, Qt.AlignmentFlag.AlignRight)
        self.card_layout.addLayout(progress_header)
        self.card_layout.addSpacing(9)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Прогресс загрузки Java")
        self.card_layout.addWidget(self.progress)
        self.card_layout.addSpacing(8)

        self.detail_label = QLabel("Ищем подходящую среду выполнения…")
        self.detail_label.setObjectName("ProgressDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setMinimumHeight(18)
        self.card_layout.addWidget(self.detail_label)
        self.card_layout.addSpacing(6)

        self.error_label = QLabel("")
        self.error_label.setObjectName("DialogError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.card_layout.addWidget(self.error_label)
        self.card_layout.addSpacing(14)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(
            CapsLabel("ТОЛЬКО ПРИ ПЕРВОМ ЗАПУСКЕ", size=9, spacing=1.4, muted=True)
        )
        footer.addStretch(1)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setObjectName("GhostButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setFixedHeight(40)
        self.cancel_button.clicked.connect(self._handle_action)
        footer.addWidget(self.cancel_button)
        self.card_layout.addLayout(footer)

    # --------------------------------------------------------------- worker
    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self._auto_start and not self._started_once:
            self._started_once = True
            self._start_worker()

    def _start_worker(self) -> None:
        worker = JavaTask(self._service, self._major, self)
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_thread_finished)
        self._worker = worker
        self._running = True
        worker.start()

    def _on_progress(self, percent: int, title: str, detail: str) -> None:
        percent = max(0, min(100, int(percent)))
        self.progress.setValue(percent)
        self.percent_label.setText(f"{percent}%")
        self.phase_label.setText(title)
        if detail:
            self.detail_label.setText(detail)

    def _on_succeeded(self, runtime: object) -> None:
        if isinstance(runtime, JavaRuntime):
            self.java_runtime = runtime
        self._outcome = "success"
        self.progress.setValue(100)
        self.percent_label.setText("100%")
        self.phase_label.setText("Java готова")
        self.detail_label.setText("Запускаем Minecraft…")
        self.error_label.hide()
        self.cancel_button.setEnabled(False)

    def _on_failed(self, message: str, cancelled: bool) -> None:
        self._outcome = "cancelled" if cancelled else "error"
        self.error_message = message
        self.phase_label.setText("Загрузка отменена" if cancelled else "Java не готова")
        self.detail_label.setText("")
        if cancelled:
            self.cancel_button.setEnabled(False)
        else:
            self.error_label.setText(message)
            self.error_label.show()
            self.progress.setValue(0)
            self.percent_label.setText("—")
            self.cancel_button.setText("Закрыть")
            self.cancel_button.setEnabled(True)

    def _on_thread_finished(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._outcome == "success":
            QTimer.singleShot(400, self.accept)
        elif self._outcome == "cancelled":
            self.reject()

    def _request_cancel(self) -> None:
        if self._running and self._worker is not None:
            self.phase_label.setText("Отменяем загрузку…")
            self.percent_label.setText("—")
            self.cancel_button.setEnabled(False)
            self.close_button.setEnabled(False)
            self._worker.cancel()
        elif not self._running:
            self.reject()

    def _handle_action(self) -> None:
        if self._running:
            self._request_cancel()
        else:
            self.reject()

    def _on_escape(self) -> None:
        self._request_cancel()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._running:
            self._request_cancel()
            event.ignore()
            return
        super().closeEvent(event)


class NoticeDialog(OverlayDialog):
    """Error / information dialog with the same glass visuals."""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        message: str,
        *,
        icon_name: str = "info",
        eyebrow: str = "FIONIX",
    ) -> None:
        super().__init__(parent, card_width=452)
        layout = self.card_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(IconBadge(icon_name, size=48, icon_size=22, radius=14))
        header.addStretch(1)
        close = IconButton("close", size=(30, 30), icon_size=13, radius=9, tooltip="Закрыть")
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(18)
        layout.addWidget(CapsLabel(eyebrow, size=9, spacing=2.0, accent=True))
        layout.addSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addSpacing(8)
        body = QLabel(message)
        body.setObjectName("PageSubtitle")
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addSpacing(22)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        close_button = QPushButton("Понятно")
        close_button.setObjectName("SoftButton")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setFixedHeight(40)
        close_button.setMinimumWidth(116)
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)
        self._default_button = close_button
        self.setWindowTitle(title)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._default_button.setFocus()
