"""Crash report dialog with a red surface, log and an AI helper."""

from __future__ import annotations

import webbrowser
from pathlib import Path

from config import CHATGPT_URL
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class CrashDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        title: str,
        log_path: Path,
        exit_code: int,
    ) -> None:
        super().__init__(parent)
        self._log_path = Path(log_path)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(720, 520)
        self.setStyleSheet(
            """
            QDialog { background-color: #2A0B12; }
            QLabel { color: #FFE4E9; background: transparent; }
            QLabel#CrashTitle { font-size: 22px; font-weight: 700; color: #FF8A9D; }
            QLabel#CrashSubtitle { font-size: 12px; color: #E8A9B4; }
            QTextEdit {
                background-color: #18060A;
                color: #FFE8EC;
                border: 1px solid #7A2534;
                border-radius: 10px;
                padding: 10px;
                font-family: "Consolas", "Cascadia Mono", monospace;
                font-size: 11px;
            }
            QPushButton {
                background-color: #4A1520;
                color: #FFE8EC;
                border: 1px solid #8E3042;
                border-radius: 9px;
                padding: 9px 16px;
            }
            QPushButton:hover { background-color: #67202E; }
            QPushButton#AiButton {
                background-color: #B91C3C;
                border-color: #FF8A9D;
                font-weight: 600;
            }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title_label = QLabel("Minecraft завершился с ошибкой")
        title_label.setObjectName("CrashTitle")
        header.addWidget(title_label, 1)
        code = QLabel(f"Код {exit_code}")
        code.setObjectName("CrashSubtitle")
        header.addWidget(code)
        layout.addLayout(header)
        subtitle = QLabel(
            "Ниже — последние строки лога. Скопируйте их в ИИ или приложите к "
            "сообщению об ошибке."
        )
        subtitle.setObjectName("CrashSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlainText(self._read_log())
        layout.addWidget(self.log, 1)
        footer = QHBoxLayout()
        folder = QPushButton("Открыть папку логов")
        folder.clicked.connect(self._open_folder)
        footer.addWidget(folder)
        footer.addStretch(1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        ask = QPushButton("Спросить у ИИ")
        ask.setObjectName("AiButton")
        ask.clicked.connect(self._ask_ai)
        footer.addWidget(ask)
        layout.addLayout(footer)

    def _read_log(self) -> str:
        try:
            text = self._log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Не удалось прочитать лог:\n{self._log_path}\n\n{exc}"
        if len(text) > 120_000:
            text = "…начало лога обрезано…\n" + text[-120_000:]
        return text or "Лог пуст."

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_path.parent)))

    def _ask_ai(self) -> None:
        prompt = (
            "Помоги разобраться, почему Minecraft завершился с ошибкой. "
            "Вот лог игры:\n\n" + self.log.toPlainText()
        )
        QApplication.clipboard().setText(prompt)
        webbrowser.open(CHATGPT_URL)
