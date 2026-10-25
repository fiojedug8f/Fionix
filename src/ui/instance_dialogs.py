"""Dialogs for content management, instance settings and maintenance tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.launcher import (
    ContentCategory,
    ContentFile,
    Instance,
    LauncherError,
    LauncherService,
)
from src.ui.launch_dialogs import OverlayDialog
from src.ui.widgets import (
    CapsLabel,
    GlassComboBox,
    IconBadge,
    IconButton,
    ToggleSwitch,
)


def format_size(size: int) -> str:
    if size <= 0:
        return "—"
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} КБ"
    return f"{size / 1024 / 1024:.1f} МБ"


def plural_files(count: int) -> str:
    count = abs(count)
    if count % 10 == 1 and count % 100 != 11:
        return "файл"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "файла"
    return "файлов"


class ContentFileRow(QFrame):
    """One installed content entry with an enable/disable switch."""

    def __init__(
        self,
        service: LauncherService,
        instance: Instance,
        category: ContentCategory,
        content: ContentFile,
        on_changed: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ContentRow")
        self._service = service
        self._instance = instance
        self._category = category
        self._content = content
        self._on_changed = on_changed
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(11)
        layout.addWidget(IconBadge(category.icon, size=32, icon_size=16, radius=9))

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        self.name_label = QLabel()
        self.name_label.setObjectName("ContentFileName")
        self.name_label.setToolTip(str(content.path))
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.meta_label = QLabel()
        self.meta_label.setObjectName("ContentFileMeta")
        self.status_label = QLabel()
        self.status_label.setObjectName("ContentFileStatus")
        text_column.addWidget(self.name_label)
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)
        meta_row.addWidget(self.meta_label)
        meta_row.addWidget(self.status_label)
        meta_row.addStretch(1)
        text_column.addLayout(meta_row)
        layout.addLayout(text_column, 1)

        self.toggle = ToggleSwitch()
        self.toggle.setAccessibleName(f"Включить {content.display_name}")
        self.toggle.setChecked(content.enabled)
        self.toggle.toggled.connect(self._toggle)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)

        self._refresh_labels()

    def _refresh_labels(self) -> None:
        self.name_label.setText(self._content.display_name)
        details = "Папка" if self._content.is_dir else format_size(self._content.size)
        self.meta_label.setText(details)
        self.status_label.setText("Включён" if self._content.enabled else "Отключён")
        self.status_label.setProperty("state", "on" if self._content.enabled else "off")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.update()
        self.setProperty("disabled", "false" if self._content.enabled else "true")
        self.style().unpolish(self)
        self.style().polish(self)

    def _toggle(self, enabled: bool) -> None:
        self.toggle.setEnabled(False)
        try:
            new_path = self._service.toggle_content(
                self._instance, self._category.key, self._content.path, enabled
            )
        except LauncherError as exc:
            self.status_label.setText("Ошибка")
            self.status_label.setProperty("state", "error")
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            self.status_label.setToolTip(str(exc))
            blocked = self.toggle.blockSignals(True)
            try:
                self.toggle.setChecked(self._content.enabled)
            finally:
                self.toggle.blockSignals(blocked)
        else:
            new_name = new_path.name
            is_dir = self._content.is_dir
            self._content = ContentFile(
                path=new_path,
                name=new_name,
                enabled=enabled,
                size=self._content.size,
                is_dir=is_dir,
            )
            self._refresh_labels()
            self._on_changed()
        finally:
            self.toggle.setEnabled(True)


class ContentManagerDialog(OverlayDialog):
    """Installed content browser with a tab bar and per-file toggles."""

    content_changed = Signal()

    def __init__(
        self,
        service: LauncherService,
        instance: Instance,
        category_key: str,
        parent: QWidget,
    ) -> None:
        super().__init__(parent, card_width=716)
        self._service = service
        self._instance = instance
        self._category = service.content_category(category_key)
        self._rows: list[ContentFileRow] = []
        self.setWindowTitle(f"{self._category.title} · {instance.name}")

        layout = self.card_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(IconBadge(self._category.icon, size=48, icon_size=22, radius=14))
        header.addStretch(1)
        close = IconButton("close", size=(30, 30), icon_size=13, radius=9, tooltip="Закрыть")
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(16)

        layout.addWidget(CapsLabel(f"СОДЕРЖИМОЕ · {self._category.title.upper()}", size=9, spacing=1.7, accent=True))
        layout.addSpacing(5)
        title = QLabel(self._category.title)
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        layout.addSpacing(4)
        subtitle = QLabel(self._category.description)
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)
        layout.addSpacing(14)

        tab_bar = QHBoxLayout()
        tab_bar.setContentsMargins(0, 0, 0, 0)
        tab_bar.setSpacing(4)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self.installed_tab = QPushButton("Установленные")
        self.installed_tab.setObjectName("TabButton")
        self.installed_tab.setCheckable(True)
        self.installed_tab.setChecked(True)
        self.find_tab = QPushButton("Найти")
        self.find_tab.setObjectName("TabButton")
        self.find_tab.setCheckable(True)
        for tab in (self.installed_tab, self.find_tab):
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            self._tab_group.addButton(tab)
            tab_bar.addWidget(tab)
        tab_bar.addStretch(1)
        layout.addLayout(tab_bar)
        divider = QFrame()
        divider.setObjectName("DialogDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        self._build_installed_page()
        self._build_find_page()
        self.installed_tab.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        self.find_tab.clicked.connect(lambda: self.pages.setCurrentIndex(1))

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 10, 0, 0)
        self.footer_count = QLabel("")
        self.footer_count.setObjectName("Muted")
        footer.addWidget(self.footer_count, 1)
        close_button = QPushButton("Готово")
        close_button.setObjectName("SoftButton")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setFixedHeight(40)
        close_button.setMinimumWidth(110)
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.reload()

    def _build_installed_page(self) -> None:
        page = QWidget()
        page.setObjectName("Page")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 12, 0, 0)
        page_layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        toolbar.addWidget(self.count_label, 1)
        refresh = QPushButton("Обновить")
        refresh.setObjectName("LinkButton")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self.reload)
        toolbar.addWidget(refresh)
        open_folder = QPushButton("Открыть папку")
        open_folder.setObjectName("GhostButton")
        open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder.setFixedHeight(34)
        open_folder.clicked.connect(self._open_folder)
        toolbar.addWidget(open_folder)
        page_layout.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(210)
        self.scroll.setMaximumHeight(340)
        self.scroll.viewport().setAutoFillBackground(False)
        self.list_widget = QWidget()
        self.list_widget.setObjectName("ContentList")
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_widget)
        page_layout.addWidget(self.scroll)
        self.pages.addWidget(page)

    def _build_find_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 20, 0, 20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop)
        empty = QFrame()
        empty.setObjectName("ContentEmpty")
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(24, 28, 24, 28)
        empty_layout.setSpacing(7)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(IconBadge("search", size=48, icon_size=22), 0, Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Поиск контента — в следующем этапе")
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel(
            "Сейчас здесь можно включать и отключать уже установленные файлы. "
            "Скачивание модов, карт и шейдеров появится позже."
        )
        sub.setObjectName("EmptyText")
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setMaximumWidth(480)
        empty_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(sub, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(empty, 0, Qt.AlignmentFlag.AlignCenter)
        self.pages.addWidget(page)

    # ------------------------------------------------------------- content
    def reload(self) -> None:
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()
        files = self._service.list_content(self._instance, self._category.key)
        if not files:
            empty = QFrame()
            empty.setObjectName("ContentEmpty")
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(16, 28, 16, 28)
            empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon = IconBadge(self._category.icon, size=42, icon_size=20)
            empty_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)
            label = QLabel(f"В разделе «{self._category.title}» пока пусто")
            label.setObjectName("EmptyTitle")
            empty_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignCenter)
            hint = QLabel("Добавьте файлы в папку экземпляра — они появятся здесь.")
            hint.setObjectName("EmptyText")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(hint, 0, Qt.AlignmentFlag.AlignCenter)
            self.list_layout.insertWidget(0, empty)
        else:
            for content in files:
                row = ContentFileRow(
                    self._service,
                    self._instance,
                    self._category,
                    content,
                    self._after_toggle,
                )
                self._rows.append(row)
                self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self._update_counts()

    def _after_toggle(self) -> None:
        self._update_counts()
        self.content_changed.emit()

    def _update_counts(self) -> None:
        files = self._service.list_content(self._instance, self._category.key)
        total = len(files)
        disabled = sum(1 for item in files if not item.enabled)
        self.count_label.setText(f"{total} {plural_files(total)}")
        self.footer_count.setText(
            f"Установлено: {total} · отключено: {disabled}"
            if total
            else "Папка пока пуста"
        )

    def _open_folder(self) -> None:
        folder = self._service.content_dir(self._instance, self._category.key)
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


class InstanceSettingsDialog(OverlayDialog):
    """Per-instance RAM, Java and folder settings."""

    def __init__(
        self,
        service: LauncherService,
        instance: Instance,
        default_memory_mb: int,
        parent: QWidget,
    ) -> None:
        super().__init__(parent, card_width=536)
        self._service = service
        self._instance = instance
        self._default_memory = max(1024, min(16384, int(default_memory_mb)))
        self._custom_java_path = ""
        self._managed_paths = set()

        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = self.card_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(IconBadge("settings", size=48, icon_size=22, radius=14))
        header.addStretch(1)
        close = IconButton("close", size=(30, 30), icon_size=13, radius=9, tooltip="Закрыть")
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(16)

        layout.addWidget(CapsLabel("НАСТРОЙКИ ЭКЗЕМПЛЯРА", size=9, spacing=1.8, accent=True))
        layout.addSpacing(5)
        self.title_label = QLabel(self._instance.name)
        self.title_label.setObjectName("DialogTitle")
        layout.addWidget(self.title_label)
        layout.addSpacing(4)
        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("PageSubtitle")
        layout.addWidget(self.subtitle_label)
        layout.addSpacing(14)

        name_label = QLabel("Название экземпляра")
        name_label.setObjectName("FieldLabel")
        layout.addWidget(name_label)
        self.name_edit = QLineEdit(self._instance.name)
        self.name_edit.setMaxLength(80)
        self.name_edit.setPlaceholderText("Например, Моя сборка")
        layout.addWidget(self.name_edit)
        icon_row = QHBoxLayout()
        icon_row.setSpacing(8)
        self.icon_button = QPushButton("Сменить иконку")
        self.icon_button.setObjectName("GhostButton")
        self.icon_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon_button.clicked.connect(self._choose_icon)
        icon_row.addWidget(self.icon_button)
        self.icon_hint = QLabel("PNG/JPG, будет обрезана до квадрата")
        self.icon_hint.setObjectName("Caption")
        icon_row.addWidget(self.icon_hint, 1)
        layout.addLayout(icon_row)
        layout.addSpacing(14)

        memory_header = QHBoxLayout()
        memory_header.setContentsMargins(0, 0, 0, 0)
        memory_label = QLabel("Оперативная память")
        memory_label.setObjectName("FieldLabel")
        self.memory_value = QLabel("")
        self.memory_value.setObjectName("ValueLabel")
        memory_header.addWidget(memory_label, 1)
        memory_header.addWidget(self.memory_value)
        layout.addLayout(memory_header)
        layout.addSpacing(4)
        hint = QLabel("Выделяется для Java-процесса именно этого экземпляра.")
        hint.setObjectName("FieldHint")
        layout.addWidget(hint)
        layout.addSpacing(10)
        self.memory_slider = QSlider(Qt.Orientation.Horizontal)
        self.memory_slider.setRange(1024, 16384)
        self.memory_slider.setSingleStep(512)
        self.memory_slider.setPageStep(1024)
        self.memory_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.memory_slider.valueChanged.connect(self._update_memory_label)
        self.memory_slider.setAccessibleName("Оперативная память экземпляра")
        layout.addWidget(self.memory_slider)
        scale = QHBoxLayout()
        scale.setContentsMargins(0, 2, 0, 0)
        for text in ("1 ГБ", "16 ГБ"):
            label = QLabel(text)
            label.setObjectName("Caption")
            scale.addWidget(label)
            if text == "1 ГБ":
                scale.addStretch(1)
        layout.addLayout(scale)
        layout.addSpacing(18)

        divider = QFrame()
        divider.setObjectName("DialogDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(16)

        java_label = QLabel("Java")
        java_label.setObjectName("FieldLabel")
        layout.addWidget(java_label)
        layout.addSpacing(3)
        java_hint = QLabel(
            f"Для этой сборки рекомендуется Java {self._instance.java_major} или новее."
        )
        java_hint.setObjectName("FieldHint")
        layout.addWidget(java_hint)
        layout.addSpacing(8)

        java_row = QHBoxLayout()
        java_row.setContentsMargins(0, 0, 0, 0)
        java_row.setSpacing(8)
        self.java_combo = GlassComboBox()
        self.java_combo.setAccessibleName("Java для экземпляра")
        java_row.addWidget(self.java_combo, 1)
        browse = QPushButton("Выбрать файл…")
        browse.setObjectName("GhostButton")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.setFixedHeight(40)
        browse.clicked.connect(self._browse_java)
        java_row.addWidget(browse, 0)
        layout.addLayout(java_row)

        self.java_error = QLabel("")
        self.java_error.setObjectName("DialogError")
        self.java_error.setWordWrap(True)
        self.java_error.hide()
        layout.addSpacing(5)
        layout.addWidget(self.java_error)
        layout.addSpacing(18)

        divider2 = QFrame()
        divider2.setObjectName("DialogDivider")
        divider2.setFixedHeight(1)
        layout.addWidget(divider2)
        layout.addSpacing(14)

        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_text = QVBoxLayout()
        folder_text.setContentsMargins(0, 0, 0, 0)
        folder_title = QLabel("Папка экземпляра")
        folder_title.setObjectName("FieldLabel")
        self.folder_path = QLabel("")
        self.folder_path.setObjectName("FieldHint")
        self.folder_path.setWordWrap(True)
        folder_text.addWidget(folder_title)
        folder_text.addWidget(self.folder_path)
        folder_row.addLayout(folder_text, 1)
        open_button = QPushButton("Открыть папку")
        open_button.setObjectName("GhostButton")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.setFixedHeight(38)
        open_button.clicked.connect(self._open_folder)
        folder_row.addWidget(open_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(folder_row)
        layout.addSpacing(20)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        note = QLabel("Изменения применятся при следующем запуске.")
        note.setObjectName("Caption")
        footer.addWidget(note, 1)
        cancel = QPushButton("Отмена")
        cancel.setObjectName("GhostButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setFixedHeight(40)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton("Сохранить")
        save.setObjectName("SoftButton")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setFixedHeight(40)
        save.setMinimumWidth(120)
        save.setDefault(True)
        save.clicked.connect(self._save)
        footer.addWidget(save)
        layout.addLayout(footer)

    def _load_values(self) -> None:
        self.title_label.setText(self._instance.name)
        self.name_edit.setText(self._instance.name)
        self.icon_button.setText(
            "Иконка выбрана" if self._instance.icon_path else "Сменить иконку"
        )
        self.subtitle_label.setText(
            f"{self._instance.loader_name} · Minecraft {self._instance.version}"
        )
        memory = self._instance.memory_mb or self._default_memory
        self.memory_slider.setValue(memory)
        self._update_memory_label(memory)
        parts = self._instance.path.parts
        short = (
            f"…{Path(*parts[-2:])}"
            if len(parts) >= 2
            else str(self._instance.path)
        )
        self.folder_path.setText(short)
        self.folder_path.setToolTip(str(self._instance.path))

        self.java_combo.addItem("Автоматически (Temurin)", "")
        managed = self._service.available_java_runtimes()
        for runtime in managed:
            data = str(runtime.path)
            self._managed_paths.add(data)
            label = f"Temurin Java {runtime.major}"
            if runtime.version:
                label += f" · {runtime.version}"
            self.java_combo.addItem(label, data)
        if self._instance.java_path:
            self._custom_java_path = self._instance.java_path
            index = self.java_combo.findData(self._instance.java_path)
            if index < 0:
                self.java_combo.addItem(
                    f"Своя Java · {Path(self._instance.java_path).name}",
                    self._instance.java_path,
                )
                index = self.java_combo.findData(self._instance.java_path)
            if index >= 0:
                self.java_combo.setCurrentIndex(index)

    def _update_memory_label(self, value: int) -> None:
        spacing = f"{value:,}".replace(",", " ")
        self.memory_value.setText(f"{spacing} МБ · {value // 1024} ГБ")

    def _browse_java(self) -> None:
        start_dir = (
            str(Path(self._instance.java_path).parent)
            if self._instance.java_path
            else str(self._service.runtime_dir)
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите исполняемый файл Java",
            start_dir,
            "Java executable (java.exe javaw.exe);;Все файлы (*)",
        )
        if not filename:
            return
        try:
            runtime = self._service.java_runtime_from_path(
                filename, self._instance.java_major
            )
        except LauncherError as exc:
            self.java_error.setText(str(exc))
            self.java_error.show()
            return
        self.java_error.hide()
        self._custom_java_path = str(runtime.path)
        if self.java_combo.findData(self._custom_java_path) < 0:
            self.java_combo.addItem(
                f"Своя Java · {Path(self._custom_java_path).name}",
                self._custom_java_path,
            )
        index = self.java_combo.findData(self._custom_java_path)
        if index >= 0:
            self.java_combo.setCurrentIndex(index)

    def _choose_icon(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Иконка экземпляра",
            str(Path.home()),
            "Изображения (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not filename:
            return
        source = Path(filename)
        target = self._instance.path / "icon.png"
        try:
            data = source.read_bytes()
            if len(data) > 5 * 1024 * 1024:
                raise LauncherError("Иконка больше 5 МБ.")
            target.write_bytes(data)
        except (OSError, LauncherError) as exc:
            QMessageBox.warning(self, "Иконка", str(exc))
            return
        self._instance.icon_path = str(target)
        self._instance.save()
        self.icon_button.setText("Иконка выбрана")

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Название", "Название не может быть пустым.")
            return
        self._instance.name = name[:80]
        memory_mb = int(self.memory_slider.value())
        if memory_mb < 2048:
            answer = QMessageBox.warning(
                self,
                "Мало оперативной памяти",
                "Выделено слишком мало памяти. Игра может вылететь или не запуститься.\n\n"
                "Всё равно сохранить настройки?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        selected = self.java_combo.currentData()
        java_path = str(selected) if selected else ""
        if java_path and java_path not in self._managed_paths:
            try:
                self._service.java_runtime_from_path(
                    java_path, self._instance.java_major
                )
            except LauncherError as exc:
                self.java_error.setText(str(exc))
                self.java_error.show()
                return
        self._instance.memory_mb = memory_mb
        self._instance.java_path = java_path
        try:
            self._instance.save()
        except OSError as exc:
            self.java_error.setText(f"Не удалось сохранить настройки: {exc}")
            self.java_error.show()
            return
        self.accept()

    def _open_folder(self) -> None:
        try:
            self._service.open_instance_folder(self._instance)
        except LauncherError as exc:
            self.java_error.setText(str(exc))
            self.java_error.show()


class OperationProgressDialog(OverlayDialog):
    """Generic cancellable progress dialog for optimize/backup workers."""

    def __init__(
        self,
        parent: QWidget,
        *,
        title: str,
        subtitle: str,
        icon_name: str,
        eyebrow: str,
        worker_factory: Callable[[QWidget], QThread],
    ) -> None:
        super().__init__(parent, card_width=486)
        self._worker_factory = worker_factory
        self._worker = None
        self._running = False
        self._started = False
        self._outcome = ""
        self.result: object | None = None
        self.error_message = ""
        self.setWindowTitle(title)

        layout = self.card_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(IconBadge(icon_name, size=48, icon_size=22, radius=14))
        header.addStretch(1)
        self.close_button = IconButton(
            "close", size=(30, 30), icon_size=13, radius=9, tooltip="Отменить"
        )
        self.close_button.clicked.connect(self._request_cancel)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(16)
        layout.addWidget(CapsLabel(eyebrow, size=9, spacing=1.9, accent=True))
        layout.addSpacing(5)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("DialogTitle")
        layout.addWidget(self.title_label)
        layout.addSpacing(4)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
        layout.addSpacing(22)

        progress_header = QHBoxLayout()
        progress_header.setContentsMargins(0, 0, 0, 0)
        self.phase_label = QLabel("Подготовка…")
        self.phase_label.setObjectName("ProgressPhase")
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("ValueLabel")
        progress_header.addWidget(self.phase_label, 1)
        progress_header.addWidget(self.percent_label)
        layout.addLayout(progress_header)
        layout.addSpacing(8)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        layout.addSpacing(8)
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("ProgressDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setMinimumHeight(18)
        layout.addWidget(self.detail_label)
        layout.addSpacing(5)
        self.error_label = QLabel("")
        self.error_label.setObjectName("DialogError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        layout.addSpacing(14)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        self.action_button = QPushButton("Отмена")
        self.action_button.setObjectName("GhostButton")
        self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_button.setFixedHeight(40)
        self.action_button.clicked.connect(self._handle_action)
        footer.addWidget(self.action_button)
        layout.addLayout(footer)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._start_worker()

    def _start_worker(self) -> None:
        worker = self._worker_factory(self)
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

    def _on_succeeded(self, result: object) -> None:
        self._outcome = "success"
        self.result = result
        self.progress.setValue(100)
        self.percent_label.setText("100%")
        self.phase_label.setText("Готово")
        self.detail_label.setText("Операция завершена.")
        self.error_label.hide()
        self.action_button.setEnabled(False)

    def _on_failed(self, message: str, cancelled: bool) -> None:
        self._outcome = "cancelled" if cancelled else "error"
        self.error_message = message
        self.phase_label.setText("Отменено" if cancelled else "Не удалось выполнить")
        self.detail_label.setText("")
        if cancelled:
            self.action_button.setEnabled(False)
        else:
            self.error_label.setText(message)
            self.error_label.show()
            self.progress.setValue(0)
            self.percent_label.setText("—")
            self.action_button.setText("Закрыть")
            self.action_button.setEnabled(True)

    def _on_thread_finished(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._outcome == "success":
            QTimer.singleShot(600, self.accept)
        elif self._outcome == "cancelled":
            self.reject()

    def _request_cancel(self) -> None:
        if self._running and self._worker is not None:
            self.phase_label.setText("Отмена…")
            self.percent_label.setText("—")
            self.action_button.setEnabled(False)
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
