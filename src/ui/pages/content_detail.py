"""Full-screen Modrinth-style content page used instead of modal dialogs."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QImage, QPixmap, QTextDocument
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.core.launcher import Instance, LauncherService
from src.core.market_api import MarketAPI, MarketProject, MarketVersion
from src.ui.pages import Page
from src.ui.pages.market_page import ModIcon
from src.ui.widgets import CapsLabel


class MarkdownBrowser(QTextBrowser):
    """QTextBrowser with an in-memory cache for remote Markdown images."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.images: dict[str, QImage] = {}

    def loadResource(self, resource_type, url):  # noqa: N802 - Qt API
        key = url.toString()
        if resource_type == QTextDocument.ResourceType.ImageResource and key in self.images:
            return self.images[key]
        return super().loadResource(resource_type, url)


class GalleryImage(QLabel):
    clicked = Signal(QPixmap)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = QPixmap()
        self.setFixedSize(270, 152)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("GalleryThumb")

    def set_full_pixmap(self, pixmap: QPixmap) -> None:
        self._full = pixmap
        self.setPixmap(
            pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._full.isNull():
            self.clicked.emit(self._full)
        super().mousePressEvent(event)


class ImageLightbox(QWidget):
    def __init__(self, parent: QWidget, pixmap: QPixmap) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setStyleSheet("background-color: rgba(5, 5, 10, 245);")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 20)
        close = QPushButton("Закрыть")
        close.setObjectName("GhostButton")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.close)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(
            pixmap.scaled(
                self.screen().availableGeometry().size() * 0.9,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        layout.addWidget(label, 1)
        self.showFullScreen()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape:
            self.close()


class DetailLoadTask(QThread):
    succeeded = Signal(object, object)
    failed = Signal(str)

    def __init__(self, api: MarketAPI, project: MarketProject) -> None:
        super().__init__()
        self._api = api
        self._project = project

    def run(self) -> None:
        try:
            project = (
                self._api.modrinth_project(self._project.id)
                if self._project.source == "modrinth"
                else self._project
            )
            versions = (
                self._api.modrinth_all_versions(project.id)
                if project.source == "modrinth"
                else []
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(project, versions)


class VersionDownloadTask(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, api, instance, version, category: str) -> None:
        super().__init__()
        self._api = api
        self._instance = instance
        self._version = version
        self._category = category

    def run(self) -> None:
        folder = {
            "mod": "mods",
            "resourcepack": "resourcepacks",
            "shader": "shaderpacks",
            "map": "saves",
        }.get(self._category, "mods")
        try:
            path = self._api.download_file(
                self._version.url,
                self._instance.path / folder,
                self._version.filename,
                sha512=self._version.sha512,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(str(path))


class ContentDetailPage(Page):
    back_requested = Signal()
    install_requested = Signal(object, str)
    error_notified = Signal(str)

    def __init__(
        self,
        service: LauncherService,
        api: MarketAPI,
        project: MarketProject,
        category: str = "mod",
        instance: Instance | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, margins=(28, 16, 28, 24), spacing=12)
        self._service = service
        self._api = api
        self._project = project
        self._category = category
        self._instance = instance
        self._manager = QNetworkAccessManager(self)
        self._task: DetailLoadTask | None = None
        self._versions: list[MarketVersion] = []

        hero = QFrame()
        hero.setObjectName("DetailHero")
        top = QHBoxLayout(hero)
        top.setContentsMargins(20, 16, 20, 16)
        back = QPushButton("← Назад")
        back.setObjectName("GhostButton")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFixedHeight(36)
        back.clicked.connect(self.back_requested.emit)
        top.addWidget(back)
        self.icon = ModIcon(self._manager, 84)
        self.icon.load(project.icon_url)
        top.addWidget(self.icon)
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        self.title_label = QLabel(project.name)
        self.title_label.setObjectName("PageTitle")
        title_column.addWidget(self.title_label)
        self.meta_label = QLabel(
            f"{project.author} · {project.source} · {project.downloads:,} загрузок".replace(
                ",", " "
            )
        )
        self.meta_label.setObjectName("Caption")
        title_column.addWidget(self.meta_label)
        self.stats_label = QLabel()
        self.stats_label.setObjectName("Caption")
        title_column.addWidget(self.stats_label)
        top.addLayout(title_column, 1)
        self.install_button = QPushButton("Установить")
        self.install_button.setObjectName("PrimaryButton")
        self.install_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_button.setFixedHeight(42)
        self.install_button.setEnabled(category == "modpack" or instance is not None)
        self.install_button.clicked.connect(
            lambda: self.install_requested.emit(self._project, self._category)
        )
        top.addWidget(self.install_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addWidget(hero)
        self._update_stats(project)

        content = QHBoxLayout()
        content.setSpacing(14)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("ContentTabs")
        self.description = MarkdownBrowser()
        self.description.setObjectName("ModBody")
        self.description.setOpenExternalLinks(True)
        self.description.setStyleSheet(
            "QTextBrowser { background: transparent; color: #E9E4FF; "
            "border: none; padding: 20px; font-size: 14px; "
            "selection-background-color: #6C5CE7; }"
        )
        self.description.document().setDocumentMargin(20)
        self.description.document().setDefaultStyleSheet(
            "body { font-family: 'Segoe UI', 'Inter', sans-serif; "
            "font-size: 14px; line-height: 1.65; color: #E9E4FF; } "
            "p { margin: 0 0 12px 0; } h1 { font-size: 23px; margin: 20px 0 10px; } "
            "h2 { font-size: 19px; margin: 18px 0 8px; } "
            "h3 { font-size: 16px; margin: 15px 0 7px; } "
            "ul,ol { margin: 6px 0 12px 22px; } li { margin-bottom: 5px; } "
            "a { color: #4CC2FF; text-decoration: none; } "
            "img { max-width: 100%; margin: 8px 0; }"
        )
        self._markdown_source = project.body or project.description
        self._set_markdown(self._markdown_source)
        self.tabs.addTab(self.description, "Описание")
        self.gallery_body = QWidget()
        self.gallery_body.setObjectName("GallerySurface")
        self.gallery_body.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.gallery_layout = QGridLayout(self.gallery_body)
        self.gallery_layout.setContentsMargins(10, 10, 10, 10)
        self.gallery_layout.setSpacing(10)
        self.gallery_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._gallery_count = 0
        self.tabs.addTab(self.gallery_body, "Галерея")
        self.versions_widget = QWidget()
        self.versions_layout = QVBoxLayout(self.versions_widget)
        self.versions_layout.setContentsMargins(10, 8, 10, 8)
        self.versions_layout.setSpacing(6)
        self.versions_layout.addWidget(QLabel("Загрузка версий…"))
        self.versions_layout.addStretch(1)
        self.tabs.addTab(self.versions_widget, "Версии")
        content.addWidget(self.tabs, 1)

        sidebar = QFrame()
        sidebar.setObjectName("SettingsCard")
        sidebar.setFixedWidth(230)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 12, 14, 12)
        side.setSpacing(6)
        side.addWidget(CapsLabel("ПАРАМЕТРЫ", size=9, spacing=1.4))
        side.addWidget(QLabel("Версия Minecraft"))
        self.version_combo = QComboBox()
        self.version_combo.addItems(project.game_versions or ("Любая",))
        side.addWidget(self.version_combo)
        side.addSpacing(6)
        side.addWidget(QLabel("Ядро"))
        self.loader_combo = QComboBox()
        self.loader_combo.addItems(project.loaders or ("Любое",))
        side.addWidget(self.loader_combo)
        side.addSpacing(10)
        self.updated_label = QLabel("Дата обновления: —")
        self.updated_label.setObjectName("Caption")
        self.updated_label.setWordWrap(True)
        side.addWidget(self.updated_label)
        self.links_label = QLabel("")
        self.links_label.setObjectName("Caption")
        self.links_label.setOpenExternalLinks(True)
        self.links_label.setWordWrap(True)
        side.addWidget(self.links_label)
        side.addStretch(1)
        content.addWidget(sidebar)
        self.body.addLayout(content, 1)
        self._start_load()

    def _update_stats(self, project: MarketProject) -> None:
        followers = project.raw.get("followers") or project.raw.get("follows") or 0
        updated = project.raw.get("updated") or project.raw.get("date_modified") or ""
        self.stats_label.setText(
            f"{project.downloads:,} загрузок · {followers:,} подписчиков".replace(
                ",", " "
            )
            + (f" · обновлено {str(updated)[:10]}" if updated else "")
        )

    def _set_markdown(self, source: str) -> None:
        self._markdown_source = source or ""
        self.description.setMarkdown(self._markdown_source)
        urls = set(
            re.findall(
                r"!\[[^\]]*\]\((https?://[^)\s]+)",
                self._markdown_source,
                flags=re.IGNORECASE,
            )
        )
        urls.update(
            re.findall(
                r"<img[^>]+src=['\"](https?://[^'\"]+)",
                self._markdown_source,
                flags=re.IGNORECASE,
            )
        )
        for url in urls:
            if url in self.description.images:
                continue
            reply = self._manager.get(QNetworkRequest(QUrl(url)))
            reply.finished.connect(
                lambda r=reply, u=url: self._on_markdown_image(r, u)
            )

    def _on_markdown_image(self, reply: QNetworkReply, url: str) -> None:
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                image = QImage.fromData(bytes(reply.readAll()))
                if not image.isNull():
                    self.description.images[url] = image
                    self.description.setMarkdown(self._markdown_source)
        finally:
            reply.deleteLater()

    def _start_load(self) -> None:
        self._task = DetailLoadTask(self._api, self._project)
        self._task.succeeded.connect(self._on_loaded)
        self._task.failed.connect(self._on_failed)
        self._task.start()

    def _on_loaded(self, project: object, versions: object) -> None:
        if isinstance(project, MarketProject):
            self._project = project
            self._set_markdown(project.body or project.description)
            self.meta_label.setText(
                f"{project.author} · {project.source}".replace(",", " ")
            )
            self._update_stats(project)
            updated = project.raw.get("updated") or project.raw.get("date_modified")
            if updated:
                self.updated_label.setText(f"Дата обновления: {str(updated)[:10]}")
            links = []
            for key, label in (
                ("source_url", "GitHub"),
                ("issues_url", "Issues"),
                ("discord_url", "Discord"),
            ):
                value = project.raw.get(key)
                if value:
                    links.append(f'<a href="{value}">{label}</a>')
            self.links_label.setText("Ссылки: " + " · ".join(links) if links else "")
            gallery = project.raw.get("gallery") or []
            for item in gallery[:8]:
                if isinstance(item, dict) and item.get("url"):
                    self._load_gallery_image(str(item["url"]))
        if isinstance(versions, list):
            self._versions = versions
            self._fill_versions(versions)

    def _load_gallery_image(self, url: str) -> None:
        label = GalleryImage()
        label.setText("Загрузка…")
        label.clicked.connect(
            lambda pixmap: ImageLightbox(self.window(), pixmap)
        )
        self.gallery_layout.addWidget(
            label, self._gallery_count // 3, self._gallery_count % 3
        )
        self._gallery_count += 1
        reply = self._manager.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda: self._gallery_ready(reply, label))

    def _gallery_ready(self, reply: QNetworkReply, label: GalleryImage) -> None:
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                pixmap = QPixmap()
                if pixmap.loadFromData(bytes(reply.readAll())):
                    label.set_full_pixmap(pixmap)
                    return
            label.setText("Нет изображения")
        finally:
            reply.deleteLater()

    def _fill_versions(self, versions: list[MarketVersion]) -> None:
        while self.versions_layout.count() > 1:
            item = self.versions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not versions:
            self.versions_layout.insertWidget(0, QLabel("Версии не найдены."))
            return
        for version in versions[:30]:
            card = QFrame()
            card.setObjectName("VersionCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 10, 14, 10)
            row.setSpacing(12)
            text = QVBoxLayout()
            text.setSpacing(2)
            name = QLabel(f"v{version.version_number}")
            name.setObjectName("FieldLabel")
            text.addWidget(name)
            release_type = version.version_type or "release"
            date = version.published[:10] if version.published else "дата неизвестна"
            meta = QLabel(
                f"{release_type.upper()} · {date} · "
                f"{', '.join(version.game_versions[:3]) or 'любая версия'}"
            )
            meta.setObjectName("Caption")
            text.addWidget(meta)
            row.addLayout(text, 1)
            download = QPushButton("Скачать")
            download.setObjectName("SoftButton")
            download.setCursor(Qt.CursorShape.PointingHandCursor)
            download.clicked.connect(
                lambda _checked=False, v=version: self._download_version(v)
            )
            row.addWidget(download)
            self.versions_layout.insertWidget(self.versions_layout.count() - 1, card)

    def _download_version(self, version: MarketVersion) -> None:
        if self._instance is None:
            # Global catalogue: choose a target instance through the normal
            # picker flow instead of printing an error inside the list.
            self.install_requested.emit(self._project, self._category)
            return
        self.updated_label.setText("Скачивание версии…")
        task = VersionDownloadTask(
            self._api, self._instance, version, self._category
        )
        task.succeeded.connect(
            lambda path: self.updated_label.setText(f"Скачано: {Path(path).name}")
        )
        task.failed.connect(self._on_failed)
        task.finished.connect(task.deleteLater)
        task.start()

    def _on_failed(self, message: str) -> None:
        self.error_notified.emit(message)
        self.description.setMarkdown("Не удалось загрузить описание.")

    def shutdown(self) -> None:
        if self._task is not None and self._task.isRunning():
            self._task.wait(250)
