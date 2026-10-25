"""Full-screen content hub with Installed and Modrinth/CurseForge Market tabs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QThread,
    QTimer,
    QUrl,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.core.launcher import Instance, LauncherService
from src.core.market_api import MarketAPI, MarketProject
from src.core.theme import current_theme
from src.ui import icons
from src.ui.instance_dialogs import ContentFileRow, plural_files
from src.ui.downloads import downloads
from src.ui.launch_dialogs import OverlayDialog
from src.ui.pages import Page
from src.ui.tasks import MarketInstallTask, MarketSearchTask
from src.ui.widgets import CapsLabel, GlassComboBox, IconBadge, IconButton


class ModIcon(QWidget):
    """Small network-loaded icon with a graceful placeholder."""

    def __init__(self, manager: QNetworkAccessManager, size: int = 48) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self._manager = manager
        self._pixmap: QPixmap | None = None
        self._size = size

    def load(self, url: str) -> None:
        if not url:
            return
        reply = self._manager.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda: self._on_reply(reply))

    def _on_reply(self, reply) -> None:
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                pixmap = QPixmap()
                if pixmap.loadFromData(bytes(reply.readAll())):
                    self._pixmap = pixmap.scaled(
                        self.size(),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.update()
        finally:
            reply.deleteLater()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        from PySide6.QtGui import QColor, QPainter, QPainterPath

        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 12, 12)
        if self._pixmap is None:
            painter.fillPath(path, theme.accent_soft)
            painter.setPen(QColor(theme.accent_border))
            painter.drawPath(path)
            icon_rect = self.rect().adjusted(
                int(self._size * 0.25),
                int(self._size * 0.25),
                -int(self._size * 0.25),
                -int(self._size * 0.25),
            )
            icons.draw_icon(
                painter, "puzzle", icon_rect, theme.accent_light, 1.8
            )
            return
        painter.setClipPath(path)
        painter.drawPixmap(self.rect(), self._pixmap)


class LoadingSpinner(QWidget):
    """Small animated arc used on a mod card while its file is downloading."""

    def __init__(self, parent: QWidget | None = None, *, size: int = 17) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 28) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        painter.setPen(QPen(theme.accent_soft, 2.5))
        painter.drawArc(rect, 0, 360 * 16)
        painter.setPen(QPen(theme.accent_light, 2.5))
        painter.drawArc(rect, int(self._angle * 16), 110 * 16)


class ModCard(QPushButton):
    clicked_project = Signal(object)
    install_clicked = Signal(object)

    def __init__(
        self,
        project: MarketProject,
        manager: QNetworkAccessManager,
        instance_version: str = "",
        instance_loader: str = "",
    ) -> None:
        super().__init__()
        self.project = project
        self._install_state = ""
        self._compatible = self._is_compatible(
            project, instance_version, instance_loader
        )
        self._icon = ModIcon(manager, 48)
        self._icon.load(project.icon_url)
        self.setObjectName("ModCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(project.description)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 12, 13, 10)
        layout.setSpacing(7)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        top.addWidget(self._icon)
        self.warning = QLabel("Несовместимо")
        self.warning.setObjectName("IncompatibleBadge")
        self.warning.setToolTip(
            f"Мод не поддерживает Minecraft {instance_version} / {instance_loader}."
        )
        self.warning.setVisible(not self._compatible)
        top.addWidget(self.warning, 0, Qt.AlignmentFlag.AlignTop)
        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 1, 0, 0)
        title_column.setSpacing(2)
        name = QLabel(project.name)
        name.setObjectName("ModCardTitle")
        name.setWordWrap(True)
        author = QLabel(f"{project.author} · {project.source}")
        author.setObjectName("Caption")
        title_column.addWidget(name)
        title_column.addWidget(author)
        top.addLayout(title_column, 1)
        layout.addLayout(top)
        description = QLabel(project.description)
        description.setObjectName("ModCardText")
        description.setWordWrap(True)
        description.setMaximumHeight(38)
        layout.addWidget(description)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(7)
        downloads = QLabel(f"{project.downloads:,} загрузок".replace(",", " "))
        downloads.setObjectName("Caption")
        bottom.addWidget(downloads, 1)
        self.spinner = LoadingSpinner(self)
        self.spinner.hide()
        bottom.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        self.install_status = QLabel("")
        self.install_status.setObjectName("ModCardStatus")
        bottom.addWidget(self.install_status, 0, Qt.AlignmentFlag.AlignVCenter)
        self.install_button = QPushButton("Установить")
        self.install_button.setObjectName("SoftButton")
        self.install_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_button.setFixedHeight(26)
        self.install_button.clicked.connect(
            lambda: self.install_clicked.emit(self.project)
        )
        bottom.addWidget(self.install_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(bottom)
        self.clicked.connect(lambda: self.clicked_project.emit(self.project))
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.install_button.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
        )
        self.install_button.raise_()

    @staticmethod
    def _is_compatible(project: MarketProject, version: str, loader: str) -> bool:
        if not version or not loader:
            return True
        versions = tuple(project.game_versions or ())
        loaders = tuple(str(item).lower() for item in project.loaders or ())
        version_ok = not versions or version in versions
        aliases = {
            "fabric": {"fabric", "quilt"},
            "quilt": {"fabric", "quilt"},
            "forge": {"forge"},
            "neoforge": {"neoforge", "forge"},
            "vanilla": {"vanilla"},
        }
        loader_ok = not loaders or loader.lower() in loaders or any(
            loader.lower() in aliases.get(item, {item}) for item in loaders
        )
        return version_ok and loader_ok

    def set_installing(self, percent: int = 0) -> None:
        self._install_state = "installing"
        self.spinner.start()
        self.install_status.setText(
            f"Загрузка {max(0, min(99, percent))}%" if percent else "Загрузка…"
        )
        self.install_status.setProperty("state", "working")
        self._repolish_status()

    def set_progress(self, percent: int) -> None:
        if self._install_state == "installing":
            self.install_status.setText(f"Загрузка {max(0, min(99, percent))}%")

    def set_installed(self) -> None:
        self._install_state = "installed"
        self.spinner.stop()
        self.install_status.setText("Установлено")
        self.install_status.setProperty("state", "done")
        self._repolish_status()

    def set_failed(self, message: str = "") -> None:
        self._install_state = "failed"
        self.spinner.stop()
        self.install_status.setText("Ошибка")
        self.install_status.setToolTip(message)
        self.install_status.setProperty("state", "error")
        self._repolish_status()

    def _repolish_status(self) -> None:
        self.install_status.style().unpolish(self.install_status)
        self.install_status.style().polish(self.install_status)
        self.install_status.update()


class DetailsTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, api: MarketAPI, project: MarketProject, parent=None) -> None:
        super().__init__(parent)
        self._api = api
        self._project = project

    def run(self) -> None:
        try:
            if self._project.source == "modrinth":
                detailed = self._api.modrinth_project(self._project.id)
                self.succeeded.emit(detailed)
            else:
                self.succeeded.emit(self._project)
        except Exception as exc:
            self.failed.emit(str(exc))


class ModDetailDialog(OverlayDialog):
    install_requested = Signal(object, bool)

    def __init__(
        self,
        parent: QWidget,
        api: MarketAPI,
        project: MarketProject,
        *,
        loader: str = "vanilla",
    ) -> None:
        super().__init__(parent, card_width=720)
        self._api = api
        self._project = project
        self._loader = loader
        self._task: DetailsTask | None = None
        layout = self.card_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(14)
        self._badge = IconBadge("puzzle", size=58, icon_size=27, radius=16)
        header.addWidget(self._badge)
        text = QVBoxLayout()
        text.setContentsMargins(0, 1, 0, 0)
        text.setSpacing(3)
        self.title_label = QLabel(project.name)
        self.title_label.setObjectName("DialogTitle")
        self.meta_label = QLabel(f"{project.author} · {project.source}")
        self.meta_label.setObjectName("FieldHint")
        text.addWidget(self.title_label)
        text.addWidget(self.meta_label)
        versions = ", ".join(project.game_versions[:6]) or "все версии"
        loaders = ", ".join(project.loaders[:4]) or "любой загрузчик"
        self.versions_label = QLabel(f"Minecraft: {versions}  ·  {loaders}")
        self.versions_label.setObjectName("Caption")
        self.versions_label.setWordWrap(True)
        text.addWidget(self.versions_label)
        header.addLayout(text, 1)
        close = IconButton("close", size=(30, 30), icon_size=13, radius=9, tooltip="Закрыть")
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(16)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        self.body.setMinimumHeight(240)
        self.body.setMaximumHeight(330)
        self.body.setObjectName("ModBody")
        self.body.setMarkdown(project.description or "_Описание не указано._")
        layout.addWidget(self.body)
        layout.addSpacing(10)
        self.dependencies_label = QLabel("")
        self.dependencies_label.setObjectName("Caption")
        self.dependencies_label.setWordWrap(True)
        layout.addWidget(self.dependencies_label)
        layout.addSpacing(12)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self.install_button = QPushButton("Установить")
        self.install_button.setObjectName("SoftButton")
        self.install_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_button.setFixedHeight(42)
        self.install_button.clicked.connect(self._install)
        footer.addWidget(self.install_button)
        footer.addStretch(1)
        close_button = QPushButton("Закрыть")
        close_button.setObjectName("GhostButton")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setFixedHeight(42)
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)
        layout.addLayout(footer)
        if project.source == "modrinth":
            self._task = DetailsTask(api, project, self.window())
            self._task.succeeded.connect(self._on_details)
            self._task.failed.connect(self._on_details_failed)
            self._task.start()
        else:
            self.dependencies_label.setText("CurseForge не отдаёт список зависимостей через этот запрос.")

    def _on_details(self, project: object) -> None:
        if isinstance(project, MarketProject):
            self._project = project
            self.body.setMarkdown(project.body or project.description or "_Описание не указано._")

    def _on_details_failed(self, message: str) -> None:
        self.dependencies_label.setText(f"Не удалось загрузить полное описание: {message}")

    def _install(self) -> None:
        if self._project.source == "curseforge":
            include_dependencies = False
        else:
            if self._loader in ("fabric", "quilt"):
                text = (
                    "Установить обязательные зависимости автоматически?\n"
                    "Многим Fabric/Quilt-модам нужен Fabric API."
                )
            else:
                text = (
                    "Установить обязательные зависимости автоматически, "
                    "если они указаны автором мода?"
                )
            answer = QMessageBox.question(
                self,
                "Зависимости мода",
                text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            include_dependencies = answer == QMessageBox.StandardButton.Yes
        self.install_requested.emit(self._project, include_dependencies)
        self.accept()


class MarketPage(Page):
    back_requested = Signal()
    content_changed = Signal()
    details_requested = Signal(object, str)
    queued_install_requested = Signal(object, str)
    error_notified = Signal(str)

    def __init__(self, service: LauncherService, parent: QWidget | None = None) -> None:
        super().__init__(parent, margins=(30, 18, 30, 24), spacing=12)
        self._service = service
        self._api = MarketAPI(service.config)
        self._instance: Instance | None = None
        self._search_task: MarketSearchTask | None = None
        self._search_mode = ""
        self._install_tasks: dict[str, MarketInstallTask] = {}
        self._cards: dict[str, ModCard] = {}
        self._popular_loaded = False
        self._icon_manager = QNetworkAccessManager(self)
        self._projects: list[MarketProject] = []
        self._offset = 0
        self._has_more = False
        self._appending = False
        self._query = ""
        self._popular = False
        self._rows: list[ContentFileRow] = []
        self._source = "modrinth"
        self._project_type = "mod"

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        self.back_button = IconButton(
            "chevron_left", size=(36, 36), icon_size=18, radius=10, tooltip="Назад"
        )
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(2)
        self.title_label = QLabel("Моды")
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("PageSubtitle")
        title_column.addWidget(self.title_label)
        title_column.addWidget(self.subtitle_label)
        header.addLayout(title_column, 1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Badge")
        header.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addLayout(header)
        self.body.addSpacing(4)

        tabs = QHBoxLayout()
        tabs.setContentsMargins(0, 0, 0, 0)
        tabs.setSpacing(4)
        self.installed_tab = QPushButton("Установленные")
        self.installed_tab.setObjectName("TabButton")
        self.installed_tab.setCheckable(True)
        self.installed_tab.setChecked(True)
        self.market_tab = QPushButton("Маркет")
        self.market_tab.setObjectName("TabButton")
        self.market_tab.setCheckable(True)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        for tab in (self.installed_tab, self.market_tab):
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            self._tab_group.addButton(tab)
            tabs.addWidget(tab)
        tabs.addStretch(1)
        self.body.addLayout(tabs)
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        self.body.addWidget(divider)

        self.pages = QStackedWidget()
        self.pages.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.body.addWidget(self.pages, 1)
        self._build_installed_page()
        self._build_market_page()
        self.installed_tab.clicked.connect(self._show_installed_tab)
        self.market_tab.clicked.connect(self._show_market_tab)

    def _build_installed_page(self) -> None:
        page = QWidget()
        page.setObjectName("Page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        self.installed_count = QLabel("")
        self.installed_count.setObjectName("Muted")
        toolbar.addWidget(self.installed_count, 1)
        refresh = QPushButton("Обновить")
        refresh.setObjectName("LinkButton")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self.reload_installed)
        toolbar.addWidget(refresh)
        open_folder = QPushButton("Открыть папку")
        open_folder.setObjectName("GhostButton")
        open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder.setFixedHeight(34)
        open_folder.clicked.connect(self._open_folder)
        toolbar.addWidget(open_folder)
        layout.addLayout(toolbar)
        self.installed_scroll = QScrollArea()
        self.installed_scroll.setWidgetResizable(True)
        self.installed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.installed_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.installed_widget = QWidget()
        self.installed_widget.setObjectName("ContentList")
        self.installed_layout = QVBoxLayout(self.installed_widget)
        self.installed_layout.setContentsMargins(0, 0, 4, 0)
        self.installed_layout.setSpacing(6)
        self.installed_layout.addStretch(1)
        self.installed_scroll.setWidget(self.installed_widget)
        layout.addWidget(self.installed_scroll, 1)
        self.pages.addWidget(page)

    def _build_market_page(self) -> None:
        page = QWidget()
        page.setObjectName("Page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск модов…")
        self.search_edit.setMinimumHeight(40)
        self.search_edit.returnPressed.connect(self.search)
        search_row.addWidget(self.search_edit, 1)
        self.source_combo = GlassComboBox()
        self.source_combo.addItem("Modrinth", "modrinth")
        if self._api.curseforge_key:
            self.source_combo.addItem("CurseForge", "curseforge")
        self.source_combo.setFixedWidth(160)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        search_row.addWidget(self.source_combo, 0)
        self.search_button = QPushButton("Найти")
        self.search_button.setObjectName("SoftButton")
        self.search_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_button.setFixedHeight(40)
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        if not self._api.curseforge_key:
            note = QLabel("CurseForge временно недоступен")
            note.setObjectName("Caption")
            layout.addWidget(note)

        self.market_status = QLabel("Введите запрос или нажмите «Найти», чтобы увидеть моды.")
        self.market_status.setObjectName("Muted")
        self.market_status.setWordWrap(True)
        layout.addWidget(self.market_status)
        self.market_scroll = QScrollArea()
        self.market_scroll.setWidgetResizable(True)
        self.market_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.market_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.market_host = QWidget()
        self.market_host.setObjectName("ContentList")
        self.market_grid = QGridLayout(self.market_host)
        self.market_grid.setContentsMargins(0, 0, 4, 0)
        self.market_grid.setSpacing(10)
        self.market_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.market_scroll.setWidget(self.market_host)
        self.market_scroll.verticalScrollBar().valueChanged.connect(
            self._on_market_scroll
        )
        layout.addWidget(self.market_scroll)
        self.more_row = QWidget()
        more_layout = QHBoxLayout(self.more_row)
        more_layout.setContentsMargins(0, 4, 0, 4)
        self.more_spinner = LoadingSpinner(size=18)
        more_layout.addWidget(self.more_spinner)
        more_layout.addWidget(QLabel("Загружаем ещё…"))
        more_layout.addStretch(1)
        self.more_row.hide()
        layout.addWidget(self.more_row)
        pager = QHBoxLayout()
        self.market_page_label = QLabel("Страница 1")
        self.market_page_label.setObjectName("Caption")
        pager.addWidget(self.market_page_label)
        pager.addStretch(1)
        self.prev_button = QPushButton("← Назад")
        self.prev_button.setObjectName("GhostButton")
        self.prev_button.clicked.connect(self._previous_market_page)
        self.next_button = QPushButton("Вперёд →")
        self.next_button.setObjectName("GhostButton")
        self.next_button.clicked.connect(self._next_market_page)
        for button in (self.prev_button, self.next_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(34)
            pager.addWidget(button)
        layout.addLayout(pager)
        self._page_index = 1
        self.pages.addWidget(page)
        self._update_pager()

    # ---------------------------------------------------------------- state
    def set_instance(self, instance: Instance, category: str = "mod") -> None:
        if self._instance is not None and self._instance.path != instance.path:
            self._cancel_installs()
        self._instance = instance
        self._project_type = category if category in {
            "mod", "resourcepack", "shader", "map"
        } else "mod"
        labels = {
            "mod": "Моды",
            "resourcepack": "Текстурпаки",
            "shader": "Шейдеры",
            "map": "Карты",
        }
        self._popular_loaded = False
        self._search_mode = ""
        self._offset = 0
        self._has_more = False
        self._appending = False
        self._page_index = 1
        self.more_row.hide()
        self.more_spinner.stop()
        self.title_label.setText(labels[self._project_type])
        self.subtitle_label.setText(
            f"{instance.name} · Minecraft {instance.version} · {instance.loader_name}"
        )
        self._update_curseforge_panel()
        self.reload_installed()
        if self.pages.currentIndex() == 1:
            QTimer.singleShot(0, self._ensure_popular)

    def _fade_tab(self, widget: QWidget) -> None:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(170)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: widget.setGraphicsEffect(None))
        self._tab_animation = animation
        animation.start()

    def _show_installed_tab(self) -> None:
        self.installed_tab.setChecked(True)
        self.pages.setCurrentIndex(0)
        self._fade_tab(self.pages.currentWidget())
        self.reload_installed()

    def _show_market_tab(self) -> None:
        self.market_tab.setChecked(True)
        self.pages.setCurrentIndex(1)
        self._fade_tab(self.pages.currentWidget())
        self._ensure_popular()

    def _ensure_popular(self) -> None:
        if (
            self._instance is None
            or self._source != "modrinth"
            or self._popular_loaded
            or self._search_task is not None
        ):
            return
        self._start_search("", "popular", popular=True)

    def _update_curseforge_panel(self) -> None:
        # The key is a build-time config.py value; there is no player UI.
        pass

    def reload_installed(self) -> None:
        if self._instance is None:
            return
        while self.installed_layout.count() > 1:
            item = self.installed_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()
        category_key = {
            "mod": "mods",
            "resourcepack": "texturepacks",
            "shader": "shaders",
            "map": "maps",
        }.get(self._project_type, "mods")
        files = self._service.list_content(self._instance, category_key)
        if not files:
            empty = QFrame()
            empty.setObjectName("ContentEmpty")
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(12, 26, 12, 26)
            empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(
                IconBadge("puzzle", size=42, icon_size=20),
                0,
                Qt.AlignmentFlag.AlignCenter,
            )
            label = QLabel(f"В этой сборке пока нет {category_key}")
            label.setObjectName("EmptyTitle")
            empty_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignCenter)
            hint = QLabel("Откройте вкладку «Маркет», чтобы установить контент.")
            hint.setObjectName("EmptyText")
            empty_layout.addWidget(hint, 0, Qt.AlignmentFlag.AlignCenter)
            self.installed_layout.insertWidget(0, empty)
        else:
            category = self._service.content_category(category_key)
            for content in files:
                row = ContentFileRow(
                    self._service,
                    self._instance,
                    category,
                    content,
                    self._after_toggle,
                )
                self._rows.append(row)
                self.installed_layout.insertWidget(
                    self.installed_layout.count() - 1, row
                )
        total = len(files)
        disabled = sum(1 for item in files if not item.enabled)
        text = f"{total} {plural_files(total)} · отключено: {disabled}"
        self.installed_count.setText(text)
        self.count_label.setText(text)

    def _after_toggle(self) -> None:
        self.reload_installed()
        self.content_changed.emit()

    def _open_folder(self) -> None:
        if self._instance is None:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        folder = self._service.content_dir(self._instance, "mods")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_source_changed(self, index: int) -> None:
        data = self.source_combo.itemData(index)
        self._source = str(data or "modrinth")
        self._popular_loaded = False
        self._update_curseforge_panel()
        if self._source == "curseforge" and not self._api.curseforge_key:
            self.market_status.setText("CurseForge временно недоступен.")
            self._clear_results()
            self._projects = []
            return
        self.market_status.setText("Нажмите «Найти», чтобы обновить результаты.")

    def search(self) -> None:
        if self._instance is None:
            return
        if self._source == "curseforge" and not self._api.curseforge_key:
            self.market_status.setText("CurseForge временно недоступен.")
            return
        if self._search_task is not None:
            return
        query = self.search_edit.text().strip()
        if not query and self._source == "modrinth":
            self._popular_loaded = False
            self._ensure_popular()
            return
        self._start_search(query, "search")

    def _start_search(
        self,
        query: str,
        mode: str,
        *,
        popular: bool = False,
        append: bool = False,
    ) -> None:
        if self._instance is None:
            return
        if not append:
            self._query = query
            self._popular = popular
            self._offset = 0
            self._has_more = False
            self._page_index = 1
            self._clear_results()
            self._projects = []
        self._appending = append
        self.search_button.setEnabled(False)
        self.market_status.setText(
            "Загружаем популярные моды…" if popular else "Ищем моды…"
        )
        if append:
            self.more_row.show()
            self.more_spinner.start()
        task = MarketSearchTask(
            self._api,
            self._query,
            self._instance.version,
            self._instance.loader,
            self._source,
            self,
            popular=self._popular,
            project_type=self._project_type,
            offset=self._offset,
        )
        task.succeeded.connect(
            lambda projects, result_mode=mode: self._on_results(projects, result_mode)
        )
        task.failed.connect(self._on_search_failed)
        task.finished.connect(lambda: self.search_button.setEnabled(True))
        self._search_mode = mode
        self._search_task = task
        task.start()

    def _clear_results(self) -> None:
        while self.market_grid.count():
            item = self.market_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()

    def _on_results(self, projects: object, mode: str) -> None:
        self._search_task = None
        self.more_row.hide()
        self.more_spinner.stop()
        if mode == "popular":
            self._popular_loaded = True
        pages = (
            [item for item in projects if isinstance(item, MarketProject)]
            if isinstance(projects, list)
            else []
        )
        start = len(self._projects)
        self._projects.extend(pages)
        if not self._projects:
            self.market_status.setText("Ничего не найдено. Попробуйте другой запрос.")
            return
        self._offset += len(pages)
        self._has_more = len(pages) >= 20
        self.market_status.setText(f"Найдено: {len(self._projects)}")
        for index, project in enumerate(pages, start=start):
            card = ModCard(
                project,
                self._icon_manager,
                self._instance.version if self._instance else "",
                self._instance.loader if self._instance else "",
            )
            card.clicked_project.connect(self._open_details)
            card.install_clicked.connect(
                lambda item, dependencies=False: self._install_project(
                    item, dependencies
                )
            )
            self._cards[project.id] = card
            if project.id in self._install_tasks:
                card.set_installing()
            self.market_grid.addWidget(card, index // 2, index % 2)
        self.market_grid.setColumnStretch(0, 1)
        self.market_grid.setColumnStretch(1, 1)
        self.market_grid.setRowStretch((len(self._projects) + 1) // 2, 0)
        self._update_pager()

    def _update_pager(self) -> None:
        if not hasattr(self, "prev_button"):
            return
        self.market_page_label.setText(
            f"Страница {self._page_index} · показано {len(self._projects)}"
        )
        self.prev_button.setEnabled(self._page_index > 1 and self._search_task is None)
        self.next_button.setEnabled(self._has_more and self._search_task is None)

    def _next_market_page(self) -> None:
        if not self._has_more or self._search_task is not None:
            return
        self._page_index += 1
        self._start_search(
            self._query, self._search_mode or "search", popular=self._popular, append=True
        )
        self._update_pager()

    def _previous_market_page(self) -> None:
        if self._page_index <= 1 or self._search_task is not None:
            return
        target = max(1, self._page_index - 1)
        self._start_search(self._query, self._search_mode or "search", popular=self._popular)
        self._page_index = target
        self._update_pager()

    def _on_market_scroll(self, value: int) -> None:
        if (
            self._instance is not None
            and self.pages.currentIndex() == 1
            and self._has_more
            and not self._appending
            and self._search_task is None
            and value >= self.market_scroll.verticalScrollBar().maximum() - 160
        ):
            self._start_search(
                self._query,
                self._search_mode or "search",
                popular=self._popular,
                append=True,
            )

    def _on_search_failed(self, message: str) -> None:
        self._search_task = None
        self._appending = False
        self.more_row.hide()
        self.more_spinner.stop()
        if self._search_mode == "popular":
            self._popular_loaded = False
        self.market_status.setText("")
        self.error_notified.emit(message or "Поиск не удался.")
        self._update_pager()

    def _open_details(self, project: object) -> None:
        if isinstance(project, MarketProject) and self._instance is not None:
            self.details_requested.emit(project, self._project_type)

    def _install_project(self, project: object, include_dependencies: bool) -> None:
        if not isinstance(project, MarketProject) or self._instance is None:
            return
        if self._instance.pending:
            self.queued_install_requested.emit(project, self._project_type)
            card = self._cards.get(project.id)
            if card is not None:
                card.install_status.setText("В очереди")
            self.market_status.setText(
                f"{project.name} будет установлен после загрузки версии."
            )
            return
        if project.id in self._install_tasks:
            self.market_status.setText(f"{project.name} уже загружается.")
            return
        card = self._cards.get(project.id)
        if card is not None:
            card.set_installing()
        self.market_status.setText(f"Загрузка {project.name}…")
        downloads.begin(f"mod:{project.id}", project.name)

        task = MarketInstallTask(
            self._api,
            self._instance,
            project,
            include_dependencies=include_dependencies,
            category=self._project_type,
            parent=self,
        )
        task.progress.connect(
            lambda percent, _title, detail, pid=project.id: (
                downloads.update(f"mod:{pid}", percent, detail),
                self._on_install_progress(pid, percent),
            )
        )
        task.succeeded.connect(
            lambda outcome, pid=project.id, name=project.name: self._on_install_done(
                pid, name, outcome
            )
        )
        task.failed.connect(
            lambda message, _cancelled, pid=project.id, name=project.name: self._on_install_failed(
                pid, name, message
            )
        )
        task.finished.connect(
            lambda pid=project.id: self._cleanup_install(pid)
        )
        self._install_tasks[project.id] = task
        task.start()

    def _on_install_progress(self, project_id: str, percent: int) -> None:
        card = self._cards.get(project_id)
        if card is not None:
            card.set_progress(percent)

    def _on_install_done(self, project_id: str, name: str, outcome: object) -> None:
        card = self._cards.get(project_id)
        if card is not None:
            card.set_installed()
        self.reload_installed()
        self.content_changed.emit()
        dependencies = getattr(outcome, "dependencies", [])
        suffix = f" · зависимости: {', '.join(dependencies[:4])}" if dependencies else ""
        self.market_status.setText(f"{name} установлен{suffix}")

    def _on_install_failed(self, project_id: str, name: str, message: str) -> None:
        card = self._cards.get(project_id)
        if card is not None:
            card.set_failed(message)
        self.market_status.setText(f"{name}: {message}")
        self.error_notified.emit(message)

    def _cleanup_install(self, project_id: str) -> None:
        downloads.finish(f"mod:{project_id}")
        task = self._install_tasks.pop(project_id, None)
        if task is not None:
            task.deleteLater()

    def _cancel_installs(self) -> None:
        tasks = list(self._install_tasks.values())
        for key in list(self._install_tasks):
            downloads.finish(f"mod:{key}")
        for task in tasks:
            task.cancel()
        self._install_tasks.clear()

    def has_active_installs(self) -> bool:
        return bool(self._install_tasks)

    def shutdown(self) -> None:
        self._cancel_installs()
