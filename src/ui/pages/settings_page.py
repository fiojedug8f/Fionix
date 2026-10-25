"""Settings screen with the first persistent preferences."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage, QIntValidator
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src import __version__
from config import DONATE_URL
from src.ui.background_crop import BackgroundCropDialog
from src.core.accounts import Account
from src.core.config_manager import ConfigManager
from src.core.theme import current_theme, set_accent_color, theme_options
from src.ui.pages import Page, build_header
from src.ui.widgets import (
    GlassComboBox,
    IconBadge,
    ToggleSwitch,
)


class SettingsPage(Page):
    theme_changed = Signal(str)
    accent_changed = Signal(str)
    background_changed = Signal()
    video_volume_changed = Signal(int)
    language_changed = Signal(str)
    accounts_add_requested = Signal()
    account_switch_requested = Signal(str)
    account_logout_requested = Signal()
    instances_path_changed = Signal(str)
    update_check_requested = Signal()
    coming_soon_requested = Signal(str, str)

    def __init__(
        self,
        config: ConfigManager,
        accounts=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, margins=(30, 20, 30, 28), spacing=14)
        self._config = config
        self._accounts = accounts
        self._memory_dirty = False
        self._account_list: list[Account] = []

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self.flush)

        self.save_state = QLabel("●  Сохранено")
        self.save_state.setObjectName("SaveState")
        self.save_state.setProperty("state", "ok")
        self.save_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.body.addWidget(
            build_header(
                "Настройки",
                "Параметры лаунчера. Изменения применяются сразу.",
                self.save_state,
            )
        )
        self.body.addSpacing(2)

        self._build_appearance()
        self._build_accounts()
        self._build_performance()
        self._build_java()
        self._build_proxy()
        self._build_data_folder()
        self._build_about()

        self.body.addStretch(1)

        footer = QLabel(
            f"Fionix {__version__}  ·  настройки хранятся локально"
        )
        footer.setObjectName("Caption")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(footer)

    # --------------------------------------------------------------- cards
    def _make_card(
        self,
        icon_name: str,
        title: str,
        subtitle: str,
        badge_text: str | None = None,
        *,
        badge_widget: QWidget | None = None,
    ) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("SettingCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 19, 22, 21)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(13)
        header.addWidget(IconBadge(icon_name, size=38, icon_size=19, radius=11), 0, Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 1, 0, 0)
        text_column.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("FieldHint")
        subtitle_label.setWordWrap(True)
        text_column.addWidget(title_label)
        text_column.addWidget(subtitle_label)
        header.addLayout(text_column, 1)

        if badge_widget is not None:
            header.addWidget(badge_widget, 0, Qt.AlignmentFlag.AlignTop)
        elif badge_text:
            badge = QLabel(badge_text)
            badge.setObjectName("Tag")
            header.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        layout.addLayout(header)
        layout.addSpacing(15)
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(16)
        self.body.addWidget(card)
        return card, layout

    @staticmethod
    def _field_text(title: str, hint: str) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("FieldLabel")
        hint_label = QLabel(hint)
        hint_label.setObjectName("FieldHint")
        hint_label.setWordWrap(True)
        column.addWidget(title_label)
        column.addWidget(hint_label)
        return column

    # ------------------------------------------------------------ appearance
    def _build_appearance(self) -> None:
        _card, layout = self._make_card(
            "moon",
            "Внешний вид",
            "Оформление применяется сразу и запоминается между запусками.",
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(24)
        row.addLayout(
            self._field_text(
                "Тема оформления",
                "Подберите настроение стеклянных панелей и неоновых акцентов.",
            ),
            1,
        )

        self.theme_combo = GlassComboBox()
        self.theme_combo.setAccessibleName("Тема оформления")
        self.theme_combo.setFixedWidth(200)
        for key, display_name in theme_options():
            self.theme_combo.addItem(display_name, key)
        index = self.theme_combo.findData(self._config.theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        row.addWidget(self.theme_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)

        language_row = QHBoxLayout()
        language_row.setContentsMargins(0, 10, 0, 0)
        language_row.addLayout(
            self._field_text(
                "Язык интерфейса",
                "Русский или English. Применяется после перезапуска.",
            ),
            1,
        )
        self.language_combo = GlassComboBox()
        self.language_combo.addItem("Русский", "ru")
        self.language_combo.addItem("English", "en")
        lang_index = self.language_combo.findData(self._config.language)
        if lang_index >= 0:
            self.language_combo.setCurrentIndex(lang_index)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        language_row.addWidget(self.language_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(language_row)

        accent_row = QHBoxLayout()
        accent_row.setContentsMargins(0, 12, 0, 0)
        accent_row.setSpacing(12)
        accent_row.addLayout(
            self._field_text(
                "Акцентный цвет",
                "Меняет кнопки, подсветки и графику интерфейса.",
            ),
            1,
        )
        self.accent_button = QPushButton("Выбрать цвет")
        self.accent_button.setObjectName("GhostButton")
        self.accent_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.accent_button.clicked.connect(self._pick_accent)
        accent_row.addWidget(self.accent_button, 0, Qt.AlignmentFlag.AlignVCenter)
        reset_accent = QPushButton("Сбросить")
        reset_accent.setObjectName("LinkButton")
        reset_accent.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_accent.clicked.connect(self._reset_accent)
        accent_row.addWidget(reset_accent, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(accent_row)

        colors_row = QHBoxLayout()
        colors_row.setContentsMargins(0, 10, 0, 0)
        colors_row.setSpacing(10)
        colors_row.addLayout(
            self._field_text(
                "Цвета интерфейса",
                "Текст и панели можно подстроить под фон вручную.",
            ),
            1,
        )
        self.text_color_button = QPushButton("Цвет текста")
        self.text_color_button.setObjectName("GhostButton")
        self.text_color_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.text_color_button.clicked.connect(
            lambda: self._pick_ui_color("text_color", "Цвет текста")
        )
        colors_row.addWidget(self.text_color_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.panel_color_button = QPushButton("Цвет панелей")
        self.panel_color_button.setObjectName("GhostButton")
        self.panel_color_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.panel_color_button.clicked.connect(
            lambda: self._pick_ui_color("panel_color", "Цвет панелей")
        )
        colors_row.addWidget(self.panel_color_button, 0, Qt.AlignmentFlag.AlignVCenter)
        reset_colors = QPushButton("Сбросить")
        reset_colors.setObjectName("LinkButton")
        reset_colors.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_colors.clicked.connect(self._reset_ui_colors)
        colors_row.addWidget(reset_colors, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(colors_row)

        contrast_row = QHBoxLayout()
        contrast_row.setContentsMargins(0, 9, 0, 0)
        contrast_row.addLayout(
            self._field_text(
                "Авто-контраст",
                "Подбирает светлый или тёмный текст и панели под яркость фона.",
            ),
            1,
        )
        self.auto_contrast_toggle = ToggleSwitch()
        self.auto_contrast_toggle.setAccessibleName("Авто-контраст")
        self.auto_contrast_toggle.setChecked(self._config.auto_contrast)
        self.auto_contrast_toggle.toggled.connect(self._on_auto_contrast_toggled)
        contrast_row.addWidget(self.auto_contrast_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(contrast_row)

        snapshots_row = QHBoxLayout()
        snapshots_row.setContentsMargins(0, 9, 0, 0)
        snapshots_row.addLayout(
            self._field_text(
                "Показывать снапшоты и старые версии",
                "Release, Snapshot, Old Beta и Old Alpha из официального манифеста Mojang.",
            ),
            1,
        )
        self.snapshots_toggle = ToggleSwitch()
        self.snapshots_toggle.setAccessibleName("Показывать снапшоты и старые версии")
        self.snapshots_toggle.setChecked(self._config.show_snapshots)
        self.snapshots_toggle.toggled.connect(
            lambda enabled: self._config.update({"show_snapshots": bool(enabled)})
        )
        snapshots_row.addWidget(self.snapshots_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(snapshots_row)

        background_row = QHBoxLayout()
        background_row.setContentsMargins(0, 12, 0, 0)
        background_row.setSpacing(8)
        background_text = self._field_text(
            "Фон лаунчера",
            "Картинка или MP4 до 10 МБ.",
        )
        background_row.addLayout(background_text, 1)
        for label, mode in (("Картинка", "image"), ("Видео MP4", "video")):
            button = QPushButton(label)
            button.setObjectName("GhostButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=mode: self._choose_background(value))
            background_row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        reset_background = QPushButton("Сбросить")
        reset_background.setObjectName("LinkButton")
        reset_background.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_background.clicked.connect(self._reset_background)
        background_row.addWidget(reset_background, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(background_row)

        volume_row = QHBoxLayout()
        volume_row.setContentsMargins(0, 10, 0, 0)
        volume_row.setSpacing(10)
        volume_row.addLayout(
            self._field_text(
                "Громкость видео-фона",
                "Звук MP4-фона. 0 — без звука.",
            ),
            1,
        )
        self.video_volume = QSlider(Qt.Orientation.Horizontal)
        self.video_volume.setRange(0, 100)
        self.video_volume.setValue(self._config.video_volume)
        self.video_volume.setFixedWidth(180)
        self.video_volume.valueChanged.connect(self._on_video_volume_changed)
        volume_row.addWidget(self.video_volume, 0, Qt.AlignmentFlag.AlignVCenter)
        self.video_volume_label = QLabel(f"{self._config.video_volume}%")
        self.video_volume_label.setObjectName("Caption")
        self.video_volume_label.setFixedWidth(38)
        volume_row.addWidget(self.video_volume_label)
        layout.addLayout(volume_row)
        self.background_status = QLabel(self._background_label())
        self.background_status.setObjectName("Caption")
        layout.addSpacing(5)
        layout.addWidget(self.background_status)

        preview_note = QLabel(
            "Тёмная палитра · акцент применяется сразу"
        )
        preview_note.setObjectName("Caption")
        layout.addSpacing(10)
        layout.addWidget(preview_note)

    def _background_label(self) -> str:
        background = self._config.get("background", {})
        mode = str(background.get("mode", "asset"))
        path = str(background.get("path", ""))
        if mode == "asset" or not path:
            return "Сейчас используется стандартный фон Fionix."
        return f"Пользовательский {('видео' if mode == 'video' else 'изображение')}: {Path(path).name}"

    def _pick_accent(self) -> None:
        current = QColor(self._config.accent or current_theme().accent)
        color = QColorDialog.getColor(current, self, "Акцентный цвет Fionix")
        if not color.isValid():
            return
        value = color.name()
        self._config.update({"accent": value})
        set_accent_color(value)
        self._finish_save(True)
        self.accent_changed.emit(value)

    def _reset_accent(self) -> None:
        self._config.update({"accent": ""})
        set_accent_color("")
        self._finish_save(True)
        self.accent_changed.emit("")

    def _pick_ui_color(self, key: str, title: str) -> None:
        current = QColor(
            str(self._config.get(key, "") or current_theme().text)
        )
        color = QColorDialog.getColor(current, self, title)
        if not color.isValid():
            return
        self._config.update({key: color.name(), "auto_contrast": False})
        self.auto_contrast_toggle.blockSignals(True)
        self.auto_contrast_toggle.setChecked(False)
        self.auto_contrast_toggle.blockSignals(False)
        self._finish_save(True)
        self.accent_changed.emit(self._config.accent)

    def _reset_ui_colors(self) -> None:
        self._config.update({"text_color": "", "panel_color": ""})
        self._finish_save(True)
        self.accent_changed.emit(self._config.accent)

    def _on_auto_contrast_toggled(self, enabled: bool) -> None:
        self._config.update({"auto_contrast": enabled})
        if not enabled:
            return
        background = self._config.get("background", {})
        path = str(background.get("path", ""))
        if path and Path(path).is_file():
            image = QImage(path)
            if not image.isNull():
                self._apply_auto_contrast(image)
        else:
            self._config.update({"theme": "dark", "text_color": "", "panel_color": ""})
            self.accent_changed.emit(self._config.accent)

    def _apply_auto_contrast(self, image: QImage) -> None:
        if image.isNull():
            return
        sample = image.scaled(
            32, 32,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).convertToFormat(QImage.Format.Format_RGB32)
        total = 0.0
        count = 0
        for y in range(sample.height()):
            for x in range(sample.width()):
                color = QColor(sample.pixel(x, y))
                total += (
                    0.2126 * color.red()
                    + 0.7152 * color.green()
                    + 0.0722 * color.blue()
                )
                count += 1
        brightness = (total / max(1, count)) / 255
        # Bright backgrounds get the light palette with dark text/panels;
        # dark backgrounds keep the dark palette with light text.
        theme_key = "light" if brightness > 0.62 else "dark"
        self._config.update(
            {
                "theme": theme_key,
                "text_color": "",
                "panel_color": "",
                "auto_contrast": True,
            }
        )
        index = self.theme_combo.findData(theme_key)
        if index >= 0:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(index)
            self.theme_combo.blockSignals(False)
        self.accent_changed.emit(self._config.accent)

    def _choose_background(self, mode: str) -> None:
        if mode == "video":
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "Выберите видео-фон",
                str(Path.home()),
                "Видео (*.mp4 *.webm *.mov)",
            )
        else:
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "Выберите изображение-фон",
                str(Path.home()),
                "Изображения (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
        if not filename:
            return
        source = Path(filename)
        image_data: QImage | None = None
        if mode == "image":
            image_data = QImage(str(source))
            if image_data.isNull():
                QMessageBox.warning(self, "Не удалось открыть изображение", str(source))
                return
            crop = BackgroundCropDialog(
                self.window(), image_data, target_size=self.window().size()
            )
            if crop.exec() != QDialog.DialogCode.Accepted:
                crop.deleteLater()
                return
            image_data = crop.cropped_image()
            crop.deleteLater()
        try:
            size = source.stat().st_size
        except OSError:
            size = 0
        if mode == "video" and size > 10 * 1024 * 1024:
            QMessageBox.warning(
                self,
                "Фон слишком большой",
                "Размер фона ограничен 10 МБ.",
            )
            return
        backgrounds = self._config.data_dir / "backgrounds"
        backgrounds.mkdir(parents=True, exist_ok=True)
        target = backgrounds / f"{uuid.uuid4().hex}{'.png' if mode == 'image' else source.suffix.lower()}"
        try:
            if image_data is not None:
                if not image_data.save(str(target), "PNG"):
                    raise OSError("PNG не сохранён")
            else:
                shutil.copy2(source, target)
        except OSError as exc:
            QMessageBox.warning(self, "Не удалось скопировать фон", str(exc))
            return
        if target.stat().st_size > 10 * 1024 * 1024:
            target.unlink(missing_ok=True)
            QMessageBox.warning(
                self,
                "Фон слишком большой",
                "Итоговый файл больше 10 МБ.",
            )
            return
        self._config.update({"background": {"mode": mode, "path": str(target)}})
        if mode == "image" and image_data is not None and self._config.auto_contrast:
            self._apply_auto_contrast(image_data)
        self.background_status.setText(self._background_label())
        self._finish_save(True)
        self.background_changed.emit()

    def _reset_background(self) -> None:
        self._config.update({"background": {"mode": "asset", "path": ""}})
        self.background_status.setText(self._background_label())
        self._finish_save(True)
        self.background_changed.emit()

    # ------------------------------------------------------------- accounts
    def _build_accounts(self) -> None:
        _card, layout = self._make_card(
            "user",
            "Аккаунты",
            "Microsoft, LittleSkin, Ely.by или гость. Переключаться можно здесь и в сайдбаре.",
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.account_combo = GlassComboBox()
        self.account_combo.setMinimumWidth(240)
        self.account_combo.activated.connect(self._on_account_changed)
        row.addWidget(self.account_combo, 1)
        self.account_add_button = QPushButton("Добавить")
        self.account_add_button.setObjectName("SoftButton")
        self.account_add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.account_add_button.clicked.connect(self.accounts_add_requested.emit)
        row.addWidget(self.account_add_button, 0)
        self.account_logout_button = QPushButton("Выйти")
        self.account_logout_button.setObjectName("GhostButton")
        self.account_logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.account_logout_button.clicked.connect(self.account_logout_requested.emit)
        row.addWidget(self.account_logout_button, 0)
        layout.addLayout(row)
        self.account_hint = QLabel("Активных аккаунтов пока нет.")
        self.account_hint.setObjectName("Caption")
        layout.addSpacing(8)
        layout.addWidget(self.account_hint)
        self.refresh_accounts()

    def refresh_accounts(self) -> None:
        if not hasattr(self, "account_combo"):
            return
        if self._accounts is None:
            self._account_list = []
            active_id = ""
        else:
            self._account_list = list(self._accounts.accounts)
            active_id = self._accounts.active_id
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for account in self._account_list:
            self.account_combo.addItem(
                f"{account.username} · {account.provider_label}", account.id
            )
        self.account_combo.blockSignals(False)
        if self._account_list:
            index = self.account_combo.findData(active_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
            self.account_combo.setEnabled(True)
            self.account_hint.setText(
                "Пароли не сохраняются; хранится только токен и профиль."
            )
        else:
            self.account_combo.addItem("Нет аккаунта", "")
            self.account_combo.setEnabled(False)
            self.account_hint.setText("Добавьте аккаунт, чтобы использовать его при запуске.")

    def _on_account_changed(self, index: int) -> None:
        account_id = self.account_combo.itemData(index)
        if isinstance(account_id, str) and account_id:
            self.account_switch_requested.emit(account_id)

    # ---------------------------------------------------------- performance
    def _build_performance(self) -> None:
        _card, layout = self._make_card(
            "memory",
            "Производительность",
            "Память по умолчанию для новых экземпляров. "
            "Для каждой сборки её можно изменить отдельно.",
        )

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(20)
        top_row.addLayout(
            self._field_text(
                "Оперативная память",
                "4 ГБ — хорошая отправная точка; настройки сборки имеют приоритет.",
            ),
            1,
        )
        self.memory_value = QLabel("4 096 МБ")
        self.memory_value.setObjectName("ValueLabel")
        top_row.addWidget(self.memory_value, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(top_row)
        layout.addSpacing(16)

        self.memory_slider = QSlider(Qt.Orientation.Horizontal)
        self.memory_slider.setAccessibleName("Оперативная память, МБ")
        self.memory_slider.setRange(1024, 16384)
        self.memory_slider.setSingleStep(512)
        self.memory_slider.setPageStep(1024)
        self.memory_slider.setValue(self._config.memory_mb)
        self.memory_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.memory_slider.valueChanged.connect(self._on_memory_changed)
        layout.addWidget(self.memory_slider)
        self._update_memory_label(self.memory_slider.value())

        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 4, 0, 0)
        minimum = QLabel("1 ГБ")
        minimum.setObjectName("Caption")
        maximum = QLabel("16 ГБ")
        maximum.setObjectName("Caption")
        scale_row.addWidget(minimum)
        scale_row.addStretch(1)
        scale_row.addWidget(maximum)
        layout.addLayout(scale_row)

    def _update_memory_label(self, value: int) -> None:
        spacing = f"{value:,}".replace(",", " ")
        self.memory_value.setText(f"{spacing} МБ")

    def _on_memory_changed(self, value: int) -> None:
        self._update_memory_label(value)
        self._memory_dirty = True
        self._set_save_state("saving", "Сохранение…")
        self._save_timer.start()

    # ------------------------------------------------------------------ java
    def _build_java(self) -> None:
        _card, layout = self._make_card(
            "java",
            "Java",
            "Fionix сам скачивает Eclipse Temurin нужной версии и использует её для игры.",
            "АВТО",
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(20)
        row.addLayout(
            self._field_text(
                "Среда выполнения",
                "Версия Java определяется автоматически для каждой сборки.",
            ),
            1,
        )

        runtime_path = self._config.data_dir / "runtime"
        java = self._config.get("java", {})
        configured = str(java.get("path", ""))
        auto = bool(java.get("auto", True))
        self.java_path = QLineEdit(
            "Автоматически · runtime/" if auto or not configured else configured
        )
        self.java_path.setReadOnly(True)
        self.java_path.setToolTip(str(configured or runtime_path))
        self.java_path.setMinimumWidth(220)
        self.java_path.setMaximumWidth(360)
        self.java_path.setCursorPosition(0)
        row.addWidget(self.java_path, 1, Qt.AlignmentFlag.AlignVCenter)

        choose_java = QPushButton("Выбрать Java")
        choose_java.setObjectName("SoftButton")
        choose_java.setCursor(Qt.CursorShape.PointingHandCursor)
        choose_java.clicked.connect(self._choose_global_java)
        row.addWidget(choose_java, 0, Qt.AlignmentFlag.AlignVCenter)
        auto_java = QPushButton("Авто")
        auto_java.setObjectName("GhostButton")
        auto_java.setCursor(Qt.CursorShape.PointingHandCursor)
        auto_java.clicked.connect(self._set_java_auto)
        row.addWidget(auto_java, 0, Qt.AlignmentFlag.AlignVCenter)
        runtime_button = QPushButton("Открыть runtime")
        runtime_button.setObjectName("GhostButton")
        runtime_button.setCursor(Qt.CursorShape.PointingHandCursor)
        runtime_button.clicked.connect(self._open_runtime_folder)
        row.addWidget(runtime_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)

        hint = QLabel("Загрузка выполняется при первом запуске экземпляра.")
        hint.setObjectName("Caption")
        layout.addSpacing(9)
        layout.addWidget(hint)

    def _choose_global_java(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите Java для всех экземпляров",
            str(self._config.data_dir / "runtime"),
            "Java executable (java.exe javaw.exe);;Все файлы (*)",
        )
        if not filename:
            return
        ok = self._config.update({"java": {"path": filename, "auto": False}})
        if ok:
            self.java_path.setText(filename)
            self.java_path.setCursorPosition(0)
            self._finish_save(True)
        else:
            self._finish_save(False)

    def _set_java_auto(self) -> None:
        ok = self._config.update({"java": {"path": "", "auto": True}})
        if ok:
            self.java_path.setText("Автоматически · runtime/")
            self._finish_save(True)
        else:
            self._finish_save(False)

    def _open_runtime_folder(self) -> None:
        runtime = self._config.data_dir / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(runtime))):
            self._set_save_state("error", "Не удалось открыть runtime")

    # ----------------------------------------------------------------- proxy
    def _build_proxy(self) -> None:
        _card, layout = self._make_card(
            "globe",
            "Сеть и прокси",
            "Прокси применяется к загрузкам лаунчера и к JVM Minecraft.",
        )
        proxy = self._config.get("proxy", {})

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(18)
        toggle_row.addLayout(
            self._field_text(
                "Использовать прокси",
                "Укажите HTTP-прокси для Mojang, Modrinth и загрузок файлов.",
            ),
            1,
        )
        self.proxy_toggle = ToggleSwitch()
        self.proxy_toggle.setAccessibleName("Использовать прокси")
        self.proxy_toggle.setChecked(bool(proxy.get("enabled", False)))
        toggle_row.addWidget(self.proxy_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(toggle_row)
        layout.addSpacing(14)

        fields = QWidget()
        fields.setObjectName("ProxyFields")
        fields_layout = QHBoxLayout(fields)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(12)

        host_column = QVBoxLayout()
        host_column.setContentsMargins(0, 0, 0, 0)
        host_column.setSpacing(5)
        host_label = QLabel("Хост")
        host_label.setObjectName("Caption")
        self.proxy_host = QLineEdit(str(proxy.get("host", "")))
        self.proxy_host.setAccessibleName("Хост прокси")
        self.proxy_host.setPlaceholderText("127.0.0.1")
        host_column.addWidget(host_label)
        host_column.addWidget(self.proxy_host)
        fields_layout.addLayout(host_column, 1)

        port_column = QVBoxLayout()
        port_column.setContentsMargins(0, 0, 0, 0)
        port_column.setSpacing(5)
        port_label = QLabel("Порт")
        port_label.setObjectName("Caption")
        self.proxy_port = QLineEdit(str(proxy.get("port", 8080)))
        self.proxy_port.setAccessibleName("Порт прокси")
        self.proxy_port.setValidator(QIntValidator(1, 65535, self))
        self.proxy_port.setFixedWidth(110)
        port_column.addWidget(port_label)
        port_column.addWidget(self.proxy_port)
        fields_layout.addLayout(port_column, 0)
        layout.addWidget(fields)
        layout.addSpacing(10)

        credentials = QHBoxLayout()
        credentials.setContentsMargins(0, 0, 0, 0)
        credentials.setSpacing(10)
        self.proxy_username = QLineEdit(str(proxy.get("username", "")))
        self.proxy_username.setPlaceholderText("Логин прокси (если нужен)")
        credentials.addWidget(self.proxy_username, 1)
        self.proxy_password = QLineEdit(str(proxy.get("password", "")))
        self.proxy_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.proxy_password.setPlaceholderText("Пароль прокси")
        credentials.addWidget(self.proxy_password, 1)
        layout.addLayout(credentials)
        layout.addSpacing(12)

        enabled = bool(proxy.get("enabled", False))
        self.proxy_host.setEnabled(enabled)
        self.proxy_port.setEnabled(enabled)
        self.proxy_username.setEnabled(enabled)
        self.proxy_password.setEnabled(enabled)
        self._proxy_fields = (
            self.proxy_host,
            self.proxy_port,
            self.proxy_username,
            self.proxy_password,
        )

        self.proxy_toggle.toggled.connect(self._on_proxy_toggled)
        for field in (self.proxy_host, self.proxy_port, self.proxy_username, self.proxy_password):
            field.editingFinished.connect(self._save_proxy)

    def _on_proxy_toggled(self, enabled: bool) -> None:
        for field in self._proxy_fields:
            field.setEnabled(enabled)
        self._save_proxy()

    def _save_proxy(self) -> None:
        port = self.proxy_port.text().strip() or "8080"
        try:
            port_value = max(1, min(65535, int(port)))
        except ValueError:
            port_value = 8080
        self.proxy_port.setText(str(port_value))
        ok = self._config.set_proxy(
            enabled=self.proxy_toggle.isChecked(),
            host=self.proxy_host.text().strip(),
            port=port_value,
            username=self.proxy_username.text().strip(),
            password=self.proxy_password.text(),
        )
        self._finish_save(ok)

    def _save_network(self) -> None:
        self._save_proxy()
        self._finish_save(True)

    # ----------------------------------------------------------- data folder
    def _build_data_folder(self) -> None:
        _card, layout = self._make_card(
            "folder",
            "Данные лаунчера",
            "Программа и пользовательские данные хранятся отдельно.",
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        path = QLineEdit(str(self._config.data_dir))
        path.setReadOnly(True)
        path.setCursorPosition(0)
        path.setToolTip("Папка данных Fionix")
        row.addWidget(path, 1)

        open_button = QPushButton("Открыть папку")
        open_button.setObjectName("GhostButton")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(self._open_data_folder)
        row.addWidget(open_button, 0)
        layout.addLayout(row)
        layout.addSpacing(12)

        instances_row = QHBoxLayout()
        instances_row.setContentsMargins(0, 0, 0, 0)
        instances_row.setSpacing(10)
        instances_label = QLabel("Папка экземпляров")
        instances_label.setObjectName("FieldLabel")
        instances_row.addWidget(instances_label)
        current = str(
            self._config.get("instances_path")
            or (self._config.data_dir / "instances")
        )
        self.instances_path_edit = QLineEdit(current)
        self.instances_path_edit.setReadOnly(True)
        self.instances_path_edit.setCursorPosition(0)
        instances_row.addWidget(self.instances_path_edit, 1)
        browse = QPushButton("Выбрать")
        browse.setObjectName("GhostButton")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._choose_instances_folder)
        instances_row.addWidget(browse)
        layout.addLayout(instances_row)

        hint = QLabel(
            "instances/  ·  backgrounds/  ·  logs/"
        )
        hint.setObjectName("Caption")
        layout.addSpacing(9)
        layout.addWidget(hint)

    def _choose_instances_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Папка экземпляров", self.instances_path_edit.text()
        )
        if not selected:
            return
        ok = self._config.update({"instances_path": selected})
        if ok:
            self.instances_path_edit.setText(selected)
            self.instances_path_edit.setCursorPosition(0)
            self._finish_save(True)
            self.instances_path_changed.emit(selected)
        else:
            self._finish_save(False)

    def _open_data_folder(self) -> None:
        url = QUrl.fromLocalFile(str(self._config.data_dir))
        if not QDesktopServices.openUrl(url):
            self._set_save_state("error", "Не удалось открыть папку")

    # ---------------------------------------------------------------- about
    def _build_about(self) -> None:
        _card, layout = self._make_card(
            "info",
            "О программе",
            "Версия лаунчера и проверка обновлений на GitHub.",
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.version_label = QLabel(f"Fionix v{__version__}")
        self.version_label.setObjectName("FieldLabel")
        row.addWidget(self.version_label, 1)
        self.update_status = QLabel("Проверка обновлений не выполнялась.")
        self.update_status.setObjectName("Caption")
        row.addWidget(self.update_status, 2)
        check = QPushButton("Проверить обновления")
        check.setObjectName("GhostButton")
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        check.clicked.connect(self.update_check_requested.emit)
        row.addWidget(check)
        layout.addLayout(row)

    def set_update_status(self, text: str, *, error: bool = False) -> None:
        if not hasattr(self, "update_status"):
            return
        self.update_status.setText(text)
        self.update_status.setProperty("state", "error" if error else "ok")
        self.update_status.style().unpolish(self.update_status)
        self.update_status.style().polish(self.update_status)

    # ------------------------------------------------------------------ save
    def _on_language_changed(self) -> None:
        language = str(self.language_combo.currentData() or "ru")
        self._config.update({"language": language})
        self.language_changed.emit(language)

    def _on_video_volume_changed(self, value: int) -> None:
        self.video_volume_label.setText(f"{value}%")
        self._config.update({"video_volume": int(value)})
        self.video_volume_changed.emit(int(value))

    def _on_theme_changed(self) -> None:
        theme_key = self.theme_combo.currentData()
        if not isinstance(theme_key, str):
            return
        ok = self._config.update({"theme": theme_key})
        self._finish_save(ok)
        if ok:
            self.theme_changed.emit(theme_key)

    def _set_save_state(self, state: str, text: str) -> None:
        self.save_state.setText(f"●  {text}")
        self.save_state.setProperty("state", state)
        self.save_state.style().unpolish(self.save_state)
        self.save_state.style().polish(self.save_state)
        self.save_state.update()

    def _finish_save(self, ok: bool) -> None:
        if ok:
            self._set_save_state("ok", "Сохранено")
        else:
            self._set_save_state("error", "Ошибка сохранения")

    def flush(self) -> None:
        """Persist debounced values (also called when the window closes)."""
        if not self._memory_dirty:
            return
        self._save_timer.stop()
        self._memory_dirty = False
        ok = self._config.update({"memory_mb": self.memory_slider.value()})
        self._finish_save(ok)
