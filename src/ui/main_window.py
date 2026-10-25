"""Frameless main window, navigation, game launch and system tray."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QProcess,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    QTimer,
    QUrl,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src import __version__
from src.app_paths import asset_path
from src.core.accounts import AccountManager, create_guest
from src.core.config_manager import ConfigManager
from src.core.exporter import export_pack
from src.core.launcher import GameSession, Instance, LauncherError, LauncherService
from src.core.theme import (
    build_stylesheet,
    current_theme,
    set_accent_color,
    set_custom_colors,
    set_theme,
)
from src.core.updater import (
    NOT_CONFIGURED_MESSAGE,
    UpdateInfo,
    repo_configured,
)
from src.ui.accounts_ui import (
    AccountWelcomeDialog,
    CredentialsDialog,
    MicrosoftLoginDialog,
)
from src.ui.crash_dialog import CrashDialog
from src.ui.downloads import DownloadsPanel
from src.ui.instance_dialogs import (
    ContentManagerDialog,
    InstanceSettingsDialog,
    OperationProgressDialog,
)
from src.ui.launch_dialogs import (
    CreateInstanceDialog,
    InstallProgressDialog,
    JavaProgressDialog,
    LaunchLoadingDialog,
    NoticeDialog,
)
from src.ui.profile_dialog import ProfileDialog
from src.ui.pages.home_page import HomePage
from src.ui.pages.instance_page import InstancePage, format_session_time
from src.ui.pages.content_detail import ContentDetailPage
from src.ui.pages.market_page import MarketPage
from src.ui.pages.premium_page import PremiumPage
from src.ui.pages.settings_page import SettingsPage
from src.ui.pages.store_page import StorePage
from src.ui.player import MusicPopover
from src.ui.sidebar import Sidebar
from src.ui.tasks import (
    BackupTask,
    HomeCarouselTask,
    ImportPackTask,
    MarketInstallTask,
    ModpackProjectInstallTask,
    UpdateCheckTask,
    UpdateDownloadTask,
)
from src.ui.title_bar import TitleBar
from src.ui.widgets import with_alpha

logger = logging.getLogger(__name__)

PAGE_ORDER = ("home", "store", "premium", "settings")


class VideoBackground(QGraphicsView):
    """Hardware-accelerated MP4 background rendered by QGraphicsVideoItem."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("VideoBackground")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsVideoItem()
        self._item.setOpacity(0.72)
        self._scene.addItem(self._item)
        self._tint = QGraphicsRectItem()
        self._tint.setBrush(QColor(5, 5, 10, 205))
        self._tint.setPen(Qt.PenStyle.NoPen)
        self._tint.setZValue(1)
        self._scene.addItem(self._tint)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.0)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._item)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(self._on_error)
        self._path = ""
        self.hide()

    def play(self, path: Path) -> None:
        self.stop()
        self._path = str(path)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self.show()
        self.lower()
        self._player.play()
        QTimer.singleShot(0, self._layout_item)

    def stop(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        self._path = ""
        self.hide()

    def pause(self) -> None:
        self._player.pause()

    def resume(self) -> None:
        if self._path:
            self._player.play()

    def _on_status(self, status) -> None:
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ) and self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._player.play()

    def _on_error(self, _error, message: str) -> None:
        logger.warning("Video background error: %s", message)
        self.hide()

    def _layout_item(self) -> None:
        size = self.viewport().size()
        self._scene.setSceneRect(0, 0, size.width(), size.height())
        self._item.setSize(size)
        self._tint.setRect(0, 0, size.width(), size.height())
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatioByExpanding)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._layout_item()


class LauncherShell(QFrame):
    """Rounded shell that paints the gradient backdrop."""

    def __init__(self, background_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Shell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._default_source = QPixmap(str(background_path))
        self._source = self._default_source
        self._video_frame: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._scaled_for = QSize(0, 0)
        self._radius = 20.0
        self.video_background = VideoBackground(self)
        self.video_background.setGeometry(self.rect())

    def play_video(self, path: Path) -> None:
        self.video_background.setGeometry(self.rect())
        self.video_background.play(path)
        self.update()

    def stop_video(self) -> None:
        self.video_background.stop()

    def pause_video(self) -> None:
        self.video_background.pause()

    def resume_video(self) -> None:
        self.video_background.resume()

    def set_corner_radius(self, radius: float) -> None:
        self._radius = radius
        self._apply_video_mask()
        self.update()

    def _apply_video_mask(self) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        self.video_background.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def set_background_pixmap(self, pixmap: QPixmap | None) -> None:
        self.stop_video()
        self._video_frame = None
        self._source = pixmap if pixmap is not None and not pixmap.isNull() else self._default_source
        self._scaled = None
        self.update()

    def set_video_frame(self, image: QImage) -> None:
        if image.isNull():
            return
        self._video_frame = QPixmap.fromImage(image)
        self._scaled = None
        self.update()

    def reset_video(self) -> None:
        self._video_frame = None
        self._scaled = None
        self.update()

    def refresh_theme(self) -> None:
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._scaled = None
        self.video_background.setGeometry(self.rect())
        self._apply_video_mask()
        super().resizeEvent(event)

    def _background(self) -> QPixmap | None:
        source = self._video_frame if self._video_frame is not None else self._source
        if source is None or source.isNull():
            return None
        if self._scaled is None or self._scaled_for != self.size():
            self._scaled = source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._scaled_for = self.size()
        return self._scaled

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        painter.fillPath(path, QColor(7, 7, 13))
        painter.save()
        painter.setClipPath(path)
        background = self._background()
        if background is not None:
            point = QPoint(
                int((self.width() - background.width()) / 2),
                int((self.height() - background.height()) / 2),
            )
            painter.drawPixmap(point, background)
        else:
            fallback = QRectF(rect)
            painter.fillRect(fallback, QColor(10, 9, 18))
            painter.fillRect(fallback, with_alpha(theme.accent, 24))

        painter.fillRect(rect, theme.backdrop_tint)

        # Gentle darkening at the top helps the title bar and sidebar blend in.
        painter.fillRect(
            QRectF(0, 0, self.width(), 120),
            QColor(5, 5, 10, 26),
        )
        painter.restore()

        painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class MainWindow(QMainWindow):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.launcher = LauncherService(config)
        self.accounts = AccountManager(config.data_dir)
        self._instances: list[Instance] = []
        self._current_instance: Instance | None = None
        self._game_session: GameSession | None = None
        self._tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._tray_stop_action = None
        self._pre_game_maximized = False
        self._hidden_for_game = False
        self._allow_close = False
        self._quitting = False
        self._fullscreen = False
        self._pre_fullscreen_maximized = False
        self._welcome_shown = False
        self._update_info: UpdateInfo | None = None

        self._music_popover: MusicPopover | None = None
        self._downloads_panel: DownloadsPanel | None = None
        self._detail_page: ContentDetailPage | None = None
        self._detail_parent_key = "store"
        self._detail_parent_category = "mod"
        self._page_animation: QPropertyAnimation | None = None
        self._page_effect: QGraphicsOpacityEffect | None = None
        self._fading_page: QWidget | None = None
        self._current_page_key = ""

        self.setWindowTitle("Fionix")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(1080, 700)
        self._restore_window_geometry()

        self._build_ui()
        self._wire_signals()
        self._fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self._fullscreen_shortcut.activated.connect(self._toggle_fullscreen)
        self._restore_page()
        self.refresh_instances()
        self._refresh_accounts_ui()
        self._apply_background()
        QTimer.singleShot(0, self._maybe_show_welcome)
        QTimer.singleShot(700, self._load_home_carousel)
        if os.environ.get("FIONIX_SKIP_UPDATE") != "1":
            QTimer.singleShot(1200, lambda: self._check_updates(manual=False))

        if config.get("window", {}).get("maximized", False):
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    # ------------------------------------------------------------------ ui
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("ContentRoot")
        central.setMouseTracking(True)
        self.setCentralWidget(central)
        self._central = central
        central.installEventFilter(self)

        self._root_layout = QVBoxLayout(central)
        self._root_layout.setContentsMargins(20, 20, 20, 20)
        self._root_layout.setSpacing(0)

        self.shell = LauncherShell(asset_path("background.png"))
        self.shell.setObjectName("Shell")
        self._shell_shadow = QGraphicsDropShadowEffect(self.shell)
        self._shell_shadow.setBlurRadius(44)
        self._shell_shadow.setOffset(0, 14)
        self._shell_shadow.setColor(QColor(0, 0, 0, 170))
        self.shell.setGraphicsEffect(self._shell_shadow)
        self._root_layout.addWidget(self.shell)

        shell_layout = QHBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.sidebar = Sidebar(version=__version__)
        shell_layout.addWidget(self.sidebar)

        main_area = QWidget()
        main_area.setObjectName("MainArea")
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.title_bar = TitleBar()
        main_layout.addWidget(self.title_bar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")
        self.home_page = HomePage()
        self.settings_page = SettingsPage(self.config, self.accounts)
        self.instance_page = InstancePage()
        self.market_page = MarketPage(self.launcher)
        self.store_page = StorePage(self.launcher, self.market_page._api)
        self.premium_page = PremiumPage(self.config)
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.store_page)
        self.stack.addWidget(self.premium_page)
        self.stack.addWidget(self.instance_page)
        self.stack.addWidget(self.market_page)
        main_layout.addWidget(self.stack, 1)

        shell_layout.addWidget(main_area, 1)

    def _wire_signals(self) -> None:
        self.sidebar.page_changed.connect(self.navigate)
        self.sidebar.create_instance_requested.connect(self._show_version_dialog)
        self.sidebar.instance_selected.connect(self._open_instance)
        self.sidebar.account_selected.connect(self._switch_account)
        self.sidebar.profile_requested.connect(self._open_profile)
        self.sidebar.account_add_requested.connect(self._add_account)

        self.home_page.create_requested.connect(self._show_version_dialog)
        self.home_page.import_requested.connect(self._import_pack)
        self.home_page.open_game_folder_requested.connect(self._open_game_folder)
        self.home_page.instance_selected.connect(self._open_instance)
        self.settings_page.theme_changed.connect(self.apply_theme)
        self.settings_page.accent_changed.connect(self._on_accent_changed)
        self.settings_page.background_changed.connect(self._apply_background)
        self.settings_page.accounts_add_requested.connect(self._add_account)
        self.settings_page.account_switch_requested.connect(self._switch_account)
        self.settings_page.account_logout_requested.connect(self._logout_account)
        self.settings_page.instances_path_changed.connect(self._on_instances_path_changed)
        self.settings_page.update_check_requested.connect(
            lambda: self._check_updates(manual=True)
        )

        self.instance_page.back_requested.connect(lambda: self.navigate("home"))
        self.instance_page.play_requested.connect(self._play_current)
        self.instance_page.settings_requested.connect(self._open_instance_settings)
        self.instance_page.backup_requested.connect(self._backup_current)
        self.instance_page.share_requested.connect(self._share_instance)
        self.instance_page.delete_requested.connect(self._delete_current_instance)
        self.instance_page.content_requested.connect(self._open_content_manager)
        self.instance_page.open_folder_requested.connect(self._open_instance_folder)
        self.market_page.back_requested.connect(self._back_from_market)
        self.market_page.content_changed.connect(self._refresh_content_counts)
        self.store_page.instance_ready.connect(self._on_modpack_installed)
        self.store_page.details_requested.connect(self._open_content_detail)
        self.store_page.install_requested.connect(self._install_store_project)
        self.market_page.details_requested.connect(
            lambda project, category: self._open_content_detail(
                project, category, parent_key="market"
            )
        )
        self.home_page.premium_requested.connect(lambda: self.navigate("premium"))
        self.home_page.pack_selected.connect(
            lambda project: self._open_content_detail(project, "modpack", "home")
        )
        self.premium_page.activated.connect(self._on_premium_activated)

        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self._toggle_maximized)
        self.title_bar.close_requested.connect(self.close)
        self.title_bar.music_requested.connect(self._toggle_music_popover)
        self.title_bar.downloads_requested.connect(self._toggle_downloads_panel)
        self.title_bar.update_requested.connect(self._open_update_page)

    # ---------------------------------------------------------- instances
    def refresh_instances(self) -> None:
        try:
            instances = self.launcher.list_instances()
        except Exception:
            logger.exception("Could not list instances")
            instances = []
        self._instances = instances
        self.home_page.set_instances(instances)
        self.sidebar.set_instances(instances)

        if self._current_instance is not None:
            for candidate in instances:
                if candidate.folder_name == self._current_instance.folder_name:
                    self._current_instance = candidate
                    break

    def _open_instance(self, instance: object, *, animate: bool = True) -> None:
        if not isinstance(instance, Instance):
            return
        fresh = self.launcher.get_instance(instance.folder_name) or instance
        self._current_instance = fresh
        self.instance_page.load_instance(
            fresh,
            java_hint=self._java_hint(fresh),
            memory_mb=(
                fresh.memory_mb if fresh.memory_mb is not None else self.config.memory_mb
            ),
            content_counts=self.launcher.content_counts(fresh),
        )
        if (
            self._game_session is not None
            and self._game_session.instance.folder_name == fresh.folder_name
            and self._game_session.is_running()
        ):
            self.instance_page.set_game_running()
            self.instance_page.update_running(
                self._game_session.session_seconds, self._game_session.total_playtime
            )

        self.sidebar.set_active("home")
        self._current_page_key = "instance"
        self.stack.setCurrentWidget(self.instance_page)
        if animate:
            self._fade_in_page(self.instance_page)
        self.setWindowTitle(f"Fionix — {fresh.name}")

    def _on_modpack_installed(self, instance: object) -> None:
        if not isinstance(instance, Instance):
            return
        self.refresh_instances()
        self._open_instance(instance)
        self._notice("Сборка установлена", f"Создан экземпляр «{instance.name}».")

    def _java_hint(self, instance: Instance) -> str:
        if instance.java_path:
            try:
                runtime = self.launcher.java_for_instance(instance)
            except LauncherError:
                return "Своя Java · ошибка пути"
            if runtime is not None:
                return f"Java {runtime.major} · своя"
            return "Своя Java · не задана"
        runtime = self.launcher.preferred_java(instance.java_major)
        if runtime is not None:
            return f"Java {instance.java_major} · {runtime.source}"
        return f"Java {instance.java_major} · скачается при запуске"

    def _open_instance_folder(self) -> None:
        if self._current_instance is None:
            return
        try:
            self.launcher.open_instance_folder(self._current_instance)
        except LauncherError as exc:
            self._notice("Не удалось открыть папку", str(exc))

    def _open_instance_settings(self) -> None:
        instance = self._current_instance
        if instance is None:
            return
        if self._game_session is not None and self._game_session.is_running():
            self._notice(
                "Игра запущена",
                "Настройки экземпляра можно менять после закрытия Minecraft.",
            )
            return
        dialog = InstanceSettingsDialog(
            self.launcher, instance, self.config.memory_mb, self
        )
        result = dialog.exec()
        dialog.deleteLater()
        if result != QDialog.DialogCode.Accepted:
            return
        fresh = self.launcher.get_instance(instance.folder_name) or instance
        self.refresh_instances()
        self._open_instance(fresh, animate=False)

    def _open_content_manager(self, category_key: str) -> None:
        instance = self._current_instance
        if instance is None:
            return
        if self._game_session is not None and self._game_session.is_running():
            self._notice(
                "Игра запущена",
                "Содержимое экземпляра можно менять после закрытия Minecraft.",
            )
            return
        category = {
            "mods": "mod",
            "texturepacks": "resourcepack",
            "shaders": "shader",
            "maps": "map",
        }.get(category_key)
        if category is not None:
            self._open_market(category)
            return
        dialog = ContentManagerDialog(
            self.launcher, instance, category_key, self
        )
        dialog.content_changed.connect(self._refresh_content_counts)
        dialog.exec()
        dialog.deleteLater()
        self._refresh_content_counts()

    def _open_content_detail(
        self, project: object, category: str, parent_key: str | None = None
    ) -> None:
        if not hasattr(project, "id"):
            return
        if self._detail_page is not None:
            self._close_content_detail()
        self._detail_parent_key = parent_key or (
            "market" if self._current_page_key == "market" else "store"
        )
        self._detail_parent_category = category
        page = ContentDetailPage(
            self.launcher,
            self.market_page._api,
            project,
            category,
            self._current_instance if self._detail_parent_key == "market" else None,
        )
        page.back_requested.connect(self._close_content_detail)
        page.install_requested.connect(self._install_content_detail)
        self._detail_page = page
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        self.sidebar.set_active("home")
        self.setWindowTitle(f"Fionix — {getattr(project, 'name', 'Контент')}")
        self._fade_in_page(page)

    def _close_content_detail(self) -> None:
        page = self._detail_page
        if page is None:
            return
        self._detail_page = None
        self.stack.removeWidget(page)
        page.shutdown()
        page.deleteLater()
        if self._detail_parent_key == "market":
            self._open_market(self._detail_parent_category)
        elif self._detail_parent_key == "home":
            self.navigate("home", persist=False)
        else:
            self.navigate("store", persist=False)

    def _install_store_project(self, project: object) -> None:
        dialog = OperationProgressDialog(
            self,
            title="Установка сборки",
            subtitle=getattr(project, "name", "Modpack"),
            icon_name="download",
            eyebrow="MODPACK",
            worker_factory=lambda parent: ModpackProjectInstallTask(
                self.launcher, self.market_page._api, project, parent
            ),
        )
        dialog.exec()
        result = dialog.result
        error = dialog.error_message
        dialog.deleteLater()
        if isinstance(result, Instance):
            self._on_modpack_installed(result)
        elif error:
            self._notice("Не удалось установить сборку", error)

    def _install_content_detail(self, project: object, category: str) -> None:
        if category == "modpack":
            dialog = OperationProgressDialog(
                self,
                title="Установка сборки",
                subtitle=getattr(project, "name", "Modpack"),
                icon_name="download",
                eyebrow="MODPACK",
                worker_factory=lambda parent: ModpackProjectInstallTask(
                    self.launcher, self.market_page._api, project, parent
                ),
            )
            dialog.exec()
            result = dialog.result
            error = dialog.error_message
            dialog.deleteLater()
            if isinstance(result, Instance):
                self._close_content_detail()
                self._on_modpack_installed(result)
            elif error:
                self._notice("Не удалось установить сборку", error)
            return
        instance = self._current_instance
        if instance is None:
            self._notice("Сначала откройте экземпляр", "Выберите сборку в библиотеке.")
            return
        dialog = OperationProgressDialog(
            self,
            title="Установка контента",
            subtitle=getattr(project, "name", "Контент"),
            icon_name="download",
            eyebrow="MARKET",
            worker_factory=lambda parent: MarketInstallTask(
                self.market_page._api,
                instance,
                project,
                include_dependencies=False,
                category=category,
                parent=parent,
            ),
        )
        dialog.exec()
        error = dialog.error_message
        dialog.deleteLater()
        if error:
            self._notice("Не удалось установить контент", error)
        else:
            self._refresh_content_counts()
            self._close_content_detail()

    def _open_market(self, category: str = "mod") -> None:
        instance = self._current_instance
        if instance is None:
            return
        self.market_page.set_instance(instance, category)
        self.market_page._show_market_tab()
        self._current_page_key = "market"
        self.stack.setCurrentWidget(self.market_page)
        self.sidebar.set_active("home")
        self._fade_in_page(self.market_page)
        labels = {
            "mod": "Моды",
            "resourcepack": "Текстурпаки",
            "shader": "Шейдеры",
            "map": "Карты",
        }
        self.setWindowTitle(
            f"Fionix — {instance.name} · {labels.get(category, 'Контент')}"
        )

    def _back_from_market(self) -> None:
        if self._current_instance is not None:
            self._open_instance(self._current_instance)
        else:
            self.navigate("home")

    def _open_game_folder(self) -> None:
        from PySide6.QtGui import QDesktopServices

        path = self.launcher.instances_dir
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _share_instance(self) -> None:
        instance = self._current_instance
        if instance is None:
            return
        default = str(Path.home() / f"{instance.name}.fionixpack")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Поделиться сборкой",
            default,
            "Fionix pack (*.fionixpack);;JSON (*.json)",
        )
        if not filename:
            return
        try:
            target = export_pack(instance, Path(filename))
        except (OSError, LauncherError) as exc:
            self._notice("Не удалось экспортировать сборку", str(exc))
            return
        self._notice(
            "Сборка экспортирована",
            f"Файл сохранён:\n{target}\n\n"
            "В пак попадают включённые моды, версия Minecraft и ядро.",
        )

    def _import_pack(self) -> None:
        if self._game_session is not None and self._game_session.is_running():
            self._notice("Игра запущена", "Дождитесь завершения Minecraft перед импортом.")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Импортировать сборку",
            str(Path.home()),
            "Fionix pack (*.fionixpack);;JSON (*.json);;Все файлы (*)",
        )
        if not filename:
            return
        from src.core.market_api import MarketAPI

        dialog = OperationProgressDialog(
            self,
            title="Импорт .fionixpack",
            subtitle="Создаём экземпляр и скачиваем моды из пака.",
            icon_name="archive",
            eyebrow="ИМПОРТ СБОРКИ",
            worker_factory=lambda parent: ImportPackTask(
                self.launcher, MarketAPI(self.config), Path(filename), parent
            ),
        )
        dialog.exec()
        result = dialog.result
        error = dialog.error_message
        dialog.deleteLater()
        if result is not None:
            instance, skipped = result
            self.refresh_instances()
            self._open_instance(instance)
            message = f"Сборка «{instance.name}» создана."
            if skipped:
                message += "\n\nПропущены:\n" + "\n".join(skipped[:10])
            self._notice("Импорт завершён", message)
        elif error:
            self._notice("Не удалось импортировать сборку", error)

    def _refresh_content_counts(self) -> None:
        instance = self._current_instance
        if instance is None:
            return
        try:
            counts = self.launcher.content_counts(instance)
        except Exception:
            logger.exception("Could not count instance content")
            return
        self.instance_page.set_content_counts(counts)

    def _delete_current_instance(self) -> None:
        instance = self._current_instance
        if instance is None:
            return
        if self._game_session is not None and self._game_session.is_running():
            self._notice(
                "Игра запущена",
                "Сначала закройте Minecraft, затем удалите экземпляр.",
            )
            return
        if self.market_page.has_active_installs():
            self._notice(
                "Идёт загрузка модов",
                "Дождитесь завершения установки модов или закройте страницу маркета.",
            )
            return
        answer = QMessageBox.warning(
            self,
            "Удалить экземпляр?",
            f"«{instance.name}» будет удалён вместе со всеми модами, "
            "конфигами, мирами и логами.\n\n"
            f"Папка: {instance.path}\n\n"
            "Это действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.launcher.delete_instance(instance)
        except LauncherError as exc:
            self._notice("Не удалось удалить экземпляр", str(exc))
            return
        self._current_instance = None
        self._current_page_key = "home"
        self.refresh_instances()
        self.navigate("home")
        self._notice("Экземпляр удалён", f"Папка «{instance.name}» удалена с диска.")

    def _backup_current(self) -> None:
        instance = self._current_instance
        if instance is None:
            return
        dialog = OperationProgressDialog(
            self,
            title="Бэкап экземпляра",
            subtitle="Упаковываем папки mods и config в ZIP-архив "
            "в %APPDATA%\\Fionix\\backups.",
            icon_name="archive",
            eyebrow="РЕЗЕРВНАЯ КОПИЯ",
            worker_factory=lambda parent: BackupTask(self.launcher, instance, parent),
        )
        dialog.exec()
        result = dialog.result
        error = dialog.error_message
        dialog.deleteLater()
        if result is not None:
            self.instance_page.set_operation_note(f"Бэкап создан: {Path(result).name}")
            self._notice(
                "Бэкап создан",
                f"Архив сохранён:\n{result}",
            )
        elif error:
            self.instance_page.set_operation_note(error, error=True)

    # ------------------------------------------------------------- accounts
    def _maybe_show_welcome(self) -> None:
        if self._welcome_shown:
            return
        self._welcome_shown = True
        if self.accounts.accounts:
            self._refresh_accounts_ui()
            return
        if os.environ.get("FIONIX_SKIP_WELCOME") == "1":
            self.accounts.ensure_guest()
            self._refresh_accounts_ui()
            return
        dialog = AccountWelcomeDialog(self, first_run=True)
        result = dialog.exec()
        provider = dialog.provider
        dialog.deleteLater()
        if result == QDialog.DialogCode.Accepted and provider:
            self._handle_provider(provider, first_run=True)
        if not self.accounts.accounts:
            self.accounts.ensure_guest()
        self._refresh_accounts_ui()

    def _add_account(self) -> None:
        dialog = AccountWelcomeDialog(self, first_run=False)
        result = dialog.exec()
        provider = dialog.provider
        dialog.deleteLater()
        if result == QDialog.DialogCode.Accepted and provider:
            self._handle_provider(provider, first_run=False)

    def _handle_provider(self, provider: str, *, first_run: bool) -> None:
        if provider == "guest":
            account = create_guest()
            self.accounts.add(account)
            self._refresh_accounts_ui()
            return
        if provider in ("littleskin", "elyby"):
            credentials = CredentialsDialog(self, provider)
            result = credentials.exec()
            account = credentials.account
            credentials.deleteLater()
            if result == QDialog.DialogCode.Accepted and account is not None:
                self.accounts.add(account)
                self._refresh_accounts_ui()
            return
        if provider == "microsoft":
            dialog = MicrosoftLoginDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.account is not None:
                self.accounts.add(dialog.account)
                self._refresh_accounts_ui()
            dialog.deleteLater()
            if first_run and not self.accounts.accounts:
                self.accounts.ensure_guest()
                self._refresh_accounts_ui()

    def _switch_account(self, account_id: str) -> None:
        if not self.accounts.set_active(account_id):
            return
        self._refresh_accounts_ui()

    def _logout_account(self) -> None:
        current = self.accounts.current
        if current is None:
            self._notice("Аккаунт не выбран", "Сейчас используется локальный гость.")
            return
        answer = QMessageBox.question(
            self,
            "Выйти из аккаунта",
            f"Удалить аккаунт «{current.username}» с этого компьютера?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.accounts.remove(current.id)
        if not self.accounts.accounts:
            self.accounts.ensure_guest()
        self._refresh_accounts_ui()

    def _refresh_accounts_ui(self) -> None:
        active = self.accounts.current
        self.sidebar.set_accounts(self.accounts.accounts, self.accounts.active_id)
        self.sidebar.set_premium(self.config.premium_active)
        self.settings_page.refresh_accounts()
        name = active.username if active is not None else "Гость"
        self.home_page.set_player_name(name)
        self.sidebar.set_player(name)
        self.config.update({"player": {"name": name}})

    def _load_home_carousel(self) -> None:
        task = HomeCarouselTask(self.market_page._api, self)
        task.succeeded.connect(self.home_page.carousel.set_projects)
        task.finished.connect(task.deleteLater)
        task.start()

    def _on_premium_activated(self) -> None:
        self.sidebar.set_premium(self.config.premium_active)
        self._refresh_accounts_ui()

    def _open_profile(self) -> None:
        dialog = ProfileDialog(self, self.accounts, self.config.data_dir)
        dialog.changed.connect(self._refresh_accounts_ui)
        dialog.exec()
        self._refresh_accounts_ui()
        dialog.deleteLater()

    # ---------------------------------------------------------- background
    def _apply_background(self) -> None:
        self.shell.stop_video()
        background = self.config.get("background", {})
        mode = str(background.get("mode", "asset"))
        raw_path = str(background.get("path", ""))
        default_pixmap = QPixmap(str(asset_path("background.png")))
        if mode == "asset" or not raw_path:
            self.shell.set_background_pixmap(default_pixmap)
            return
        path = Path(raw_path)
        if not path.is_file():
            self.shell.set_background_pixmap(default_pixmap)
            return
        if mode == "image":
            pixmap = QPixmap(str(path))
            self.shell.set_background_pixmap(
                pixmap if not pixmap.isNull() else default_pixmap
            )
            return
        # QGraphicsVideoItem path (hardware-backed, loops indefinitely).
        self.shell.set_background_pixmap(default_pixmap)
        self.shell.play_video(path)

    def _on_accent_changed(self, value: str) -> None:
        set_accent_color(value)
        self.apply_theme(self.config.theme)

    # ---------------------------------------------------------- instances
    def _on_instances_path_changed(self, path: str) -> None:
        if self._game_session is not None and self._game_session.is_running():
            self._notice(
                "Игра запущена",
                "Папку экземпляров нельзя менять во время игры.",
            )
            return
        try:
            self.launcher.reload_instances_dir()
        except OSError as exc:
            self._notice("Не удалось сменить папку", str(exc))
            return
        self.refresh_instances()
        self.navigate("home")

    # ------------------------------------------------------------- updates
    def _check_updates(self, *, manual: bool) -> None:
        if not repo_configured():
            self.title_bar.clear_update()
            self._update_info = None
            if manual:
                self.settings_page.set_update_status(NOT_CONFIGURED_MESSAGE)
                self._notice("Обновления", NOT_CONFIGURED_MESSAGE)
            return
        if getattr(self, "_update_task", None) is not None:
            return
        task = UpdateCheckTask(__version__, self.launcher.proxies, self)
        task.succeeded.connect(
            lambda info: self._on_update_checked(info, manual=manual)
        )
        task.failed.connect(
            lambda message: self._on_update_failed(message, manual=manual)
        )
        task.finished.connect(self._clear_update_task)
        self._update_task = task
        task.start()
        if manual:
            self.settings_page.set_update_status("Проверяем обновления…")

    def _clear_update_task(self) -> None:
        task = getattr(self, "_update_task", None)
        if task is not None:
            task.deleteLater()
        self._update_task = None

    def _on_update_checked(self, info: object, *, manual: bool) -> None:
        if not isinstance(info, UpdateInfo):
            return
        if not info.configured:
            self.title_bar.clear_update()
            self.settings_page.set_update_status(NOT_CONFIGURED_MESSAGE)
            return
        self._update_info = info if info.available else None
        if info.available:
            self.title_bar.set_update_available(info.latest, info.url)
            self.settings_page.set_update_status(
                f"Доступна версия {info.display_latest}."
            )
            if manual:
                answer = QMessageBox.question(
                    self,
                    "Доступно обновление",
                    f"Вышла новая версия Fionix: {info.display_latest}.\n"
                    "Скачать обновление и перезапустить лаунчер?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    self._start_update_download(info)
        else:
            self.title_bar.clear_update()
            self.settings_page.set_update_status(
                f"Установлена актуальная версия v{__version__}."
            )

    def _on_update_failed(self, message: str, *, manual: bool) -> None:
        self.settings_page.set_update_status(message, error=True)
        if manual:
            self._notice("Не удалось проверить обновления", message)

    def _open_update_page(self) -> None:
        if self._update_info is None:
            self._check_updates(manual=True)
            return
        self._start_update_download(self._update_info)

    def _start_update_download(self, info: UpdateInfo) -> None:
        if not info.asset_url:
            self._notice(
                "Обновление недоступно",
                "В последнем релизе GitHub нет .exe-файла для обновления.",
            )
            return
        dialog = OperationProgressDialog(
            self,
            title=f"Обновление Fionix {info.display_latest}",
            subtitle="Скачиваем новый .exe во временную папку. "
            "После загрузки лаунчер перезапустится.",
            icon_name="download",
            eyebrow="ОБНОВЛЕНИЕ",
            worker_factory=lambda parent: UpdateDownloadTask(
                info, self.launcher.proxies, parent
            ),
        )
        dialog.exec()
        path = dialog.result
        error = dialog.error_message
        dialog.deleteLater()
        if path is None:
            if error:
                self._notice("Не удалось обновить Fionix", error)
            return
        self._restart_into_update(Path(path))

    def _restart_into_update(self, executable: Path) -> None:
        started, _pid = QProcess.startDetached(str(executable), [])
        if not started:
            self._notice(
                "Не удалось перезапустить лаунчер",
                f"Файл обновления сохранён:\n{executable}",
            )
            return
        self._quitting = True
        self._allow_close = True
        self._hide_tray_icon()
        self.close()
        QApplication.quit()

    # -------------------------------------------------------------- create
    def _show_version_dialog(self) -> None:
        if self._game_session is not None and self._game_session.is_running():
            self._notice(
                "Minecraft уже запущен",
                "Завершите текущую игру, прежде чем создавать новый экземпляр.",
            )
            return
        dialog = CreateInstanceDialog(self.launcher, self)
        result = dialog.exec()
        version = dialog.selected_version
        loader = dialog.selected_loader
        optimize = dialog.selected_optimize
        dialog.deleteLater()
        if result != QDialog.DialogCode.Accepted or not version:
            return
        existing = self.launcher.instance_for(version, loader)
        if existing is not None:
            self.refresh_instances()
            self._open_instance(existing)
            return
        self._install_version(version, loader, optimize=optimize)

    def _install_version(
        self, version: str, loader: str = "vanilla", *, optimize: bool = False
    ) -> None:
        dialog = InstallProgressDialog(
            self.launcher, version, self, loader=loader, optimize=optimize
        )
        dialog.exec()
        instance = dialog.installed_instance
        dialog.deleteLater()
        if instance is not None:
            self.refresh_instances()
            self._open_instance(instance)

    # ---------------------------------------------------------------- play
    def _play_current(self) -> None:
        instance = self._current_instance
        if instance is None:
            return
        self.settings_page.flush()
        if self._game_session is not None and self._game_session.is_running():
            if self._game_session.instance.folder_name != instance.folder_name:
                self._notice(
                    "Minecraft уже запущен",
                    "Сначала закройте текущую игру, затем можно будет запустить другой экземпляр.",
                )
            return

        self.instance_page.set_busy("Проверка Java…")
        java = None
        if instance.java_path:
            try:
                java = self.launcher.java_for_instance(instance)
            except LauncherError as exc:
                self.instance_page.set_error(str(exc))
                self._notice("Проблема с выбранной Java", str(exc))
                return
        if java is None:
            java = self.launcher.preferred_java(instance.java_major)
        if java is None:
            dialog = JavaProgressDialog(self.launcher, instance.java_major, self)
            dialog.exec()
            java = dialog.java_runtime
            error = dialog.error_message
            dialog.deleteLater()
            if java is None:
                self.instance_page.set_error(
                    error or "Не удалось подготовить Java для запуска."
                )
                return

        self.instance_page.update_java_hint(f"Java {java.major} · {java.source}")
        loading = LaunchLoadingDialog(
            self, f"{instance.name} · проверяем файлы и готовим запуск"
        )
        loading.show()
        QApplication.processEvents()
        try:
            session = self.launcher.create_game_session(
                instance, java, self.accounts.current
            )
        except LauncherError as exc:
            loading.close()
            loading.deleteLater()
            self.instance_page.set_error(str(exc))
            self._notice("Не удалось запустить Minecraft", str(exc))
            return
        QApplication.processEvents()
        if loading.was_cancelled:
            loading.close()
            loading.deleteLater()
            self.instance_page.set_game_finished(instance, 0)
            return

        self._game_session = session
        session.tick.connect(self._on_game_tick)
        session.finished.connect(self._on_game_finished)

        if not session.start():
            loading.close()
            loading.deleteLater()
            message = session.error_message or "Java не запустилась."
            self._game_session = None
            session.deleteLater()
            self.instance_page.set_error(message)
            self._notice(
                "Minecraft не запустился",
                f"{message}\n\nПроверьте лог экземпляра в папке logs.",
            )
            return

        loading.close()
        loading.deleteLater()
        self.instance_page.set_game_running()
        self._enter_game_mode(instance)

    def _enter_game_mode(self, instance: Instance) -> None:
        self._pre_game_maximized = self.isMaximized()
        self._hidden_for_game = True
        if not self._ensure_tray():
            self.showMinimized()
            return
        assert self._tray is not None
        if self._tray_stop_action is not None:
            self._tray_stop_action.setEnabled(True)
        self._tray.setToolTip(f"Fionix · {instance.name} · 00:00:00")
        self._tray.show()
        if QSystemTrayIcon.supportsMessages():
            self._tray.showMessage(
                "Fionix",
                f"{instance.name} запущен. Лаунчер свёрнут в трей и вернётся после закрытия игры.",
                QSystemTrayIcon.MessageIcon.Information,
                3500,
            )
        self.shell.pause_video()
        if self._music_popover is not None:
            self._music_popover.close()
            self._music_popover = None
        self.hide()

    def _on_game_tick(self, session_seconds: int, total_seconds: int) -> None:
        if self._game_session is None:
            return
        if (
            self._current_instance is not None
            and self._current_instance.folder_name == self._game_session.instance.folder_name
        ):
            self.instance_page.update_running(session_seconds, total_seconds)
        if self._tray is not None:
            self._tray.setToolTip(
                f"Fionix · {self._game_session.instance.name} · "
                f"{format_session_time(session_seconds)}"
            )

    def _on_game_finished(self, exit_code: int, _total_seconds: int) -> None:
        session = self._game_session
        if session is None:
            return
        self._game_session = None
        self._hide_tray_icon()

        if self._quitting:
            session.deleteLater()
            return

        fresh = self.launcher.get_instance(session.instance.folder_name) or session.instance
        if (
            self._current_instance is not None
            and self._current_instance.folder_name == fresh.folder_name
        ):
            self._current_instance = fresh
            self.instance_page.set_game_finished(fresh, exit_code)
        self.refresh_instances()
        self._restore_after_game()
        session.deleteLater()

        if exit_code != 0 and not getattr(session, "user_stopped", False):
            try:
                crash = CrashDialog(
                    self,
                    title="Minecraft завершился с ошибкой",
                    log_path=session.log_path,
                    exit_code=exit_code,
                )
                crash.exec()
                crash.deleteLater()
            except Exception:
                logger.exception("Could not show crash dialog")
                self._notice(
                    "Minecraft завершился с ошибкой",
                    f"Игра закрылась с кодом {exit_code}.\n"
                    f"Подробности сохранены в папке:\n{session.log_path.parent}",
                )

    def _restore_after_game(self) -> None:
        if not self._hidden_for_game:
            return
        self._hidden_for_game = False
        self.showNormal()
        if self._pre_game_maximized:
            self.showMaximized()
        self.shell.resume_video()
        self.raise_()
        self.activateWindow()

    # --------------------------------------------------------------- tray
    def _ensure_tray(self) -> bool:
        if self._tray is not None:
            return True
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray is not available")
            return False
        icon_path = asset_path("icons", "fionix.ico")
        icon = (
            QIcon(str(icon_path))
            if icon_path.exists()
            else self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        )
        tray = QSystemTrayIcon(icon, self)
        menu = QMenu(self)
        show_action = menu.addAction("Показать лаунчер")
        show_action.triggered.connect(self._show_launcher_from_tray)
        self._tray_stop_action = menu.addAction("Остановить игру")
        self._tray_stop_action.triggered.connect(self._stop_game_from_tray)
        self._tray_stop_action.setEnabled(False)
        menu.addSeparator()
        quit_action = menu.addAction("Выход")
        quit_action.triggered.connect(self._quit_from_tray)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.setToolTip("Fionix")
        self._tray = tray
        self._tray_menu = menu
        return True

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_launcher_from_tray()

    def _show_launcher_from_tray(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        if self._pre_game_maximized:
            self.showMaximized()
        self.raise_()
        self.activateWindow()

    def _hide_tray_icon(self) -> None:
        if self._tray_stop_action is not None:
            self._tray_stop_action.setEnabled(False)
        if self._tray is not None:
            self._tray.hide()

    def _stop_game_from_tray(self) -> None:
        if self._game_session is None or not self._game_session.is_running():
            return
        self._show_launcher_from_tray()
        answer = QMessageBox.question(
            self,
            "Остановить Minecraft",
            "Завершить запущенную игру?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.instance_page.set_busy("Останавливаем Minecraft…")
            self._game_session.stop()

    def _quit_from_tray(self) -> None:
        if self._game_session is not None and self._game_session.is_running():
            self._show_launcher_from_tray()
            answer = QMessageBox.question(
                self,
                "Выход из Fionix",
                "Minecraft ещё запущен. Закрыть игру и выйти?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._quitting = True
            self._game_session.stop(wait_ms=2500)
        else:
            self._quitting = True
        self._allow_close = True
        self._hide_tray_icon()
        self.close()
        QApplication.quit()

    # -------------------------------------------------------------- pages
    def _restore_page(self) -> None:
        saved = self.config.last_page
        key = saved if saved in PAGE_ORDER else "home"
        self.navigate(key, persist=False, animate=False)

    def navigate(self, key: str, *, persist: bool = True, animate: bool = True) -> None:
        if key not in PAGE_ORDER:
            key = "home"
        page = {
            "home": self.home_page,
            "store": self.store_page,
            "premium": self.premium_page,
            "settings": self.settings_page,
        }[key]
        if key == "store":
            self.store_page.ensure_loaded()

        self.sidebar.set_active(key)
        changed = key != self._current_page_key
        self._current_page_key = key
        self.stack.setCurrentWidget(page)
        self.setWindowTitle("Fionix")

        if animate and changed:
            self._fade_in_page(page)
        if persist and self.config.last_page != key:
            self.config.last_page = key

    def _fade_in_page(self, page: QWidget) -> None:
        if self._page_animation is not None:
            self._page_animation.stop()
            self._page_animation = None
        if self._fading_page is not None:
            self._fading_page.setGraphicsEffect(None)
            self._fading_page = None
        self._page_effect = None

        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(200)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def finish() -> None:
            if page.graphicsEffect() is effect:
                page.setGraphicsEffect(None)
            if self._fading_page is page:
                self._fading_page = None
            self._page_effect = None
            self._page_animation = None

        animation.finished.connect(finish)
        self._page_effect = effect
        self._page_animation = animation
        self._fading_page = page
        animation.start()

    # ------------------------------------------------------------- notices
    def _notice(self, title: str, message: str) -> None:
        dialog = NoticeDialog(self, title, message)
        dialog.exec()
        dialog.deleteLater()

    # -------------------------------------------------------------- theme
    def apply_theme(self, key: str) -> None:
        theme = set_theme(key)
        set_accent_color(self.config.accent)
        set_custom_colors(self.config.text_color, self.config.panel_color)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(theme))
        self.shell.refresh_theme()
        for widget in self.findChildren(QWidget):
            refresh = getattr(widget, "refresh_theme", None)
            if callable(refresh):
                refresh()
            else:
                widget.update()
        self.update()

    # ------------------------------------------------------------- music
    def _toggle_music_popover(self) -> None:
        if self._music_popover is not None and self._music_popover.isVisible():
            self._music_popover.close()
            self._music_popover = None
            return

        popover = MusicPopover(self.title_bar.music_button)
        popover.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        popover.destroyed.connect(self._clear_music_popover)
        self._music_popover = popover
        popover.show_at_anchor()

    def _clear_music_popover(self) -> None:
        self._music_popover = None

    def _toggle_downloads_panel(self) -> None:
        if self._downloads_panel is not None and self._downloads_panel.isVisible():
            self._downloads_panel.close()
            self._downloads_panel = None
            return
        panel = DownloadsPanel(self)
        panel.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        panel.destroyed.connect(lambda: setattr(self, "_downloads_panel", None))
        self._downloads_panel = panel
        panel.show_at(self.title_bar.downloads_button)

    # ------------------------------------------------------------- window
    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _update_window_chrome(self) -> None:
        maximized = self.isMaximized()
        fullscreen = self.isFullScreen() or self._fullscreen
        edge_to_edge = maximized or fullscreen
        self.title_bar.set_maximized(maximized)
        margin = 0 if edge_to_edge else 20
        self._root_layout.setContentsMargins(margin, margin, margin, margin)
        self.shell.set_corner_radius(0 if edge_to_edge else 20)
        self._shell_shadow.setEnabled(not edge_to_edge)
        self.sidebar.setProperty("maximized", "true" if edge_to_edge else "false")
        self.sidebar.style().unpolish(self.sidebar)
        self.sidebar.style().polish(self.sidebar)
        self.sidebar.update()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen() or self._fullscreen:
            self._fullscreen = False
            self.showNormal()
            if self._pre_fullscreen_maximized:
                self.showMaximized()
        else:
            self._pre_fullscreen_maximized = self.isMaximized()
            self._fullscreen = True
            self.showFullScreen()
        self._update_window_chrome()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_F11 and not event.isAutoRepeat():
            self._toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.WindowStateChange:
            self._update_window_chrome()
        super().changeEvent(event)

    def _restore_window_geometry(self) -> None:
        window = self.config.get("window", {})
        width = int(window.get("width", 1360))
        height = int(window.get("height", 860))
        x = window.get("x")
        y = window.get("y")

        screen = QGuiApplication.primaryScreen()
        saved_rect = (
            QRect(int(x), int(y), width, height)
            if isinstance(x, int) and isinstance(y, int)
            else None
        )
        if saved_rect is not None:
            for candidate in QGuiApplication.screens():
                if candidate.availableGeometry().intersects(saved_rect):
                    screen = candidate
                    break

        available = (
            screen.availableGeometry()
            if screen is not None
            else QRect(0, 0, 1920, 1080)
        )
        width = max(self.minimumWidth(), min(width, available.width() - 32))
        height = max(self.minimumHeight(), min(height, available.height() - 32))
        self.resize(width, height)

        if saved_rect is not None:
            x = max(available.left() + 8, min(saved_rect.x(), available.right() - width - 8))
            y = max(available.top() + 8, min(saved_rect.y(), available.bottom() - height - 8))
            self.move(x, y)
        else:
            self.move(
                available.center().x() - width // 2,
                available.center().y() - height // 2,
            )

    # ------------------------------------------------------ edge resizing
    RESIZE_MARGIN = 7

    def _edges_at(self, global_pos: QPoint) -> Qt.Edge:
        if self.isMaximized():
            return Qt.Edge(0)
        local = self.mapFromGlobal(global_pos)
        edges = Qt.Edge(0)
        margin = self.RESIZE_MARGIN
        if local.x() <= margin:
            edges |= Qt.Edge.LeftEdge
        elif local.x() >= self.width() - margin:
            edges |= Qt.Edge.RightEdge
        if local.y() <= margin:
            edges |= Qt.Edge.TopEdge
        elif local.y() >= self.height() - margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor_for_edges(edges: Qt.Edge) -> Qt.CursorShape:
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self._central:
            if event.type() == QEvent.Type.MouseMove:
                edges = self._edges_at(event.globalPosition().toPoint())
                self._central.setCursor(self._cursor_for_edges(edges))
            elif (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                edges = self._edges_at(event.globalPosition().toPoint())
                if edges:
                    handle = self.windowHandle()
                    if handle is not None:
                        handle.startSystemResize(edges)
                        return True
        return super().eventFilter(watched, event)

    # --------------------------------------------------------------- close
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if (
            not self._allow_close
            and self._game_session is not None
            and self._game_session.is_running()
        ):
            self._pre_game_maximized = self.isMaximized()
            if self._ensure_tray():
                assert self._tray is not None
                if self._tray_stop_action is not None:
                    self._tray_stop_action.setEnabled(True)
                self._tray.show()
                if QSystemTrayIcon.supportsMessages():
                    self._tray.showMessage(
                        "Fionix остаётся в трее",
                        "Minecraft продолжает работать. Лаунчер вернётся после закрытия игры.",
                        QSystemTrayIcon.MessageIcon.Information,
                        3000,
                    )
                self._hidden_for_game = True
                self.hide()
            else:
                self.showMinimized()
            event.ignore()
            return

        self.settings_page.flush()
        self.market_page.shutdown()
        self.store_page.shutdown()
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        self.config.set_window_state(
            geometry.width(),
            geometry.height(),
            geometry.x(),
            geometry.y(),
            self.isMaximized(),
        )
        self.shell.stop_video()
        if self._tray is not None:
            self._tray.hide()
        super().closeEvent(event)
