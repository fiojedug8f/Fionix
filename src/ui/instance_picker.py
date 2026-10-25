"""Small instance chooser used for global market installs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.core.launcher import Instance
from src.ui.launch_dialogs import OverlayDialog


class InstancePickerDialog(OverlayDialog):
    def __init__(self, parent: QWidget, instances: list[Instance], project_name: str) -> None:
        super().__init__(parent, card_width=470)
        self.instance: Instance | None = None
        self.setWindowTitle("Выберите экземпляр")
        layout = self.card_layout
        title = QLabel("Куда установить?")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        hint = QLabel(f"{project_name} будет добавлен в выбранный экземпляр.")
        hint.setObjectName("PageSubtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(12)
        for instance in instances:
            button = QPushButton(
                f"{instance.name}\n{instance.loader_name} · Minecraft {instance.version}"
            )
            button.setObjectName("SoftButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(52)
            button.clicked.connect(
                lambda _checked=False, item=instance: self._choose(item)
            )
            layout.addWidget(button)
        layout.addSpacing(10)
        cancel = QPushButton("Отмена")
        cancel.setObjectName("GhostButton")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel, 0, Qt.AlignmentFlag.AlignRight)

    def _choose(self, instance: Instance) -> None:
        self.instance = instance
        self.accept()
