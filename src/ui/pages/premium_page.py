"""User-facing Premium page with benefits and one-key activation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.config_manager import ConfigManager
from src.ui.pages import Page, build_header


class PremiumPage(Page):
    activated = Signal()

    BENEFITS = (
        ("4K-фоны", "Картинки и видео без ограничения 10 МБ."),
        ("Эксклюзивные темы", "Премиальные палитры и акценты Fionix."),
        ("Корона", "Значок Premium рядом с ником в сайдбаре."),
        ("Приоритет", "Ранний доступ к новым функциям лаунчера."),
    )

    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.body.addWidget(
            build_header(
                "Премиум",
                "Больше возможностей для вашего лаунчера.",
            )
        )
        for title, description in self.BENEFITS:
            card = QFrame()
            card.setObjectName("InstallInfo")
            layout = QHBoxLayout(card)
            layout.setContentsMargins(18, 13, 18, 13)
            column = QVBoxLayout()
            column.setSpacing(2)
            title_label = QLabel(title)
            title_label.setObjectName("FieldLabel")
            column.addWidget(title_label)
            hint = QLabel(description)
            hint.setObjectName("Caption")
            hint.setWordWrap(True)
            column.addWidget(hint)
            layout.addLayout(column, 1)
            layout.addWidget(QLabel("◆"), 0, Qt.AlignmentFlag.AlignVCenter)
            self.body.addWidget(card)

        activate_card = QFrame()
        activate_card.setObjectName("SettingsCard")
        activate_layout = QVBoxLayout(activate_card)
        activate_layout.setContentsMargins(18, 15, 18, 15)
        activate_layout.setSpacing(8)
        activate_layout.addWidget(QLabel("Активация ключом"))
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("Ключ Dodo Payments")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        activate_layout.addWidget(self.key_edit)
        self.status = QLabel()
        self.status.setObjectName("Caption")
        activate_layout.addWidget(self.status)
        button = QPushButton("Активировать")
        button.setObjectName("PrimaryButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(self._activate)
        activate_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(activate_card)
        self.body.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        if self.config.premium_active:
            self.status.setText("Премиум активен. Корона уже рядом с ником.")
        else:
            self.status.setText("Сейчас активен бесплатный режим.")

    def _activate(self) -> None:
        key = self.key_edit.text().strip()
        if len(key) < 8:
            QMessageBox.warning(self, "Ключ", "Введите ключ Dodo Payments.")
            return
        self.config.update({"premium": {"key": key, "active": True}})
        self.refresh()
        self.activated.emit()
