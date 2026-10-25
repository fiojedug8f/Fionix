"""Qt worker wrappers around the blocking :mod:`src.core.launcher` calls.

All network and process work stays in the core service; these classes only
move it off the UI thread and translate progress into signals.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QRunnable, QThread, Signal

from src.core.accounts import (
    AccountError,
    login_elyby,
    login_littleskin,
    login_microsoft_manual,
    login_microsoft_oauth,
)
from src.core.exporter import PackError, import_pack
from src.core.launcher import InstallCancelled, LauncherError, LauncherService
from src.core.market_api import MarketAPI, MarketError, MarketKeyMissing
from src.core.modpacks import install_modpack, resolve_modpack
from src.core.updater import UpdateError, check_for_updates, download_update

logger = logging.getLogger(__name__)


class InstallTask(QThread):
    progress = Signal(int, str, str)  # percent, title, detail
    succeeded = Signal(object)  # Instance
    failed = Signal(str, bool)  # message, was_cancelled

    def __init__(
        self,
        service: LauncherService,
        version: str,
        loader: str = "vanilla",
        parent: QObject | None = None,
        *,
        optimize: bool = False,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._version = version
        self._loader = loader
        self._optimize = optimize
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        def report(percent: int, title: str, detail: str) -> None:
            self.progress.emit(percent, title, detail)

        try:
            instance = self._service.create_instance(
                self._version,
                self._loader,
                progress=report,
                cancel_event=self._cancel_event,
                optimize=self._optimize,
            )
        except InstallCancelled:
            self.failed.emit("Установка отменена.", True)
        except LauncherError as exc:
            logger.error("Minecraft installation error: %s", exc)
            self.failed.emit(str(exc), False)
        except Exception:
            logger.exception("Unexpected installation error")
            self.failed.emit(
                "Неожиданная ошибка при установке. Подробности — в логе Fionix.",
                False,
            )
        else:
            self.succeeded.emit(instance)


class JavaTask(QThread):
    progress = Signal(int, str, str)
    succeeded = Signal(object)  # JavaRuntime
    failed = Signal(str, bool)

    def __init__(self, service: LauncherService, major: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._major = major
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        def report(percent: int, title: str, detail: str) -> None:
            self.progress.emit(percent, title, detail)

        try:
            runtime = self._service.ensure_java(
                self._major,
                progress=report,
                cancel_event=self._cancel_event,
            )
        except InstallCancelled:
            self.failed.emit("Загрузка Java отменена.", True)
        except LauncherError as exc:
            logger.error("Java setup error: %s", exc)
            self.failed.emit(str(exc), False)
        except Exception:
            logger.exception("Unexpected Java setup error")
            self.failed.emit(
                "Не удалось подготовить Java. Подробности — в логе Fionix.",
                False,
            )
        else:
            self.succeeded.emit(runtime)


class OptimizeTask(QThread):
    progress = Signal(int, str, str)
    succeeded = Signal(object)  # Path to enabled mod
    failed = Signal(str, bool)

    def __init__(self, service: LauncherService, instance, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._instance = instance
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        def report(percent: int, title: str, detail: str) -> None:
            self.progress.emit(percent, title, detail)

        try:
            path = self._service.install_optimization(
                self._instance,
                progress=report,
                cancel_event=self._cancel_event,
            )
        except InstallCancelled:
            self.failed.emit("Оптимизация отменена.", True)
        except LauncherError as exc:
            logger.error("Optimization error: %s", exc)
            self.failed.emit(str(exc), False)
        except Exception:
            logger.exception("Unexpected optimization error")
            self.failed.emit(
                "Неожиданная ошибка при установке оптимизации. Подробности в логе.",
                False,
            )
        else:
            self.succeeded.emit(path)


class BackupTask(QThread):
    progress = Signal(int, str, str)
    succeeded = Signal(object)  # Path to zip
    failed = Signal(str, bool)

    def __init__(self, service: LauncherService, instance, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._instance = instance
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        def report(percent: int, title: str, detail: str) -> None:
            self.progress.emit(percent, title, detail)

        try:
            path = self._service.create_backup(
                self._instance,
                progress=report,
                cancel_event=self._cancel_event,
            )
        except InstallCancelled:
            self.failed.emit("Создание бэкапа отменено.", True)
        except LauncherError as exc:
            logger.error("Backup error: %s", exc)
            self.failed.emit(str(exc), False)
        except Exception:
            logger.exception("Unexpected backup error")
            self.failed.emit(
                "Неожиданная ошибка при создании бэкапа. Подробности в логе.",
                False,
            )
        else:
            self.succeeded.emit(path)


class MarketSearchTask(QThread):
    succeeded = Signal(object)  # list[MarketProject]
    failed = Signal(str)

    def __init__(
        self,
        api: MarketAPI,
        query: str,
        mc_version: str,
        loader: str,
        source: str,
        parent: QObject | None = None,
        *,
        popular: bool = False,
        project_type: str = "mod",
        offset: int = 0,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._query = query
        self._mc_version = mc_version
        self._loader = loader
        self._source = source
        self._popular = popular
        self._project_type = project_type
        self._offset = max(0, int(offset))

    def run(self) -> None:
        try:
            if self._source == "curseforge":
                projects = self._api.search_curseforge_type(
                    self._project_type,
                    self._query,
                    self._mc_version,
                    self._loader,
                    self._offset,
                )
            elif self._popular and not self._query and self._project_type == "mod":
                projects = self._api.popular_modrinth(limit=20, offset=self._offset)
            else:
                projects = self._api.search_modrinth_type(
                    self._project_type,
                    self._query,
                    self._mc_version,
                    self._loader,
                    offset=self._offset,
                )
        except MarketKeyMissing as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            logger.warning("Market search failed: %s", exc)
            self.failed.emit(str(exc) or "Не удалось выполнить поиск.")
        else:
            self.succeeded.emit(projects)


class MarketInstallTask(QThread):
    progress = Signal(int, str, str)
    succeeded = Signal(object)  # InstallOutcome
    failed = Signal(str, bool)

    def __init__(
        self,
        api: MarketAPI,
        instance,
        project,
        *,
        include_dependencies: bool = True,
        category: str = "mod",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._instance = instance
        self._project = project
        self._include_dependencies = include_dependencies
        self._category = category
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        def report(percent: int, title: str, detail: str) -> None:
            self.progress.emit(percent, title, detail)

        try:
            if self._project.source == "curseforge":
                outcome = self._api.install_curseforge(
                    self._instance,
                    self._project,
                    progress=report,
                    cancel_event=self._cancel_event,
                )
            elif self._category == "mod":
                outcome = self._api.install_modrinth(
                    self._instance,
                    self._project.id,
                    include_dependencies=self._include_dependencies,
                    progress=report,
                    cancel_event=self._cancel_event,
                )
            else:
                outcome = self._api.install_modrinth_content(
                    self._instance,
                    self._project.id,
                    self._category,
                    progress=report,
                    cancel_event=self._cancel_event,
                )
        except InstallCancelled:
            self.failed.emit("Загрузка отменена.", True)
        except (MarketError, OSError) as exc:
            logger.warning("Mod install failed: %s", exc)
            self.failed.emit(str(exc), False)
        except Exception:
            logger.exception("Unexpected mod install error")
            self.failed.emit("Не удалось установить мод. Подробности в логе.", False)
        else:
            self.succeeded.emit(outcome)


class ImportPackTask(QThread):
    progress = Signal(int, str, str)
    succeeded = Signal(object, object)  # Instance, list[str]
    failed = Signal(str, bool)

    def __init__(
        self,
        service: LauncherService,
        api: MarketAPI,
        path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._api = api
        self._path = path
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        def report(percent: int, title: str, detail: str) -> None:
            self.progress.emit(percent, title, detail)

        try:
            instance, skipped = import_pack(
                self._service,
                self._api,
                self._path,
                progress=report,
                cancel_event=self._cancel_event,
            )
        except InstallCancelled:
            self.failed.emit("Импорт отменён.", True)
        except (PackError, LauncherError) as exc:
            logger.warning("Import failed: %s", exc)
            self.failed.emit(str(exc), False)
        except Exception:
            logger.exception("Unexpected pack import error")
            self.failed.emit("Не удалось импортировать сборку.", False)
        else:
            self.succeeded.emit(instance, skipped)


class UpdateCheckTask(QThread):
    succeeded = Signal(object)  # UpdateInfo
    failed = Signal(str)

    def __init__(self, current: str, proxies=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current = current
        self._proxies = proxies

    def run(self) -> None:
        try:
            info = check_for_updates(self._current, proxies=self._proxies)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            logger.warning("Update check failed: %s", exc)
            self.failed.emit("Не удалось проверить обновления.")
        else:
            self.succeeded.emit(info)


class UpdateDownloadTask(QThread):
    progress = Signal(int, str, str)
    succeeded = Signal(object)  # Path to downloaded exe
    failed = Signal(str, bool)

    def __init__(self, info, proxies=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._info = info
        self._proxies = proxies
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        def report(percent: int, title: str, detail: str) -> None:
            self.progress.emit(percent, title, detail)

        try:
            path = download_update(
                self._info,
                progress=report,
                proxies=self._proxies,
                cancel_event=self._cancel_event,
            )
        except InstallCancelled:
            self.failed.emit("Загрузка обновления отменена.", True)
        except UpdateError as exc:
            self.failed.emit(str(exc), False)
        except Exception:
            logger.exception("Unexpected update download error")
            self.failed.emit("Не удалось скачать обновление.", False)
        else:
            self.succeeded.emit(path)


class MicrosoftOAuthTask(QThread):
    succeeded = Signal(object)  # Account
    failed = Signal(str)
    browser_requested = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            account = login_microsoft_oauth(
                cancel_event=self._cancel_event,
                on_browser_url=self.browser_requested.emit,
            )
        except AccountError as exc:
            logger.warning("Microsoft OAuth failed: %s", exc)
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Unexpected Microsoft OAuth error")
            self.failed.emit("Не удалось завершить вход Microsoft.")
        else:
            self.succeeded.emit(account)


class MicrosoftCodeTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, code: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._code = code

    def run(self) -> None:
        try:
            account = login_microsoft_manual(self._code)
        except AccountError as exc:
            logger.warning("Microsoft code exchange failed: %s", exc)
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Unexpected Microsoft code exchange error")
            self.failed.emit("Не удалось обменять код Microsoft на токен.")
        else:
            self.succeeded.emit(account)


class AccountLoginTask(QThread):
    succeeded = Signal(object)  # Account
    failed = Signal(str)

    def __init__(
        self,
        provider: str,
        username: str,
        password: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._username = username
        self._password = password

    def run(self) -> None:
        try:
            if self._provider == "littleskin":
                account = login_littleskin(self._username, self._password)
            elif self._provider == "elyby":
                account = login_elyby(self._username, self._password)
            else:
                raise AccountError("Этот способ входа не поддерживается.")
        except AccountError as exc:
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Unexpected account login error")
            self.failed.emit("Не удалось войти. Подробности в логе.")
        else:
            self.succeeded.emit(account)


class FetchVersionsSignals(QObject):
    finished = Signal(object)  # list[VersionEntry]
    failed = Signal(str)


class HomeCarouselTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, api: MarketAPI, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._api = api

    def run(self) -> None:
        import random

        projects = []
        try:
            for offset in (0, 20, 40, 60, 80):
                projects.extend(self._api.popular_modpacks(offset))
            unique = {project.id: project for project in projects}
            picks = random.sample(list(unique.values()), min(6, len(unique)))
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(picks)


class ModpackSearchTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        api: MarketAPI,
        query: str,
        source: str,
        mc_version: str = "",
        loader: str = "",
        popular: bool = False,
        offset: int = 0,
        project_type: str = "modpack",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._query = query
        self._source = source
        self._mc_version = mc_version
        self._loader = loader
        self._popular = popular
        self._offset = max(0, int(offset))
        self._project_type = project_type

    def run(self) -> None:
        try:
            if self._source == "curseforge":
                projects = self._api.search_curseforge_type(
                    self._project_type,
                    self._query,
                    self._mc_version,
                    self._loader,
                    self._offset,
                )
            elif self._project_type == "modpack" and not self._query:
                projects = self._api.popular_modpacks(self._offset)
            else:
                projects = self._api.search_modrinth_type(
                    self._project_type,
                    self._query,
                    self._mc_version,
                    self._loader,
                    offset=self._offset,
                )
        except (MarketError, MarketKeyMissing) as exc:
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Modpack search failed")
            self.failed.emit("Не удалось загрузить сборки.")
        else:
            self.succeeded.emit(projects)


class ModpackDetailsTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, api: MarketAPI, project, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._project = project
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            info = resolve_modpack(
                self._api, self._project, cancel_event=self._cancel_event
            )
        except (MarketError, MarketKeyMissing) as exc:
            self.failed.emit(str(exc))
        except Exception:
            logger.exception("Modpack details failed")
            self.failed.emit("Не удалось прочитать сборку.")
        else:
            self.succeeded.emit(info)


class ModpackProjectInstallTask(QThread):
    progress = Signal(int, str, str)
    succeeded = Signal(object)
    failed = Signal(str, bool)

    def __init__(self, service, api, project, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._api = api
        self._project = project
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            info = resolve_modpack(
                self._api, self._project, cancel_event=self._cancel_event
            )
            instance = install_modpack(
                self._service,
                self._api,
                info,
                progress=lambda p, t, d: self.progress.emit(p, t, d),
                cancel_event=self._cancel_event,
            )
        except InstallCancelled:
            self.failed.emit("Установка сборки отменена.", True)
        except (MarketError, LauncherError) as exc:
            self.failed.emit(str(exc), False)
        except Exception:
            logger.exception("Modpack project install failed")
            self.failed.emit("Не удалось установить сборку.", False)
        else:
            self.succeeded.emit(instance)


class ModpackInstallTask(QThread):
    progress = Signal(int, str, str)
    succeeded = Signal(object)
    failed = Signal(str, bool)

    def __init__(
        self,
        service: LauncherService,
        api: MarketAPI,
        info,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._api = api
        self._info = info
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            instance = install_modpack(
                self._service,
                self._api,
                self._info,
                progress=lambda p, t, d: self.progress.emit(p, t, d),
                cancel_event=self._cancel_event,
            )
        except InstallCancelled:
            self.failed.emit("Установка сборки отменена.", True)
        except (MarketError, LauncherError) as exc:
            self.failed.emit(str(exc), False)
        except Exception:
            logger.exception("Modpack install failed")
            self.failed.emit("Не удалось установить сборку.", False)
        else:
            self.succeeded.emit(instance)


class FetchVersionsTask(QRunnable):
    """Fetch the Mojang version manifest without blocking the picker dialog."""

    def __init__(self, service: LauncherService) -> None:
        super().__init__()
        self.signals = FetchVersionsSignals()
        self._service = service
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            versions = self._service.fetch_release_versions()
        except Exception as exc:
            logger.warning("Could not fetch version list: %s", exc)
            try:
                self.signals.failed.emit(str(exc))
            except RuntimeError:
                # The picker (and QApplication) may already be gone during exit.
                pass
        else:
            try:
                self.signals.finished.emit(versions)
            except RuntimeError:
                pass
