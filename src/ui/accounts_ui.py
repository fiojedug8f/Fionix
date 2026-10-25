"""Welcome/provider chooser and credential dialogs for Fionix accounts."""

from __future__ import annotations

import os
import webbrowser

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import ELYBY_REGISTER_URL, LITTLESKIN_REGISTER_URL, REDIRECT_URL
from src.core.accounts import Account, microsoft_login_url
from src.ui.launch_dialogs import OverlayDialog
from src.ui.tasks import AccountLoginTask, MicrosoftCodeTask, MicrosoftOAuthTask
from src.ui.widgets import CapsLabel, IconBadge, IconButton


class ProviderTile(QPushButton):
    def __init__(self, provider: str, title: str, subtitle: str, icon: str) -> None:
        super().__init__()
        self.provider = provider
        self.setObjectName("ProviderTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        layout.addWidget(IconBadge(icon, size=38, icon_size=19, radius=11))
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("ProviderTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("ProviderSubtitle")
        subtitle_label.setWordWrap(True)
        text.addStretch(1)
        text.addWidget(title_label)
        text.addWidget(subtitle_label)
        text.addStretch(1)
        layout.addLayout(text, 1)
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)


class AccountWelcomeDialog(OverlayDialog):
    """First-run/account-add chooser with the four required providers."""

    def __init__(self, parent: QWidget, *, first_run: bool = False) -> None:
        super().__init__(parent, card_width=590)
        self.provider = ""
        self.first_run = first_run
        layout = self.card_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(IconBadge("user", size=48, icon_size=22, radius=14))
        header.addStretch(1)
        close = IconButton("close", size=(30, 30), icon_size=13, radius=9, tooltip="Закрыть")
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(14)
        layout.addWidget(CapsLabel("FIONIX ACCOUNT", size=9, spacing=1.9, accent=True))
        layout.addSpacing(6)
        title = QLabel("Добро пожаловать в Fionix" if first_run else "Добавить аккаунт")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        layout.addSpacing(5)
        subtitle = QLabel(
            "Выберите, как войти. Аккаунт можно сменить в сайдбаре, "
            "а управлять ими — в настройках."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(18)

        grid = QHBoxLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(9)
        left = QVBoxLayout()
        left.setSpacing(9)
        right = QVBoxLayout()
        right.setSpacing(9)
        specs = (
            ("microsoft", "Microsoft", "Лицензионный аккаунт", "windows"),
            ("littleskin", "LittleSkin", "Скины и Yggdrasil-профиль", "user"),
            ("elyby", "Ely.by", "Скины и Yggdrasil-профиль", "globe"),
            ("guest", "Войти как гость", "Локальный офлайн-профиль", "user"),
        )
        for index, spec in enumerate(specs):
            tile = ProviderTile(*spec)
            tile.clicked.connect(
                lambda _checked=False, value=spec[0]: self._choose(value)
            )
            (left if index % 2 == 0 else right).addWidget(tile)
        grid.addLayout(left, 1)
        grid.addLayout(right, 1)
        layout.addLayout(grid)
        layout.addSpacing(14)

        hint = QLabel(
            "Пароли LittleSkin и Ely.by используются только для получения токена "
            "и не сохраняются на диск."
        )
        hint.setObjectName("Caption")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(14)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        later = QPushButton("Позже" if not first_run else "Продолжить как гость")
        later.setObjectName("GhostButton")
        later.setCursor(Qt.CursorShape.PointingHandCursor)
        later.setFixedHeight(38)
        later.clicked.connect(self._continue_later)
        footer.addWidget(later)
        footer.addStretch(1)
        layout.addLayout(footer)

    def _choose(self, provider: str) -> None:
        self.provider = provider
        self.accept()

    def _continue_later(self) -> None:
        if self.first_run:
            self.provider = "guest"
            self.accept()
        else:
            self.reject()


class CredentialsDialog(OverlayDialog):
    """Login form for LittleSkin/Ely.by backed by a worker thread."""

    def __init__(self, parent: QWidget, provider: str) -> None:
        super().__init__(parent, card_width=470)
        self.provider = provider
        self.account: Account | None = None
        self._worker: AccountLoginTask | None = None
        provider_title = "LittleSkin" if provider == "littleskin" else "Ely.by"
        layout = self.card_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(IconBadge("user" if provider == "littleskin" else "globe", size=48, icon_size=22, radius=14))
        header.addStretch(1)
        close = IconButton("close", size=(30, 30), icon_size=13, radius=9, tooltip="Закрыть")
        close.clicked.connect(self._close)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(15)
        layout.addWidget(CapsLabel(f"ВХОД · {provider_title.upper()}", size=9, spacing=1.8, accent=True))
        layout.addSpacing(6)
        title = QLabel(f"Аккаунт {provider_title}")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        layout.addSpacing(5)
        subtitle = QLabel("Введите логин и пароль от аккаунта. Пароль не сохраняется.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(18)

        layout.addWidget(self._label("Логин или e-mail"))
        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("Никнейм")
        self.login_edit.setMinimumHeight(42)
        self.login_edit.returnPressed.connect(self._submit)
        layout.addWidget(self.login_edit)
        layout.addSpacing(12)
        layout.addWidget(self._label("Пароль"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Пароль")
        self.password_edit.setMinimumHeight(42)
        self.password_edit.returnPressed.connect(self._submit)
        layout.addWidget(self.password_edit)
        layout.addSpacing(7)
        self.error_label = QLabel("")
        self.error_label.setObjectName("DialogError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        layout.addSpacing(16)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        register = QPushButton("Регистрация")
        register.setObjectName("LinkButton")
        register.setCursor(Qt.CursorShape.PointingHandCursor)
        register.clicked.connect(self._open_register)
        footer.addWidget(register)
        footer.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setObjectName("GhostButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setFixedHeight(40)
        cancel.clicked.connect(self._close)
        footer.addWidget(cancel)
        self.login_button = QPushButton("Войти")
        self.login_button.setObjectName("SoftButton")
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.setFixedHeight(40)
        self.login_button.setMinimumWidth(112)
        self.login_button.setDefault(True)
        self.login_button.clicked.connect(self._submit)
        footer.addWidget(self.login_button)
        layout.addLayout(footer)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _submit(self) -> None:
        if self._worker is not None:
            return
        username = self.login_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            self._show_error("Введите логин и пароль.")
            return
        self.error_label.hide()
        self.login_button.setEnabled(False)
        self.login_button.setText("Вход…")
        worker = AccountLoginTask(self.provider, username, password, self)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start()

    def _on_success(self, account: object) -> None:
        if isinstance(account, Account):
            self.account = account

    def _on_failed(self, message: str) -> None:
        self._show_error(message)

    def _on_finished(self) -> None:
        self.login_button.setEnabled(True)
        self.login_button.setText("Войти")
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self.account is not None:
            self.accept()

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _open_register(self) -> None:
        url = (
            LITTLESKIN_REGISTER_URL
            if self.provider == "littleskin"
            else ELYBY_REGISTER_URL
        )
        QDesktopServices.openUrl(QUrl(url))

    def _close(self) -> None:
        if self._worker is not None:
            return
        self.reject()

    def _on_escape(self) -> None:
        self._close()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._worker is not None:
            event.ignore()
            return
        super().closeEvent(event)


class MicrosoftLoginDialog(OverlayDialog):
    """Official Microsoft authorization-code flow with a manual fallback."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, card_width=500)
        self.account: Account | None = None
        self._worker = None
        self._started = False
        self._cancel_requested = False
        self._last_auth_url = ""
        self._code_exchange_started = False
        layout = self.card_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(IconBadge("windows", size=48, icon_size=22, radius=14))
        header.addStretch(1)
        close = IconButton("close", size=(30, 30), icon_size=13, radius=9, tooltip="Закрыть")
        close.clicked.connect(self._close)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(15)
        layout.addWidget(CapsLabel("MICROSOFT", size=9, spacing=1.8, accent=True))
        layout.addSpacing(6)
        title = QLabel("Вход через Microsoft")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        layout.addSpacing(5)
        message = QLabel(
            "Откроется браузер Microsoft. Поддерживаются личные, рабочие и "
            "учебные аккаунты. Пароль вводится только на сайте Microsoft."
        )
        message.setObjectName("PageSubtitle")
        message.setWordWrap(True)
        layout.addWidget(message)
        layout.addSpacing(14)
        self.status_label = QLabel("Подключение к Microsoft…")
        self.status_label.setObjectName("Caption")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addSpacing(10)

        open_row = QHBoxLayout()
        open_row.setContentsMargins(0, 0, 0, 0)
        open_row.addStretch(1)
        self.open_button = QPushButton("Открыть браузер снова")
        self.open_button.setObjectName("GhostButton")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(self._start_oauth)
        open_row.addWidget(self.open_button)
        layout.addLayout(open_row)

        layout.addSpacing(10)
        self.manual_hint = QLabel(
            "Если браузер не вернул управление, скопируйте ВСЮ строку из "
            "адресной строки (адрес с ?code=…) и вставьте её сюда. "
            "Код действует около 10 минут."
        )
        self.manual_hint.setObjectName("Caption")
        self.manual_hint.setWordWrap(True)
        self.manual_hint.hide()
        layout.addWidget(self.manual_hint)
        self.manual_open_button = QPushButton("Открыть страницу входа")
        self.manual_open_button.setObjectName("GhostButton")
        self.manual_open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manual_open_button.clicked.connect(self._open_manual_browser)
        self.manual_open_button.hide()
        layout.addWidget(self.manual_open_button)
        self.copy_button = QPushButton("Скопировать ссылку")
        self.copy_button.setObjectName("LinkButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy_auth_url)
        self.copy_button.hide()
        layout.addWidget(self.copy_button)
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText(f"{REDIRECT_URL}/?code=… или код")
        self.code_edit.returnPressed.connect(self._submit_code)
        self.code_edit.hide()
        layout.addWidget(self.code_edit)
        self.code_button = QPushButton("Войти по коду")
        self.code_button.setObjectName("SoftButton")
        self.code_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.code_button.clicked.connect(self._submit_code)
        self.code_button.hide()
        layout.addWidget(self.code_button)
        layout.addSpacing(12)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("Отмена")
        close_button.setObjectName("GhostButton")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setFixedHeight(38)
        close_button.clicked.connect(self._close)
        footer.addWidget(close_button)
        layout.addLayout(footer)
        QTimer.singleShot(100, self._start_oauth)

    def _set_worker(self, worker) -> None:
        self._worker = worker
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        browser_signal = getattr(worker, "browser_requested", None)
        if browser_signal is not None:
            browser_signal.connect(self._open_browser)
        worker.start()

    def _open_browser(self, url: str) -> None:
        self._last_auth_url = url
        self.copy_button.show()
        if not self._launch_browser(url):
            self.status_label.setText(
                "Не удалось открыть браузер. Скопируйте ссылку кнопкой ниже "
                "и откройте её вручную."
            )

    @staticmethod
    def _launch_browser(url: str) -> bool:
        if QDesktopServices.openUrl(QUrl(url)):
            return True
        try:
            if webbrowser.open(url):
                return True
        except Exception:
            pass
        if os.name == "nt":
            try:
                os.startfile(url)  # type: ignore[attr-defined]
                return True
            except OSError:
                pass
        return False

    def _copy_auth_url(self) -> None:
        if self._last_auth_url:
            QApplication.clipboard().setText(self._last_auth_url)
            self.status_label.setText(
                "Ссылка скопирована. Откройте её в любом браузере."
            )

    def _start_oauth(self) -> None:
        if self._worker is not None:
            return
        self._started = True
        self.status_label.setText("Открываем браузер Microsoft…")
        self.open_button.setEnabled(False)
        self._set_worker(MicrosoftOAuthTask(self))

    def _open_manual_browser(self) -> None:
        self.code_edit.clear()
        url = microsoft_login_url()
        self._last_auth_url = url
        self.copy_button.show()
        self.status_label.setText(
            "После входа скопируйте всю строку из адресной строки."
        )
        if not self._launch_browser(url):
            self.status_label.setText(
                "Браузер не открылся. Скопируйте ссылку и откройте вручную."
            )

    def _submit_code(self) -> None:
        if self._worker is not None or self._code_exchange_started:
            return
        code = self.code_edit.text().strip()
        if not code:
            self.status_label.setText("Вставьте код авторизации.")
            return
        self._code_exchange_started = True
        self.status_label.setText("Обмениваем код на токен…")
        self.code_button.setEnabled(False)
        self.code_edit.setEnabled(False)
        self._set_worker(MicrosoftCodeTask(code, self))

    def _on_success(self, account: object) -> None:
        if isinstance(account, Account):
            self.account = account
            self.status_label.setText("Вход выполнен.")

    def _on_failed(self, message: str) -> None:
        if self._cancel_requested:
            return
        self.status_label.setText(message)
        self.open_button.setEnabled(True)
        self.code_button.setEnabled(True)
        self.manual_hint.show()
        self.manual_open_button.show()
        self.code_edit.show()
        self.copy_button.setVisible(bool(self._last_auth_url))
        self.code_button.show()
        self.code_edit.setFocus()

    def _on_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self.open_button.setEnabled(True)
        self.code_button.setEnabled(True)
        self.code_edit.setEnabled(True)
        self._code_exchange_started = False
        if self.account is not None:
            self.accept()
        elif self._cancel_requested:
            self.reject()

    def _close(self) -> None:
        if self._worker is not None:
            self._cancel_requested = True
            cancel = getattr(self._worker, "cancel", None)
            if callable(cancel):
                cancel()
            self.status_label.setText("Отмена входа…")
            return
        self.reject()

    def _on_escape(self) -> None:
        self._close()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._worker is not None:
            event.ignore()
            return
        super().closeEvent(event)
