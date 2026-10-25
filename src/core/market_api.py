"""Modrinth and CurseForge integration for the Fionix marketplace.

The module is UI-agnostic: workers call it from a QThread and the market page
renders the resulting dataclasses.  Modrinth needs no key; CurseForge requires
an API key configured in Settings.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from src.core.exporter import record_installed_mod
from src.core.launcher import Instance, LauncherError

logger = logging.getLogger(__name__)

MODRINTH_API = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"
HTTP_HEADERS = {"User-Agent": "Fionix/1.0 (Minecraft launcher)"}

Progress = Callable[[int, str, str], None]


class MarketError(LauncherError):
    """Marketplace/network error that can be displayed to the player."""


class MarketKeyMissing(MarketError):
    """CurseForge was opened without an API key."""


@dataclass(frozen=True, slots=True)
class MarketProject:
    id: str
    slug: str
    name: str
    author: str
    description: str
    icon_url: str
    downloads: int
    source: str
    body: str = ""
    game_versions: tuple[str, ...] = ()
    loaders: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class MarketDependency:
    project_id: str
    version_id: str = ""
    dependency_type: str = "required"
    name: str = ""


@dataclass(frozen=True, slots=True)
class MarketVersion:
    id: str
    project_id: str
    name: str
    version_number: str
    filename: str
    url: str
    sha512: str = ""
    game_versions: tuple[str, ...] = ()
    loaders: tuple[str, ...] = ()
    dependencies: tuple[MarketDependency, ...] = ()
    version_type: str = ""
    published: str = ""


@dataclass(slots=True)
class InstallOutcome:
    paths: list[Path] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _emit(progress: Progress | None, percent: int, title: str, detail: str = "") -> None:
    if progress is not None:
        progress(max(0, min(100, int(percent))), title, detail)


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        from src.core.launcher import InstallCancelled

        raise InstallCancelled("Загрузка отменена пользователем.")


def _safe_filename(value: str, fallback: str = "mod.jar") -> str:
    name = Path(str(value)).name
    name = re.sub(r"[^A-Za-z0-9._+!@ -]", "_", name).strip(". ")
    return name or fallback


class MarketAPI:
    def __init__(self, config) -> None:
        self.config = config
        self._project_cache: dict[str, MarketProject] = {}

    @property
    def curseforge_key(self) -> str:
        value = str(self.config.get("curseforge_key", "") or "").strip()
        if value:
            return value
        from config import CURSEFORGE_API_KEY

        return str(CURSEFORGE_API_KEY or "").strip()

    @property
    def proxies(self) -> dict[str, str] | None:
        proxy = self.config.get("proxy", {})
        if not proxy.get("enabled"):
            return None
        host = str(proxy.get("host", "")).strip()
        if not host:
            return None
        port = int(proxy.get("port", 8080) or 8080)
        username = str(proxy.get("username", "") or "")
        password = str(proxy.get("password", "") or "")
        auth = ""
        if username:
            from urllib.parse import quote

            auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
        url = f"http://{auth}{host}:{port}"
        return {"http": url, "https": url}

    def _json(self, url: str, *, params: Mapping[str, Any] | None = None,
              headers: Mapping[str, str] | None = None, timeout=(10, 30)) -> Any:
        merged = dict(HTTP_HEADERS)
        if headers:
            merged.update(headers)
        try:
            response = requests.get(
                url,
                params=params,
                headers=merged,
                proxies=self.proxies,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise MarketError("Нет связи с интернетом или сервер недоступен.") from exc
        if response.status_code == 403 and "curseforge" in url:
            raise MarketError("CurseForge отклонил API-ключ (403).")
        if response.status_code >= 400:
            raise MarketError(f"Сервер вернул ошибку {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise MarketError("Сервер вернул некорректный ответ.") from exc

    # --------------------------------------------------------------- modrinth
    def _modrinth_hits(self, payload: Any) -> list[MarketProject]:
        hits = payload.get("hits", []) if isinstance(payload, Mapping) else []
        projects: list[MarketProject] = []
        for hit in hits:
            if not isinstance(hit, Mapping):
                continue
            projects.append(
                MarketProject(
                    id=str(hit.get("project_id") or ""),
                    slug=str(hit.get("slug") or ""),
                    name=str(hit.get("title") or "Без названия"),
                    author=str(hit.get("author") or "неизвестен"),
                    description=str(hit.get("description") or ""),
                    icon_url=str(hit.get("icon_url") or ""),
                    downloads=int(hit.get("downloads") or 0),
                    source="modrinth",
                    game_versions=tuple(hit.get("versions") or ()),
                    loaders=tuple(hit.get("categories") or ()),
                    raw=hit,
                )
            )
        return projects

    def search_modrinth_type(
        self,
        project_type: str,
        query: str,
        mc_version: str = "",
        loader: str = "",
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> list[MarketProject]:
        # Modrinth has no separate "map" project type; maps live in datapacks.
        if project_type == "map":
            project_type = "datapack"
        facets: list[list[str]] = [[f"project_type:{project_type}"]]
        if mc_version:
            facets.append([f"versions:{mc_version}"])
        if loader in {"fabric", "forge", "quilt", "neoforge"} and project_type in {
            "mod",
            "modpack",
        }:
            facets.append([f"categories:{loader}"])
        payload = self._json(
            f"{MODRINTH_API}/search",
            params={
                "query": query,
                "facets": json.dumps(facets),
                "limit": limit,
                "offset": offset,
                "index": "relevance",
            },
        )
        return self._modrinth_hits(payload)

    def search_modrinth(
        self, query: str, mc_version: str, loader: str, *, offset: int = 0, limit: int = 20
    ) -> list[MarketProject]:
        return self.search_modrinth_type(
            "mod", query, mc_version, loader, offset=offset, limit=limit
        )

    def popular_modrinth(
        self, *, limit: int = 20, offset: int = 0
    ) -> list[MarketProject]:
        """Popular mods for the empty Market tab (no version facets)."""
        payload = self._json(
            f"{MODRINTH_API}/search",
            params={
                "facets": json.dumps([["project_type:mod"]]),
                "limit": limit,
                "offset": offset,
                "index": "downloads",
            },
        )
        return self._modrinth_hits(payload)

    def search_curseforge_type(
        self,
        project_type: str,
        query: str,
        mc_version: str = "",
        loader: str = "",
        offset: int = 0,
    ) -> list[MarketProject]:
        class_ids = {
            "mod": 6,
            "modpack": 4471,
            "resourcepack": 12,
            "shader": 6552,
            "map": 17,
        }
        return self.search_curseforge(
            query,
            mc_version,
            loader,
            class_id=class_ids.get(project_type, 6),
            limit=20,
            offset=offset,
        )

    def search_curseforge_modpacks(
        self, query: str, mc_version: str = "", loader: str = "", offset: int = 0
    ) -> list[MarketProject]:
        return self.search_curseforge(
            query, mc_version, loader, class_id=4471, limit=20, offset=offset
        )

    def search_modpacks(
        self, query: str, mc_version: str = "", loader: str = "", offset: int = 0
    ) -> list[MarketProject]:
        return self.search_modrinth_type(
            "modpack", query, mc_version, loader, offset=offset
        )

    def popular_modpacks(self, offset: int = 0) -> list[MarketProject]:
        return self.search_modpacks("", offset=offset)

    def modrinth_all_versions(self, project_id: str) -> list[MarketVersion]:
        data = self._json(f"{MODRINTH_API}/project/{project_id}/version")
        if not isinstance(data, list):
            return []
        return self._parse_modrinth_versions(data, project_id)

    def _parse_modrinth_versions(
        self, data: list, project_id: str
    ) -> list[MarketVersion]:
        versions: list[MarketVersion] = []
        for raw in data:
            if not isinstance(raw, Mapping):
                continue
            files = raw.get("files") or []
            chosen = next(
                (item for item in files if isinstance(item, Mapping) and item.get("primary")),
                files[0] if files else None,
            )
            if not isinstance(chosen, Mapping):
                continue
            dependencies = []
            for dep in raw.get("dependencies", []):
                if isinstance(dep, Mapping) and dep.get("project_id"):
                    dependencies.append(
                        MarketDependency(
                            project_id=str(dep["project_id"]),
                            version_id=str(dep.get("version_id") or ""),
                            dependency_type=str(dep.get("dependency_type") or "required"),
                        )
                    )
            versions.append(
                MarketVersion(
                    id=str(raw.get("id") or ""),
                    project_id=str(raw.get("project_id") or project_id),
                    name=str(raw.get("name") or ""),
                    version_number=str(raw.get("version_number") or ""),
                    filename=_safe_filename(str(chosen.get("filename") or "pack.mrpack")),
                    url=str(chosen.get("url") or ""),
                    sha512=str((chosen.get("hashes") or {}).get("sha512") or ""),
                    game_versions=tuple(raw.get("game_versions") or ()),
                    loaders=tuple(raw.get("loaders") or ()),
                    dependencies=tuple(dependencies),
                    version_type=str(raw.get("version_type") or ""),
                    published=str(raw.get("date_published") or ""),
                )
            )
        return versions

    def curseforge_file(self, project_id: int, file_id: int) -> Mapping[str, Any] | None:
        if not self.curseforge_key:
            return None
        try:
            payload = self._json(
                f"{CURSEFORGE_API}/v1/mods/{project_id}/files/{file_id}",
                headers={"x-api-key": self.curseforge_key},
            )
        except MarketError:
            return None
        data = payload.get("data") if isinstance(payload, Mapping) else None
        return data if isinstance(data, Mapping) else None

    def curseforge_modpack_file(self, project: MarketProject) -> Mapping[str, Any] | None:
        files = project.raw.get("latestFiles") or []
        return next(
            (item for item in files if isinstance(item, Mapping) and item.get("downloadUrl")),
            None,
        )

    def modrinth_project(self, project_id: str) -> MarketProject:
        if project_id in self._project_cache:
            return self._project_cache[project_id]
        data = self._json(f"{MODRINTH_API}/project/{project_id}")
        if not isinstance(data, Mapping):
            raise MarketError("Проект Modrinth не найден.")
        project = MarketProject(
            id=str(data.get("id") or project_id),
            slug=str(data.get("slug") or ""),
            name=str(data.get("title") or "Без названия"),
            author="",
            description=str(data.get("description") or ""),
            icon_url=str(data.get("icon_url") or ""),
            downloads=int(data.get("downloads") or 0),
            source="modrinth",
            body=str(data.get("body") or ""),
            game_versions=tuple(data.get("game_versions") or ()),
            loaders=tuple(data.get("loaders") or ()),
            raw=data,
        )
        self._project_cache[project_id] = project
        return project

    def modrinth_versions(
        self, project_id: str, mc_version: str, loader: str
    ) -> list[MarketVersion]:
        params: dict[str, str] = {"game_versions": json.dumps([mc_version])}
        if loader:
            params["loaders"] = json.dumps([loader])
        data = self._json(f"{MODRINTH_API}/project/{project_id}/version", params=params)
        if not isinstance(data, list):
            return []
        versions: list[MarketVersion] = []
        for raw in data:
            if not isinstance(raw, Mapping):
                continue
            files = raw.get("files") or []
            chosen = next(
                (item for item in files if isinstance(item, Mapping) and item.get("primary")),
                files[0] if files else None,
            )
            if not isinstance(chosen, Mapping):
                continue
            dependencies = []
            for dep in raw.get("dependencies", []):
                if isinstance(dep, Mapping) and dep.get("project_id"):
                    dependencies.append(
                        MarketDependency(
                            project_id=str(dep["project_id"]),
                            version_id=str(dep.get("version_id") or ""),
                            dependency_type=str(dep.get("dependency_type") or "required"),
                        )
                    )
            versions.append(
                MarketVersion(
                    id=str(raw.get("id") or ""),
                    project_id=str(raw.get("project_id") or project_id),
                    name=str(raw.get("name") or ""),
                    version_number=str(raw.get("version_number") or ""),
                    filename=_safe_filename(str(chosen.get("filename") or "mod.jar")),
                    url=str(chosen.get("url") or ""),
                    sha512=str((chosen.get("hashes") or {}).get("sha512") or ""),
                    game_versions=tuple(raw.get("game_versions") or ()),
                    loaders=tuple(raw.get("loaders") or ()),
                    dependencies=tuple(dependencies),
                    version_type=str(raw.get("version_type") or ""),
                    published=str(raw.get("date_published") or ""),
                )
            )
        # Modrinth returns versions newest-first; keep that order.
        return versions

    def modrinth_dependencies(
        self, project_id: str, mc_version: str, loader: str
    ) -> list[MarketDependency]:
        versions = self.modrinth_versions(project_id, mc_version, loader)
        if not versions:
            return []
        result: list[MarketDependency] = []
        for dep in versions[0].dependencies:
            if dep.dependency_type != "required":
                continue
            try:
                name = self.modrinth_project(dep.project_id).name
            except MarketError:
                name = "зависимость"
            result.append(
                MarketDependency(
                    project_id=dep.project_id,
                    version_id=dep.version_id,
                    dependency_type=dep.dependency_type,
                    name=name,
                )
            )
        return result

    def download_file(
        self,
        url: str,
        mods_dir: Path,
        filename: str,
        *,
        sha512: str = "",
        progress: Progress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        mods_dir.mkdir(parents=True, exist_ok=True)
        target = mods_dir / _safe_filename(filename)
        if target.is_file():
            return target
        disabled = target.with_name(target.name + ".disabled")
        if disabled.is_file():
            disabled.rename(target)
            return target
        temp = target.with_name(target.name + ".part")
        digest = hashlib.sha512()
        downloaded = 0
        started = time.monotonic()
        try:
            with requests.get(
                url,
                headers=HTTP_HEADERS,
                proxies=self.proxies,
                stream=True,
                timeout=(15, 120),
            ) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or 0)
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        _check_cancel(cancel_event)
                        if not chunk:
                            continue
                        handle.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        if progress and total:
                            percent = min(95, int(downloaded * 85 / total) + 5)
                            progress(
                                percent,
                                f"Загрузка {target.name}",
                                f"{downloaded / 1024 / 1024:.1f} МБ · "
                                f"{downloaded / 1024 / 1024 / max(0.25, time.monotonic() - started):.1f} МБ/с",
                            )
            _check_cancel(cancel_event)
            if sha512 and digest.hexdigest().lower() != sha512.lower():
                raise MarketError("Контрольная сумма файла не совпала.")
            temp.replace(target)
            return target
        except requests.RequestException as exc:
            raise MarketError(f"Не удалось скачать файл: {exc}") from exc
        finally:
            temp.unlink(missing_ok=True)

    def install_modrinth_content(
        self,
        instance: Instance,
        project_id: str,
        category: str = "mod",
        *,
        progress: Progress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> InstallOutcome:
        outcome = InstallOutcome()
        project = self.modrinth_project(project_id)
        versions = self.modrinth_all_versions(project_id)
        matching = [
            version
            for version in versions
            if not version.game_versions or instance.version in version.game_versions
        ]
        if not matching:
            raise MarketError(
                f"Для {project.name} нет версии под Minecraft {instance.version}."
            )
        version = matching[0]
        folder = {
            "mod": "mods",
            "resourcepack": "resourcepacks",
            "shader": "shaderpacks",
            "map": "saves",
        }.get(category, "mods")
        _emit(progress, 20, f"Установка {project.name}", version.filename)
        path = self.download_file(
            version.url,
            instance.path / folder,
            version.filename,
            sha512=version.sha512,
            progress=progress,
            cancel_event=cancel_event,
        )
        outcome.paths.append(path)
        if category == "mod":
            record_installed_mod(
                instance,
                name=project.name,
                version=version.version_number,
                source="modrinth",
                filename=path.name,
                project_id=project.id,
            )
        _emit(progress, 100, "Установлено", project.name)
        return outcome

    def install_modrinth(
        self,
        instance: Instance,
        project_id: str,
        *,
        include_dependencies: bool = True,
        progress: Progress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> InstallOutcome:
        outcome = InstallOutcome()
        self._install_modrinth_tree(
            instance,
            project_id,
            outcome,
            include_dependencies,
            progress,
            cancel_event,
            set(),
            0,
        )
        _emit(progress, 100, "Установлено", instance.name)
        return outcome

    def _install_modrinth_tree(
        self,
        instance: Instance,
        project_id: str,
        outcome: InstallOutcome,
        include_dependencies: bool,
        progress: Progress | None,
        cancel_event: threading.Event | None,
        seen: set[str],
        depth: int,
    ) -> None:
        if project_id in seen or depth > 3:
            return
        seen.add(project_id)
        _check_cancel(cancel_event)
        project = self.modrinth_project(project_id)
        versions = self.modrinth_versions(project_id, instance.version, instance.loader)
        if not versions:
            raise MarketError(
                f"Для {project.name} нет версии под Minecraft {instance.version} "
                f"({instance.loader})."
            )
        version = versions[0]
        _emit(progress, 5 + depth * 5, f"Установка {project.name}", version.filename)
        mods_dir = instance.path / "mods"
        path = self.download_file(
            version.url,
            mods_dir,
            version.filename,
            sha512=version.sha512,
            progress=progress,
            cancel_event=cancel_event,
        )
        outcome.paths.append(path)
        record_installed_mod(
            instance,
            name=project.name,
            version=version.version_number,
            source="modrinth",
            filename=path.name,
            project_id=project.id,
        )
        if not include_dependencies:
            return
        for dependency in version.dependencies:
            if dependency.dependency_type != "required":
                continue
            try:
                dependency_project = self.modrinth_project(dependency.project_id)
            except MarketError:
                outcome.skipped.append("неизвестная зависимость")
                continue
            outcome.dependencies.append(dependency_project.name)
            self._install_modrinth_tree(
                instance,
                dependency.project_id,
                outcome,
                include_dependencies,
                progress,
                cancel_event,
                seen,
                depth + 1,
            )

    def install_modrinth_spec(
        self,
        instance: Instance,
        name: str,
        version: str,
        *,
        progress: Progress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> InstallOutcome:
        query = name.replace("-", " ").strip()
        projects = self.search_modrinth(query, instance.version, instance.loader, limit=10)
        if not projects:
            raise MarketError(f"Мод «{name}» не найден на Modrinth.")
        project = projects[0]
        versions = self.modrinth_versions(project.id, instance.version, instance.loader)
        chosen = None
        for candidate in versions:
            if version and (
                version.lower() in candidate.version_number.lower()
                or candidate.version_number.lower() in version.lower()
            ):
                chosen = candidate
                break
        if chosen is None and versions:
            chosen = versions[0]
        if chosen is None:
            raise MarketError(f"Для «{name}» нет подходящей версии.")
        path = self.download_file(
            chosen.url,
            instance.path / "mods",
            chosen.filename,
            sha512=chosen.sha512,
            progress=progress,
            cancel_event=cancel_event,
        )
        record_installed_mod(
            instance,
            name=project.name,
            version=chosen.version_number,
            source="modrinth",
            filename=path.name,
            project_id=project.id,
        )
        return InstallOutcome(paths=[path])

    # ------------------------------------------------------------- curseforge
    def search_curseforge(
        self,
        query: str,
        mc_version: str,
        loader: str,
        *,
        offset: int = 0,
        limit: int = 20,
        class_id: int = 6,
    ) -> list[MarketProject]:
        key = self.curseforge_key
        if not key:
            raise MarketKeyMissing("CurseForge временно недоступен.")
        loader_id = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}.get(loader)
        params: dict[str, Any] = {
            "gameId": 432,
            "classId": class_id,
            "searchFilter": query,
            "gameVersion": mc_version,
            "index": offset,
            "pageSize": limit,
            "sortField": 2,
            "sortOrder": "desc",
        }
        if loader_id:
            params["modLoaderType"] = loader_id
        payload = self._json(
            f"{CURSEFORGE_API}/mods/search",
            params=params,
            headers={"x-api-key": key},
        )
        rows = payload.get("data", []) if isinstance(payload, Mapping) else []
        projects: list[MarketProject] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            authors = row.get("authors") or []
            author = str(authors[0].get("name")) if authors and isinstance(authors[0], Mapping) else "CurseForge"
            logo = row.get("logo") or {}
            projects.append(
                MarketProject(
                    id=str(row.get("id") or ""),
                    slug=str(row.get("slug") or ""),
                    name=str(row.get("name") or "Без названия"),
                    author=author,
                    description=str(row.get("summary") or ""),
                    icon_url=str(logo.get("thumbnailUrl") or logo.get("url") or "") if isinstance(logo, Mapping) else "",
                    downloads=int(row.get("downloadCount") or 0),
                    source="curseforge",
                    raw=row,
                )
            )
        return projects

    def install_curseforge(
        self,
        instance: Instance,
        project: MarketProject,
        *,
        progress: Progress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> InstallOutcome:
        files = project.raw.get("latestFiles") or []
        chosen = None
        for item in files:
            if isinstance(item, Mapping) and item.get("downloadUrl"):
                chosen = item
                break
        if chosen is None:
            raise MarketError(
                "CurseForge не выдал прямую ссылку на файл. "
                "Скачайте мод на сайте CurseForge."
            )
        path = self.download_file(
            str(chosen["downloadUrl"]),
            instance.path / "mods",
            str(chosen.get("fileName") or f"{project.slug}.jar"),
            progress=progress,
            cancel_event=cancel_event,
        )
        record_installed_mod(
            instance,
            name=project.name,
            version=str(chosen.get("displayName") or ""),
            source="curseforge",
            filename=path.name,
            project_id=project.id,
        )
        _emit(progress, 100, "Установлено", project.name)
        return InstallOutcome(paths=[path])



