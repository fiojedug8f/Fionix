"""Account profile: active account, local skin upload and live 3D preview."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.accounts import Account, AccountManager, profile_skin_url
from src.ui.launch_dialogs import OverlayDialog
from src.ui.skin_viewer import Skin3DView
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
        row.addLayout(choose_column, 1)
        layout.addLayout(row)

        self.viewer = Skin3DView()
        self.viewer.set_show_hint(False)
        self.viewer.setFixedHeight(330)
        layout.addSpacing(8)
        layout.addWidget(self.viewer, 1)
        self.hint = QLabel("PNG 64×64 или 64×32. Скин сразу применится к аккаунту.")
        self.hint.setObjectName("Caption")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
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
            return
        image = self._skin_image(account)
        self.viewer.set_skin(image)
        self.avatar.set_image(self._pixmap(image) if not image.isNull() else None)
        self.hint.setText(
            f"{account.username} · {account.provider_label}. "
            "PNG 64×64 или 64×32, до 2 МБ."
        )

    def _on_account_changed(self, _index: int) -> None:
        account = self._current()
        if account is None:
            return
        self.accounts.set_active(account.id)
        self._refresh_current()
        self.changed.emit()

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

    @staticmethod
    def _pixmap(image: QImage):
        from PySide6.QtGui import QPixmap

        return QPixmap.fromImage(image)
