"""Account profile: active account, local skin upload and live 3D preview."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.accounts import Account, AccountManager, profile_skin_url
from src.ui.launch_dialogs import OverlayDialog
from src.ui.skin_viewer import Skin3DView
from src.ui.tasks import MinecraftProfileTask
from src.ui.widgets import AvatarWidget, CapsLabel, GlassComboBox, IconButton


class ProfileDialog(OverlayDialog):
    changed = Signal()

    def __init__(
        self,
        parent: QWidget,
        accounts: AccountManager,
        data_dir: Path,
    ) -> None:
        super().__init__(parent, card_width=650)
        self.accounts = accounts
        self.data_dir = data_dir
        self._network = QNetworkAccessManager(self)
        self._profile_task: MinecraftProfileTask | None = None
        self._profile_id = ""
        self.setWindowTitle("Профиль")
        layout = self.card_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        close = IconButton("close", size=(30, 30), icon_size=13, radius=9, tooltip="Закрыть")
        close.clicked.connect(self.accept)
        header.addWidget(CapsLabel("ПРОФИЛЬ", size=9, spacing=1.8, accent=True))
        header.addStretch(1)
        header.addWidget(close)
        layout.addLayout(header)
        layout.addSpacing(7)
        title = QLabel("Аккаунт и скин")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 0)
        row.setSpacing(10)
        self.avatar = AvatarWidget(size=52)
        row.addWidget(self.avatar)
        choose_column = QVBoxLayout()
        choose_column.setContentsMargins(0, 0, 0, 0)
        choose_column.setSpacing(3)
        account_label = QLabel("Активный аккаунт")
        account_label.setObjectName("FieldLabel")
        choose_column.addWidget(account_label)
        self.account_combo = GlassComboBox()
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        choose_column.addWidget(self.account_combo)
        self.nick_row = QWidget()
        nick_layout = QHBoxLayout(self.nick_row)
        nick_layout.setContentsMargins(0, 4, 0, 0)
        nick_layout.setSpacing(6)
        self.nick_edit = QLineEdit()
        self.nick_edit.setPlaceholderText("Ник 3–16 символов")
        self.nick_edit.setMaxLength(16)
        self.nick_edit.returnPressed.connect(self._save_guest_nick)
        nick_layout.addWidget(self.nick_edit, 1)
        self.nick_save = QPushButton("Сохранить")
        self.nick_save.setObjectName("SoftButton")
        self.nick_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nick_save.clicked.connect(self._save_guest_nick)
        nick_layout.addWidget(self.nick_save)
        self.nick_row.hide()
        choose_column.addWidget(self.nick_row)
        row.addLayout(choose_column, 1)
        layout.addLayout(row)

        self.viewer = Skin3DView()
        self.viewer.set_show_hint(False)
        self.viewer.setFixedHeight(330)
        layout.addSpacing(8)
        layout.addWidget(self.viewer, 1)
        variant_row = QHBoxLayout()
        variant_row.setSpacing(10)
        variant_label = QLabel("Тип модели")
        variant_label.setObjectName("FieldLabel")
        variant_row.addWidget(variant_label)
        self.variant_combo = GlassComboBox()
        self.variant_combo.addItem("Классический (Стив)", "classic")
        self.variant_combo.addItem("Тонкий (Алекс)", "slim")
        self.variant_combo.currentIndexChanged.connect(self._on_variant_changed)
        variant_row.addWidget(self.variant_combo, 1)
        layout.addLayout(variant_row)
        self.hint = QLabel("PNG 64×64 или 64×32. Скин сразу применится к аккаунту.")
        self.hint.setObjectName("Caption")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.capes_frame = QFrame()
        self.capes_frame.setObjectName("InstallInfo")
        capes_layout = QVBoxLayout(self.capes_frame)
        capes_layout.setContentsMargins(12, 8, 12, 8)
        capes_layout.setSpacing(5)
        self.capes_title = QLabel("Плащи Microsoft")
        self.capes_title.setObjectName("FieldLabel")
        capes_layout.addWidget(self.capes_title)
        self.capes_status = QLabel("Загрузка профиля…")
        self.capes_status.setObjectName("Caption")
        self.capes_status.setWordWrap(True)
        capes_layout.addWidget(self.capes_status)
        # Выбранный плащ применяется на сервере асинхронно, и профиль ещё
        # какое-то время отдаёт старый ACTIVE — поэтому выбор держим локально.
        self._capes: list[dict] = []
        self._cape_id = ""
        self.capes_row = QHBoxLayout()
        self.capes_row.setSpacing(6)
        capes_layout.addLayout(self.capes_row)
        self.capes_frame.hide()
        layout.addWidget(self.capes_frame)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        self.upload_button = QPushButton("Загрузить PNG")
        self.upload_button.setObjectName("PrimaryButton")
        self.upload_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upload_button.setFixedHeight(40)
        self.upload_button.clicked.connect(self._upload)
        footer.addWidget(self.upload_button)
        footer.addStretch(1)
        done = QPushButton("Готово")
        done.setObjectName("GhostButton")
        done.setCursor(Qt.CursorShape.PointingHandCursor)
        done.setFixedHeight(40)
        done.clicked.connect(self.accept)
        footer.addWidget(done)
        layout.addLayout(footer)
        self._populate()

    def _populate(self) -> None:
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for account in self.accounts.accounts:
            self.account_combo.addItem(
                f"{account.username} · {account.provider_label}", account.id
            )
        active = self.accounts.current
        if active is not None:
            index = self.account_combo.findData(active.id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        self.account_combo.blockSignals(False)
        self._refresh_current()

    def _current(self) -> Account | None:
        account_id = self.account_combo.currentData()
        return next(
            (account for account in self.accounts.accounts if account.id == account_id),
            self.accounts.current,
        )

    def _skin_image(self, account: Account) -> QImage:
        url = profile_skin_url(account)
        path = Path(url)
        if path.is_file():
            image = QImage(str(path))
            if not image.isNull():
                return image
        return QImage()

    def _refresh_current(self) -> None:
        account = self._current()
        if account is None:
            self.avatar.set_image(None)
            self.viewer.set_skin(None)
            self.capes_frame.hide()
            return
        image = self._skin_image(account)
        self.viewer.set_skin(image)
        self.avatar.set_image(self._pixmap(image) if not image.isNull() else None)
        self.nick_row.setVisible(account.is_guest)
        if account.is_guest:
            self.nick_edit.setText(account.username)
        variant = account.skin_variant if account.skin_variant in {"classic", "slim"} else "classic"
        self.variant_combo.blockSignals(True)
        self.variant_combo.setCurrentIndex(max(0, self.variant_combo.findData(variant)))
        self.variant_combo.blockSignals(False)
        self.viewer.set_variant(variant)
        is_microsoft = account.provider == "microsoft"
        self.capes_frame.setVisible(is_microsoft)
        if is_microsoft:
            self.capes_status.setText("Загрузка скина и плащей…")
            self._load_remote_skin(profile_skin_url(account))
            self._load_microsoft_profile(account)
        self.hint.setText(
            f"{account.username} · {account.provider_label}. "
            + (
                "Смена скина и плаща идёт через Minecraft Services."
                if is_microsoft
                else "PNG 64×64 или 64×32, до 2 МБ."
            )
        )

    def _load_remote_skin(self, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            return
        reply = self._network.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda: self._on_remote_skin(reply))

    def _on_remote_skin(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                image = QImage.fromData(bytes(reply.readAll()))
                if not image.isNull():
                    self.viewer.set_skin(image)
                    self.avatar.set_image(self._pixmap(image))
        finally:
            reply.deleteLater()

    def _load_microsoft_profile(self, account: Account) -> None:
        if self._profile_task is not None and self._profile_task.isRunning():
            return
        self._profile_id = account.id
        task = MinecraftProfileTask(account, "load", parent=self)
        self._profile_task = task
        task.succeeded.connect(
            lambda profile, acc=account: self._on_profile_loaded(acc, profile)
        )
        task.failed.connect(self._on_profile_failed)
        task.finished.connect(task.deleteLater)
        task.finished.connect(lambda: setattr(self, "_profile_task", None))
        task.start()

    def _on_profile_loaded(self, account: Account, profile: object) -> None:
        if not isinstance(profile, dict) or self._current() is None:
            return
        active_skin = ""
        for skin in profile.get("skins", []):
            if isinstance(skin, dict) and skin.get("state") == "ACTIVE":
                active_skin = str(skin.get("url") or "")
        if active_skin:
            self.accounts.update_skin(account.id, active_skin)
            self._load_remote_skin(active_skin)
        capes = [cape for cape in profile.get("capes", []) if isinstance(cape, dict)]
        self._render_capes(account, capes)
        self.capes_status.setText(
            "Выберите плащ или снимите его." if capes else "Доступных плащей нет."
        )

    def _on_profile_failed(self, message: str) -> None:
        self.capes_status.setText(message or "Профиль Microsoft недоступен.")

    def _render_capes(self, account: Account, capes: list[dict]) -> None:
        self._capes = [cape for cape in capes if isinstance(cape, dict)]
        while self.capes_row.count():
            item = self.capes_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        server_id = ""
        server_url = ""
        for cape in self._capes:
            if cape.get("state") == "ACTIVE":
                server_id = str(cape.get("id") or "")
                server_url = str(cape.get("url") or "")
                break
        # Локальный выбор важнее серверного: после смены плаща Mojang ещё
        # отдаёт старый ACTIVE, и галочка «залипала» на прежнем плаще.
        known = {str(cape.get("id") or "") for cape in self._capes}
        if self._cape_id and self._cape_id in known:
            active_id = self._cape_id
            active_url = next(
                str(cape.get("url") or "")
                for cape in self._capes
                if str(cape.get("id") or "") == self._cape_id
            )
        else:
            active_id, active_url = server_id, server_url
            self._cape_id = server_id
        self._load_cape_texture(active_url)
        for cape in self._capes:
            cape_id = str(cape.get("id") or "")
            label = str(cape.get("alias") or "Плащ")
            button = QPushButton(("✓ " if cape_id == active_id else "") + label)
            button.setObjectName("SoftButton" if cape_id == active_id else "GhostButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            cape_url = str(cape.get("url") or "")
            button.clicked.connect(
                lambda _checked=False, cid=cape_id, url=cape_url: self._set_cape(
                    account, cid, url
                )
            )
            button.setToolTip(cape_url)
            self.capes_row.addWidget(button)
        if active_id:
            clear = QPushButton("Снять плащ")
            clear.setObjectName("LinkButton")
            clear.clicked.connect(lambda: self._set_cape(account, None))
            self.capes_row.addWidget(clear)
        self.capes_row.addStretch(1)

    def _load_cape_texture(self, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            self.viewer.set_cape(None)
            return
        if self.viewer._cape_url == url:
            return
        reply = self._network.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda: self._on_cape_ready(reply, url))

    def _on_cape_ready(self, reply: QNetworkReply, url: str) -> None:
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                image = QImage.fromData(bytes(reply.readAll()))
                if not image.isNull():
                    self.viewer.set_cape(image, url)
        finally:
            reply.deleteLater()

    def _set_cape(
        self, account: Account, cape_id: str | None, cape_url: str = ""
    ) -> None:
        # Оптимистично фиксируем выбор: сервер применит его асинхронно, а
        # профиль ещё вернёт прежний ACTIVE. Откатим, если задача упадёт.
        previous = self._cape_id
        self._cape_id = cape_id or ""
        self._load_cape_texture(cape_url)
        self._render_capes(account, self._capes)
        self.capes_status.setText("Применяем плащ…")
        task = MinecraftProfileTask(account, "cape", cape_id=cape_id, parent=self)
        task.succeeded.connect(
            lambda profile, acc=account: self._on_profile_loaded(acc, profile)
        )
        task.failed.connect(
            lambda message, acc=account, old=previous: self._on_cape_failed(
                acc, old, message
            )
        )
        task.finished.connect(task.deleteLater)
        task.start()

    def _on_cape_failed(
        self, account: Account, previous: str, message: str
    ) -> None:
        self._cape_id = previous
        self._render_capes(account, self._capes)
        self._on_profile_failed(message)

    def _on_variant_changed(self, _index: int) -> None:
        account = self._current()
        if account is None:
            return
        variant = str(self.variant_combo.currentData() or "classic")
        self.accounts.set_skin_variant(account.id, variant)
        account.skin_variant = "slim" if variant == "slim" else "classic"
        self.viewer.set_variant(variant)
        self.hint.setText(
            "Тонкая модель (Алекс)" if variant == "slim" else "Классическая модель (Стив)"
        )

    def _on_account_changed(self, _index: int) -> None:
        account = self._current()
        if account is None:
            return
        self.accounts.set_active(account.id)
        self._refresh_current()
        self.changed.emit()

    def _save_guest_nick(self) -> None:
        account = self._current()
        if account is None or not account.is_guest:
            return
        name = self.nick_edit.text().strip()
        if not self.accounts.rename_guest(account.id, name):
            QMessageBox.warning(
                self,
                "Некорректный ник",
                "Ник должен содержать 3–16 букв, цифр или подчёркиваний.",
            )
            return
        self._populate()
        self.changed.emit()
        self.hint.setText(f"Ник изменён: {account.username}")

    def _upload(self) -> None:
        account = self._current()
        if account is None:
            QMessageBox.warning(self, "Профиль", "Аккаунт не выбран.")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Загрузить скин", str(Path.home()), "PNG скин (*.png)"
        )
        if not filename:
            return
        source = Path(filename)
        if source.stat().st_size > 2 * 1024 * 1024:
            QMessageBox.warning(self, "Скин", "Файл скина больше 2 МБ.")
            return
        image = QImage(filename)
        if image.isNull() or (image.width(), image.height()) not in {
            (64, 64),
            (64, 32),
        }:
            QMessageBox.warning(
                self,
                "Некорректный скин",
                "Нужен PNG 64×64 или 64×32 пикселя.",
            )
            return
        if account.provider == "microsoft":
            self.capes_status.setText("Загружаем скин в Minecraft…")
            task = MinecraftProfileTask(
                account,
                "skin",
                skin_path=source,
                variant=account.skin_variant,
                parent=self,
            )
            task.succeeded.connect(
                lambda profile, acc=account, img=image: self._on_skin_uploaded(
                    acc, profile, img
                )
            )
            task.failed.connect(self._on_profile_failed)
            task.finished.connect(task.deleteLater)
            task.start()
            return
        skins_dir = self.data_dir / "skins"
        skins_dir.mkdir(parents=True, exist_ok=True)
        target = skins_dir / f"{account.id}.png"
        if not image.save(str(target), "PNG"):
            QMessageBox.warning(self, "Скин", "Не удалось сохранить файл скина.")
            return
        self.accounts.update_skin(account.id, str(target))
        self.viewer.set_skin(image)
        self.avatar.set_image(self._pixmap(image))
        self.changed.emit()

    def _on_skin_uploaded(
        self, account: Account, profile: object, image: QImage
    ) -> None:
        self.viewer.set_skin(image)
        self.avatar.set_image(self._pixmap(image))
        self.capes_status.setText("Скин обновлён в Minecraft.")
        if isinstance(profile, dict):
            self._on_profile_loaded(account, profile)
        self.changed.emit()

    @staticmethod
    def _pixmap(image: QImage):
        from PySide6.QtGui import QPixmap

        return QPixmap.fromImage(image)
