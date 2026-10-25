"""Modpack store: Modrinth and CurseForge catalogs with one-click installs."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.launcher import Instance, LauncherService
from src.core.market_api import MarketAPI, MarketProject
from src.core.modpacks import ModpackInfo
from src.ui.downloads import downloads
from src.ui.instance_dialogs import OperationProgressDialog
from src.ui.launch_dialogs import OverlayDialog
from src.ui.pages import Page, build_header
from src.ui.pages.market_page import ModIcon
from src.ui.tasks import ModpackDetailsTask, ModpackInstallTask, ModpackSearchTask
from src.ui.widgets import CapsLabel, GlassComboBox, IconButton


class ModpackCard(QPushButton):
    clicked_project = Signal(object)
    install_clicked = Signal(object)

    def __init__(self, project: MarketProject, manager: QNetworkAccessManager) -> None:
        super().__init__()
        self.project = project
        self.setObjectName("ModCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(154)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(project.description)
        self.clicked.connect(lambda: self.clicked_project.emit(project))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 12, 13, 10)
        layout.setSpacing(7)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        icon = ModIcon(manager, 48)
        icon.load(project.icon_url)
        top.addWidget(icon)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        title = QLabel(project.name)
        title.setObjectName("ModTitle")
        title.setWordWrap(True)
        title.setMaximumHeight(42)
        text.addWidget(title)
        author = QLabel(f"{project.author} · {project.source}")
        author.setObjectName("Caption")
        text.addWidget(author)
        top.addLayout(text, 1)
        layout.addLayout(top)
        description = QLabel(project.description)
        description.setObjectName("Caption")
        description.setWordWrap(True)
        description.setMaximumHeight(38)
        layout.addWidget(description)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        downloads = QLabel(f"{project.downloads:,}".replace(",", " ") + " загрузок")
        downloads.setObjectName("Caption")
        bottom.addWidget(downloads)
        bottom.addStretch(1)
        install = QPushButton("Установить")
        install.setObjectName("SoftButton")
        install.setCursor(Qt.CursorShape.PointingHandCursor)
        install.setFixedHeight(26)
        install.clicked.connect(lambda: self.install_clicked.emit(project))
        bottom.addWidget(install)
        arrow = QPushButton("Подробнее")
        arrow.setObjectName("LinkButton")
        arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        arrow.clicked.connect(lambda: self.clicked_project.emit(project))
        bottom.addWidget(arrow)
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        install.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        install.raise_()
        arrow.raise_()
        layout.addLayout(bottom)


class ModpackDetailsDialog(OverlayDialog):
    installed = Signal(object)

    def __init__(
        self,
        parent: QWidget,
        service: LauncherService,
        api: MarketAPI,
        project: MarketProject,
    ) -> None:
        super().__init__(parent, card_width=560)
        self._service = service
        self._api = api
        self._project = project
        self._info: ModpackInfo | None = None
        self._task: ModpackDetailsTask | None = None
        self._closing = False
        self.setWindowTitle("Сборка")
        layout = self.card_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        close = IconButton("close", size=(30, 30), icon_size=13, radius=9, tooltip="Закрыть")
        close.clicked.connect(self.reject)
        header.addWidget(CapsLabel("MODPACK", size=9, spacing=1.8, accent=True))
        header.addStretch(1)
        header.addWidget(close)
        layout.addLayout(header)
        layout.addSpacing(8)
        self.title_label = QLabel(project.name)
        self.title_label.setObjectName("DialogTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        self.meta_label = QLabel(
            f"{project.author} · {project.source} · "
            f"{project.downloads:,}".replace(",", " ") + " загрузок"
        )
        self.meta_label.setObjectName("Caption")
        layout.addWidget(self.meta_label)
        self.summary = QLabel(project.description)
        self.summary.setObjectName("PageSubtitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addSpacing(8)
        self.status = QLabel("Загрузка данных сборки…")
        self.status.setObjectName("ProgressPhase")
        layout.addWidget(self.status)
        self.mods_scroll = QScrollArea()
        self.mods_scroll.setWidgetResizable(True)
        self.mods_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.mods_scroll.setMinimumHeight(170)
        self.mods_scroll.setMaximumHeight(260)
        self.mods_host = QWidget()
        self.mods_host.setObjectName("ContentList")
        self.mods_layout = QVBoxLayout(self.mods_host)
        self.mods_layout.setContentsMargins(0, 0, 4, 0)
        self.mods_layout.setSpacing(4)
        self.mods_layout.addStretch(1)
        self.mods_scroll.setWidget(self.mods_host)
        self.mods_scroll.hide()
        layout.addWidget(self.mods_scroll)
        self.mods_title = QLabel()
        self.mods_title.setObjectName("SectionTitle")
        self.mods_title.hide()
        layout.addWidget(self.mods_title)
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.install_button = QPushButton("Установить")
        self.install_button.setObjectName("PrimaryButton")
        self.install_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_button.setFixedHeight(40)
        self.install_button.setEnabled(False)
        self.install_button.clicked.connect(self._install)
        footer.addWidget(self.install_button)
        cancel = QPushButton("Закрыть")
        cancel.setObjectName("GhostButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setFixedHeight(40)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        layout.addLayout(footer)
        self._start()

    def _start(self) -> None:
        self._task = ModpackDetailsTask(self._api, self._project, self)
        self._task.succeeded.connect(self._on_ready)
        self._task.failed.connect(self._on_failed)
        self._task.finished.connect(self._on_finished)
        self._task.start()

    def _on_finished(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.deleteLater()
        if self._closing:
            self.reject()

    def _on_ready(self, info: object) -> None:
        if not isinstance(info, ModpackInfo):
            self._on_failed("Некорректные данные сборки.")
            return
        self._info = info
        self.status.setText(
            f"Minecraft {info.mc_version} · {info.loader.title()}"
            + (f" {info.loader_version}" if info.loader_version else "")
        )
        self.install_button.setEnabled(True)
        files = [path for path in info.mod_files if path.lower().endswith(".jar")]
        self.mods_title.setText(f"Моды · {len(files)}")
        self.mods_title.show()
        for path in files[:80]:
            label = QLabel(path)
            label.setObjectName("Caption")
            label.setWordWrap(True)
            self.mods_layout.insertWidget(self.mods_layout.count() - 1, label)
        if len(files) > 80:
            more = QLabel(f"…и ещё {len(files) - 80}")
            more.setObjectName("Caption")
            self.mods_layout.insertWidget(self.mods_layout.count() - 1, more)
        self.mods_scroll.show()

    def _on_failed(self, message: str) -> None:
        self.status.setText(message)
        self.install_button.setEnabled(False)

    def _install(self) -> None:
        if self._info is None:
            return
        key = f"pack:{self._info.project.id}"

        def make_task(parent):
            downloads.begin(key, self._info.name)
            task = ModpackInstallTask(self._service, self._api, self._info, parent)
            task.progress.connect(
                lambda percent, _title, detail: downloads.update(key, percent, detail)
            )
            task.finished.connect(lambda: downloads.finish(key))
            return task

        dialog = OperationProgressDialog(
            self,
            title="Установка сборки",
            subtitle=f"{self._info.name} · Minecraft {self._info.mc_version}",
            icon_name="download",
            eyebrow="MODPACK",
            worker_factory=make_task,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted and isinstance(
            dialog.result, Instance
        ):
            self.installed.emit(dialog.result)
            self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._task is not None and self._task.isRunning():
            self._closing = True
            self._task.cancel()
            event.ignore()
            return
        super().closeEvent(event)


class StoreBanner(QFrame):
    """Auto-rotating recommendation banner."""

    project_clicked = Signal(object)

    def __init__(self, manager: QNetworkAccessManager) -> None:
        super().__init__()
        self.setObjectName("StoreBanner")
        self.setFixedHeight(190)
        self._manager = manager
        self._projects: list[MarketProject] = []
        self._index = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        text = QVBoxLayout()
        text.setSpacing(6)
        self.eyebrow = QLabel("РЕКОМЕНДАЦИЯ")
        self.eyebrow.setObjectName("Caption")
        text.addWidget(self.eyebrow)
        self.title = QLabel("Загрузка рекомендаций…")
        self.title.setObjectName("BannerTitle")
        self.title.setWordWrap(True)
        text.addWidget(self.title)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("PageSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setMaximumHeight(54)
        text.addWidget(self.subtitle)
        text.addStretch(1)
        self.open_button = QPushButton("Смотреть сборку")
        self.open_button.setObjectName("PrimaryButton")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.setFixedHeight(38)
        self.open_button.clicked.connect(self._open_current)
        text.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(text, 1)
        self.icon = ModIcon(manager, 120)
        layout.addWidget(self.icon)
        self._timer = QTimer(self)
        self._timer.setInterval(5500)
        self._timer.timeout.connect(self._next)
        self._timer.start()

    def set_project_type(self, project_type: str) -> None:
        self.open_button.setText(
            "Смотреть сборку" if project_type == "modpack" else "Подробнее"
        )

    def set_projects(self, projects: list[MarketProject]) -> None:
        self._projects = projects[:6]
        self._index = 0
        self._show()

    def _show(self) -> None:
        if not self._projects:
            return
        project = self._projects[self._index % len(self._projects)]
        self.title.setText(project.name)
        self.subtitle.setText(project.description)
        self.icon.load(project.icon_url)
        self.open_button.setEnabled(True)

    def _next(self) -> None:
        if len(self._projects) <= 1:
            return
        self._index = (self._index + 1) % len(self._projects)
        self._show()

    def _open_current(self) -> None:
        if self._projects:
            self.project_clicked.emit(self._projects[self._index % len(self._projects)])


class StorePage(Page):
    instance_ready = Signal(object)
    details_requested = Signal(object, str)
    install_requested = Signal(object, str)
    error_notified = Signal(str)

    def __init__(
        self, service: LauncherService, api: MarketAPI, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.api = api
        self._manager = QNetworkAccessManager(self)
        self._projects: list[MarketProject] = []
        self._cards: list[ModpackCard] = []
        self._search_task: ModpackSearchTask | None = None
        self._loaded = False
        self._source = "modrinth"
        self._offset = 0
        self._has_more = False
        self._appending = False
        self._query = ""
        self._popular = False
        self._project_type = "modpack"

        self.body.addWidget(
            build_header(
                "Магазин",
                "Готовые сборки Modrinth и CurseForge. Установка создаёт новый экземпляр.",
            )
        )
        self.banner = StoreBanner(self._manager)
        self.banner.project_clicked.connect(self._open_details)
        self.body.addWidget(self.banner)
        # Global store is intentionally modpack-only.
        self._project_type = "modpack"
        self.banner.set_project_type("modpack")
        search_card = QFrame()
        search_card.setObjectName("SettingsCard")
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(18, 15, 18, 15)
        search_layout.setSpacing(10)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск сборок: Better MC, Create, RPG…")
        self.search_edit.returnPressed.connect(self._search)
        search_row.addWidget(self.search_edit, 1)
        self.source_combo = GlassComboBox()
        self.source_combo.addItem("Modrinth", "modrinth")
        if self.api.curseforge_key:
            self.source_combo.addItem("CurseForge", "curseforge")
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        search_row.addWidget(self.source_combo)
        find = QPushButton("Найти")
        find.setObjectName("PrimaryButton")
        find.setCursor(Qt.CursorShape.PointingHandCursor)
        find.setFixedHeight(40)
        find.clicked.connect(self._search)
        search_row.addWidget(find)
        search_layout.addLayout(search_row)
        self.status_label = QLabel("Каталог сборок загружается…")
        self.status_label.setObjectName("Caption")
        search_layout.addWidget(self.status_label)
        if not self.api.curseforge_key:
            cf_note = QLabel("CurseForge временно недоступен")
            cf_note.setObjectName("Caption")
            search_layout.addWidget(cf_note)
        self.body.addWidget(search_card)

        self.grid_host = QWidget()
        self.grid_host.setObjectName("ContentList")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 4, 0)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body.addWidget(self.grid_host, 1)
        pager = QHBoxLayout()
        pager.setContentsMargins(0, 6, 0, 0)
        self.page_label = QLabel("Страница 1")
        self.page_label.setObjectName("Caption")
        pager.addWidget(self.page_label)
        pager.addStretch(1)
        self.prev_button = QPushButton("← Назад")
        self.prev_button.setObjectName("GhostButton")
        self.prev_button.clicked.connect(self._previous_page)
        self.next_button = QPushButton("Вперёд →")
        self.next_button.setObjectName("GhostButton")
        self.next_button.clicked.connect(self._next_page)
        for button in (self.prev_button, self.next_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(34)
            pager.addWidget(button)
        self.body.addLayout(pager)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._page_index = 1
        self._update_pager()

    def ensure_loaded(self) -> None:
        if self._loaded or self._search_task is not None:
            return
        self._loaded = True
        QTimer.singleShot(0, lambda: self._start_search(popular=True))

    def _on_source_changed(self, _index: int = -1) -> None:
        self._source = str(self.source_combo.currentData() or "modrinth")
        if self._source == "curseforge" and not self.api.curseforge_key:
            self._clear_cards()
            self.status_label.setText("CurseForge временно недоступен.")
            return
        if self._loaded:
            self._start_search()

    def _search(self) -> None:
        if self._source == "curseforge" and not self.api.curseforge_key:
            self.status_label.setText("CurseForge временно недоступен.")
            return
        self._start_search()

    def _start_search(self, popular: bool = False, append: bool = False) -> None:
        if self._search_task is not None:
            return
        if not append:
            self._query = self.search_edit.text().strip()
            self._popular = popular
            self._offset = 0
            self._has_more = False
            self._page_index = 1
        self._appending = append
        if not append:
            self.status_label.setText("Загрузка сборок…")
        task = ModpackSearchTask(
            self.api,
            self._query,
            self._source,
            popular=self._popular,
            offset=self._offset,
            project_type=self._project_type,
            parent=self,
        )
        task.succeeded.connect(self._on_results)
        task.failed.connect(self._on_failed)
        task.finished.connect(self._on_finished)
        self._search_task = task
        task.start()

    def _on_scroll(self, value: int) -> None:
        if (
            self._loaded
            and self._has_more
            and self._search_task is None
            and value >= self.verticalScrollBar().maximum() - 160
        ):
            self._start_search(append=True)

    def _on_results(self, projects: object) -> None:
        pages = list(projects) if isinstance(projects, list) else []
        if not self._appending:
            self._clear_cards()
            self.banner.set_projects(pages)
        start = len(self._projects)
        self._projects.extend(pages)
        for offset, project in enumerate(pages):
            index = start + offset
            card = ModpackCard(project, self._manager)
            card.clicked_project.connect(self._open_details)
            card.install_clicked.connect(
                lambda project, kind=self._project_type: self.install_requested.emit(
                    project, kind
                )
            )
            self.grid.addWidget(card, index // 2, index % 2)
            self._cards.append(card)
        self._offset += len(pages)
        self._has_more = len(pages) >= 20
        if self._projects:
            self.status_label.setText(f"Найдено сборок: {len(self._projects)}")
        else:
            self.status_label.setText("Сборки не найдены.")
        self._update_pager()

    def _update_pager(self) -> None:
        if not hasattr(self, "prev_button"):
            return
        self.page_label.setText(
            f"Страница {self._page_index} · показано {len(self._projects)}"
        )
        self.prev_button.setEnabled(self._page_index > 1 and self._search_task is None)
        self.next_button.setEnabled(self._has_more and self._search_task is None)

    def _next_page(self) -> None:
        if not self._has_more or self._search_task is not None:
            return
        self._page_index += 1
        self._start_search(append=True)
        self._update_pager()

    def _previous_page(self) -> None:
        if self._page_index <= 1 or self._search_task is not None:
            return
        target = max(1, self._page_index - 1)
        self._start_search(popular=self._popular)
        self._page_index = target
        self._update_pager()

    def _on_failed(self, message: str) -> None:
        self.status_label.setText("")
        self.error_notified.emit(message)
        self._has_more = False
        self._appending = False
        self._update_pager()

    def _on_finished(self) -> None:
        task = self._search_task
        self._search_task = None
        self._appending = False
        if task is not None:
            task.deleteLater()
        self._update_pager()

    def _clear_cards(self) -> None:
        for card in self._cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._projects.clear()

    def _open_details(self, project: object) -> None:
        if isinstance(project, MarketProject):
            self.details_requested.emit(project, self._project_type)

    def shutdown(self) -> None:
        task = self._search_task
        if task is not None:
            task.wait(250)
            self._search_task = None
