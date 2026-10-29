"""Left navigation panel."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.accounts import Account, profile_skin_url
from src.core.launcher import LOADER_ICONS, Instance, format_playtime
from src.core.theme import current_theme
from src.ui import icons
from src.ui.widgets import (
    AvatarWidget,
    CapsLabel,
    GlassComboBox,
    HoverButton,
    IconBadge,
    IconButton,
    LogoWidget,
    NavButton,
    font,
)


class SidebarInstanceButton(HoverButton):
    """Compact clickable instance row in the sidebar."""

    def __init__(self, instance: Instance, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.instance = instance
        self._active = False
        self.setFixedHeight(45)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(f"{instance.name}\n{instance.path}")
        self.setAccessibleName(f"Открыть {instance.name}")

    def set_active(self, active: bool) -> None:
        if self._active != active:
            self._active = active
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        if self._active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 120, 212, 48))
            painter.drawRoundedRect(rect, 10, 10)
            painter.setBrush(theme.accent)
            painter.drawRoundedRect(QRectF(0, 8, 3, rect.height() - 16), 1.5, 1.5)
        elif self._hover > 0.01:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, int(22 * self._hover)))
            painter.drawRoundedRect(rect, 10, 10)

        icon_rect = QRectF(8, rect.center().y() - 9, 18, 18)
        custom = QPixmap(self.instance.icon_path) if self.instance.icon_path else QPixmap()
        if not custom.isNull():
            painter.drawPixmap(
                icon_rect.toRect(),
                custom.scaled(
                    icon_rect.size().toSize(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )
        else:
            icons.draw_icon(
                painter,
                LOADER_ICONS.get(self.instance.loader, "cube"),
                icon_rect,
                theme.text_secondary if self._hover > 0.4 else theme.text_muted,
                1.6,
            )

        metrics = QFontMetrics(font(11, QFont.Weight.DemiBold))
        playtime = format_playtime(self.instance.playtime_seconds)
        playtime_width = QFontMetrics(font(9)).horizontalAdvance(playtime)
        text_rect = QRectF(33, rect.top(), rect.width() - 44 - playtime_width, rect.height())
        title = metrics.elidedText(
            self.instance.name, Qt.TextElideMode.ElideRight, int(text_rect.width())
        )
        painter.setFont(font(11, QFont.Weight.DemiBold))
        painter.setPen(
            theme.text
            if self._active
            else (theme.text_secondary if self._hover > 0.4 else theme.text_muted)
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            title,
        )

        painter.setFont(font(9))
        painter.setPen(theme.text_muted)
        painter.drawText(
            QRectF(rect.right() - playtime_width - 8, rect.top(), playtime_width + 2, rect.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
            playtime,
        )


class Sidebar(QFrame):
    """Glass sidebar with navigation, guest profile and instances stub."""

    page_changed = Signal(str)
    create_instance_requested = Signal()
    instance_selected = Signal(object)
    account_selected = Signal(str)
    profile_requested = Signal()
    account_add_requested = Signal()
    token_refresh_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, version: str = "2.0.0") -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(266)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._accounts: list[Account] = []
        self._active_account: Account | None = None
        self._skin_manager = QNetworkAccessManager(self)
        self._pending_skin_id = ""
        self._instance_buttons: list[SidebarInstanceButton] = []
        self._active_instance_id = ""

        self._nav_buttons: dict[str, NavButton] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(0)

        layout.addWidget(LogoWidget())
        layout.addSpacing(22)

        profile = self._build_profile()
        layout.addWidget(profile)
        layout.addSpacing(24)

        navigation_label = CapsLabel("НАВИГАЦИЯ", muted=True)
        navigation_wrap = QHBoxLayout()
        navigation_wrap.setContentsMargins(12, 0, 4, 0)
        navigation_wrap.addWidget(navigation_label)
        navigation_wrap.addStretch(1)
        layout.addLayout(navigation_wrap)
        layout.addSpacing(8)

        for key, title, icon_name in (
            ("home", "Главная", "home"),
            ("store", "Магазин", "store"),
            ("settings", "Настройки", "settings"),
        ):
            button = NavButton(title, icon_name)
            button.setToolTip(title)
            self._button_group.addButton(button)
            self._nav_buttons[key] = button
            button.clicked.connect(lambda _checked=False, page=key: self.page_changed.emit(page))
            layout.addWidget(button)
            layout.addSpacing(4)

        instances_header = QHBoxLayout()
        instances_header.setContentsMargins(12, 0, 2, 0)
        instances_header.setSpacing(8)
        instances_header.addWidget(CapsLabel("ЭКЗЕМПЛЯРЫ", muted=True))
        instances_header.addStretch(1)

        self.count_label = QLabel("0")
        self.count_label.setObjectName("CountChip")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instances_header.addWidget(self.count_label)

        add_button = IconButton(
            "plus",
            size=(24, 24),
            icon_size=12,
            radius=7,
            tooltip="Создать экземпляр",
        )
        add_button.clicked.connect(self.create_instance_requested.emit)
        instances_header.addWidget(add_button)
        layout.addLayout(instances_header)
        layout.addSpacing(9)

        self.instances_empty = self._build_instances_empty()
        layout.addWidget(self.instances_empty)

        self.instances_scroll = QScrollArea()
        self.instances_scroll.setObjectName("SidebarInstances")
        self.instances_scroll.setWidgetResizable(True)
        self.instances_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.instances_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.instances_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.instances_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.instances_scroll.viewport().setAutoFillBackground(False)
        self.instances_list_widget = QWidget()
        self.instances_list_widget.setObjectName("SidebarInstancesList")
        self.instances_list_layout = QVBoxLayout(self.instances_list_widget)
        self.instances_list_layout.setContentsMargins(0, 0, 2, 0)
        self.instances_list_layout.setSpacing(2)
        self.instances_list_layout.addStretch(1)
        self.instances_scroll.setWidget(self.instances_list_widget)
        self.instances_scroll.hide()
        layout.addWidget(self.instances_scroll, 1)

        layout.addSpacing(12)

        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(12)

        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)
        version_label = QLabel(f"v{version}")
        version_label.setObjectName("Caption")
        footer.addWidget(version_label)
        footer.addStretch(1)
        layout.addLayout(footer)

        self.set_active("home")

    # ------------------------------------------------------------------ ui
    def _build_profile(self) -> QFrame:
        profile = QFrame()
        profile.setObjectName("ProfileCard")
        profile.setFixedHeight(150)
        profile.setToolTip("Аккаунт и быстрый переход между профилями")

        layout = QVBoxLayout(profile)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        self.avatar = AvatarWidget(size=42)
        self.avatar.setToolTip("Открыть профиль")
        self.avatar.clicked.connect(self.profile_requested.emit)
        top.addWidget(self.avatar)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self.profile_name = QLabel("Гость")
        self.profile_name.setObjectName("ProfileName")
        self.profile_role = QLabel("Локальный профиль")
        self.profile_role.setObjectName("ProfileRole")
        text_layout.addStretch(1)
        text_layout.addWidget(self.profile_name)
        text_layout.addWidget(self.profile_role)
        text_layout.addStretch(1)
        top.addLayout(text_layout, 1)
        self.add_account_button = IconButton(
            "plus",
            size=(24, 24),
            icon_size=12,
            radius=7,
            tooltip="Добавить аккаунт",
        )
        self.add_account_button.clicked.connect(self.account_add_requested.emit)
        top.addWidget(self.add_account_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(top)

        self.account_combo = GlassComboBox()
        self.account_combo.setAccessibleName("Выбор аккаунта")
        self.account_combo.setMinimumHeight(28)
        self.account_combo.activated.connect(self._on_account_activated)
        layout.addWidget(self.account_combo)

        self.token_button = QPushButton("✓ Токен активен")
        self.token_button.setObjectName("TokenButton")
        self.token_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.token_button.setFixedHeight(28)
        self.token_button.setToolTip("Проверить и обновить токен аккаунта")
        self.token_button.clicked.connect(self._request_token_refresh)
        layout.addWidget(self.token_button)

        self._token_timer = QTimer(self)
        self._token_timer.setInterval(60_000)
        self._token_timer.timeout.connect(self._update_token_button)
        self._token_timer.start()
        return profile

    def _on_account_activated(self, index: int) -> None:
        account_id = self.account_combo.itemData(index)
        if isinstance(account_id, str) and account_id:
            self.account_selected.emit(account_id)

    def _request_token_refresh(self) -> None:
        if self._active_account is not None:
            self.token_refresh_requested.emit(self._active_account.id)

    def _update_token_button(self) -> None:
        account = self._active_account
        if (
            account is None
            or account.is_guest
            or account.provider != "microsoft"
            or not account.access_token
        ):
            self.token_button.hide()
            return
        self.token_button.show()
        expired = account.token_expired
        if expired:
            text = "✕ Токен истёк · обновить"
            state = "expired"
        else:
            text = f"✓ Токен · {account.token_remaining_text()}"
            state = "valid"
        self.token_button.setText(text)
        self.token_button.setProperty("state", state)
        self.token_button.style().unpolish(self.token_button)
        self.token_button.style().polish(self.token_button)
        if account.expires_at:
            self.token_button.setToolTip(
                f"Истекает: {account.expires_at.replace('T', ' ')[:16]}\n"
                "Нажмите, чтобы обновить токен."
            )
        else:
            self.token_button.setToolTip(
                "Срок действия не указан. Нажмите, чтобы обновить токен."
            )

    def set_accounts(self, accounts: list[Account], active_id: str = "") -> None:
        self._accounts = list(accounts)
        active = next((item for item in accounts if item.id == active_id), None)
        if active is None and accounts:
            active = accounts[0]
        self._active_account = active
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        if accounts:
            for account in accounts:
                self.account_combo.addItem(
                    f"{account.username} · {account.provider_label}", account.id
                )
            if active is not None:
                index = self.account_combo.findData(active.id)
                if index >= 0:
                    self.account_combo.setCurrentIndex(index)
            self.account_combo.setEnabled(True)
        else:
            self.account_combo.addItem("Нет аккаунта", "")
            self.account_combo.setEnabled(False)
        self.account_combo.blockSignals(False)
        if active is None:
            self.profile_name.setText("Гость")
            self.profile_role.setText("Локальный профиль")
            self.avatar.set_image(None)
            self.token_button.hide()
            return
        self.profile_name.setText(active.username)
        self.profile_role.setText(active.provider_label)
        self._update_token_button()
        self._load_skin(active)

    # ----------------------------------------------------------------- skin
    def _load_skin(self, account: Account) -> None:
        url = profile_skin_url(account)
        self._pending_skin_id = account.id
        if not url:
            self.avatar.set_image(None)
            return
        if "://" in url:
            qurl = QUrl(url)
        else:
            qurl = QUrl.fromLocalFile(url)
        request = QNetworkRequest(qurl)
        request.setRawHeader(QByteArray(b"User-Agent"), QByteArray(b"Fionix/1.0"))
        reply = self._skin_manager.get(request)
        reply.finished.connect(
            lambda reply=reply, account_id=account.id, url=url: self._on_skin_reply(
                reply, account_id, url
            )
        )

    def _on_skin_reply(self, reply: QNetworkReply, account_id: str, url: str) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                return
            data = bytes(reply.readAll())
            if "sessionserver" in url and data:
                try:
                    payload = json.loads(data.decode("utf-8"))
                    properties = payload.get("properties", [])
                    if properties:
                        decoded = base64.b64decode(properties[0].get("value", ""))
                        textures = json.loads(decoded.decode("utf-8"))
                        skin_url = (
                            textures.get("textures", {})
                            .get("SKIN", {})
                            .get("url", "")
                        )
                        if skin_url:
                            self._request_pixmap(skin_url, account_id)
                            return
                except (ValueError, KeyError, TypeError):
                    pass
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self._apply_skin(account_id, pixmap)
        finally:
            reply.deleteLater()

    def _request_pixmap(self, url: str, account_id: str) -> None:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(QByteArray(b"User-Agent"), QByteArray(b"Fionix/1.0"))
        reply = self._skin_manager.get(request)
        reply.finished.connect(lambda: self._on_pixmap_reply(reply, account_id))

    def _on_pixmap_reply(self, reply: QNetworkReply, account_id: str) -> None:
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                pixmap = QPixmap()
                if pixmap.loadFromData(bytes(reply.readAll())):
                    self._apply_skin(account_id, pixmap)
        finally:
            reply.deleteLater()

    def _apply_skin(self, account_id: str, pixmap: QPixmap) -> None:
        if (
            self._active_account is not None
            and self._active_account.id == account_id
            and self._pending_skin_id == account_id
        ):
            self.avatar.set_image(pixmap)

    def _build_instances_empty(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("SidebarEmpty")
        frame.setMinimumHeight(104)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge = IconBadge("cube", size=32, icon_size=17, radius=10)
        title = QLabel("У вас пока нет сборок")
        title.setObjectName("EmptyText")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Создайте первый экземпляр")
        hint.setObjectName("Caption")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint, 0, Qt.AlignmentFlag.AlignCenter)
        return frame

    # ---------------------------------------------------------------- state
    def set_instances(self, instances: list[Instance]) -> None:
        self.count_label.setText(str(len(instances)))
        while self.instances_list_layout.count() > 1:
            item = self.instances_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._instance_buttons = []
        for instance in instances:
            button = SidebarInstanceButton(instance)
            button.set_active(instance.folder_name == self._active_instance_id)
            button.clicked.connect(
                lambda _checked=False, item=instance: self.instance_selected.emit(item)
            )
            self._instance_buttons.append(button)
            self.instances_list_layout.insertWidget(
                self.instances_list_layout.count() - 1, button
            )
        if instances:
            self.instances_empty.hide()
            self.instances_scroll.show()
        else:
            self.instances_scroll.hide()
            self.instances_empty.show()

    def set_active(self, key: str) -> None:
        self._active_instance_id = ""
        for instance_button in self._instance_buttons:
            instance_button.set_active(False)
        button = self._nav_buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_active_instance(self, instance_id: str) -> None:
        self._active_instance_id = instance_id or ""
        self._button_group.setExclusive(False)
        for button in self._nav_buttons.values():
            button.setChecked(False)
        self._button_group.setExclusive(True)
        for button in self._instance_buttons:
            button.set_active(
                button.instance.folder_name == self._active_instance_id
            )

    def current_page(self) -> str:
        if self._active_instance_id:
            return "instance"
        for key, button in self._nav_buttons.items():
            if button.isChecked():
                return key
        return "home"

    def set_player(self, name: str) -> None:
        if self._active_account is None:
            self.profile_name.setText(name or "Гость")
