"""Modrinth and CurseForge integration for the Fionix marketplace.

The module is UI-agnostic: workers call it from a QThread and the market page
renders the resulting dataclasses. CurseForge is routed through the Fionix
Cloudflare Worker, which injects its server-side API key; the launcher never
sends ``x-api-key`` itself.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import connection as urllib3_connection
from urllib3.util.retry import Retry

from src.core.async_download import DownloadCancelled, DownloadItem, download_many_sync

try:
    # curl_cffi impersonates Chrome's TLS/HTTP2 fingerprint, which is required
    # for the Cloudflare Worker from some Windows/Python environments.
    for _base in (
        Path(getattr(sys, "_MEIPASS", "") or ""),
        Path(__file__).resolve().parents[2],
        Path(__file__).resolve().parents[2] / ".deps",
    ):
        _libs = _base / "curl_cffi.libs"
        if _libs.is_dir():
            try:
                os.add_dll_directory(str(_libs))
            except OSError:
                pass
    from curl_cffi import requests as curl_requests
except Exception:  # optional fallback
    curl_requests = None
from src.core.exporter import record_installed_mod
from src.core.launcher import Instance, InstallCancelled, LauncherError

from config import CURSEFORGE_API_KEY

logger = logging.getLogger(__name__)


def _curseforge_endpoint() -> str:
    """Адрес прокси-воркера CurseForge из ``config.py``.

    В публичном репозитории значение пустое: каждый разворачивает свой
    воркер (см. INSTRUCTIONS.md). Без него вкладка CurseForge отключена,
    а Modrinth продолжает работать.
    """
    raw = str(CURSEFORGE_API_KEY or "").strip().rstrip("/")
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    if not raw.endswith("/v1"):
        raw += "/v1"
    return raw

MODRINTH_API = "https://api.modrinth.com/v2"
CURSEFORGE_API = _curseforge_endpoint()
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

Progress = Callable[[int, str, str], None]


class _IPv4HTTPAdapter(HTTPAdapter):
    """HTTPAdapter that applies IPv4/keepalive socket options."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        super().init_poolmanager(
            connections,
            maxsize,
            block=block,
            socket_options=[
                (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
                (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
            ],
            **pool_kwargs,
        )


def create_resilient_session() -> requests.Session:
    """Build a retrying IPv4-only session for CurseForge requests."""
    urllib3_connection.allowed_gai_family = lambda: socket.AF_INET
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = _IPv4HTTPAdapter(
        pool_connections=10,
        pool_maxsize=10,
        max_retries=retry,
    )
    session = requests.Session()
    session.trust_env = False
    session.headers.update(HTTP_HEADERS)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


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
    sha1: str = ""
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
        self.session = create_resilient_session()
        self.cf_session = None
        if curl_requests is not None:
            try:
                self.cf_session = curl_requests.Session(
                    impersonate="chrome120"
                )
            except Exception:
                logger.warning(
                    "curl_cffi session could not be created", exc_info=True
                )

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

    @staticmethod
    def _cf(path: str) -> str:
        """Полный URL прокси-воркера CurseForge; без него — понятная ошибка."""
        if not CURSEFORGE_API:
            raise MarketKeyMissing(
                "CurseForge не настроен: укажите адрес воркера "
                "(CURSEFORGE_API_KEY) в config.py."
            )
        return f"{CURSEFORGE_API}{path}"

    def _cf_debug(self, message: str) -> None:
        """Append network diagnostics to ``%APPDATA%/Fionix/cf_debug.log``."""
        try:
            data_dir = Path(getattr(self.config, "data_dir", "") or ".")
            path = data_dir / "cf_debug.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {message}\n"
                )
        except OSError:
            logger.debug("Could not write cf_debug.log", exc_info=True)

    def _cf_get(self, url, *, params, headers, timeout):
        """Cloudflare-compatible request via Chrome TLS impersonation."""
        last_error: Exception | None = None
        retry_statuses = {429, 500, 502, 503, 504}
        for attempt in range(1, 5):
            try:
                response = self.cf_session.get(
                    url,
                    params=params,
                    headers=headers,
                    proxies=self.proxies,
                    timeout=timeout,
                )
                if response.status_code not in retry_statuses or attempt == 4:
                    return response
                self._cf_debug(
                    f"RETRY STATUS {response.status_code} attempt {attempt}"
                )
            except Exception as exc:
                last_error = exc
                self._cf_debug(
                    f"CF GET ERROR {type(exc).__name__} attempt {attempt}: {exc}"
                )
                if self.proxies:
                    try:
                        response = self.cf_session.get(
                            url,
                            params=params,
                            headers=headers,
                            proxies={},
                            timeout=timeout,
                        )
                        if response.status_code not in retry_statuses or attempt == 4:
                            return response
                    except Exception as direct_exc:
                        last_error = direct_exc
                        self._cf_debug(
                            f"CF DIRECT ERROR {type(direct_exc).__name__}: "
                            f"{direct_exc}"
                        )
            if attempt < 4:
                time.sleep(backoff := (1, 2, 4)[attempt - 1])
                self._cf_debug(f"RETRY attempt {attempt + 1} after {backoff}s")
        if last_error is not None:
            raise last_error
        raise MarketError("CurseForge не ответил после 4 попыток.")

    def _json(self, url: str, *, params: Mapping[str, Any] | None = None,
              headers: Mapping[str, str] | None = None, timeout=(10, 60)) -> Any:
        merged = dict(HTTP_HEADERS)
        if headers:
            merged.update(headers)
        is_curseforge = bool(CURSEFORGE_API) and str(url).startswith(CURSEFORGE_API)
        prepared_url = requests.Request(
            "GET", url, params=params, headers=merged
        ).prepare().url
        if is_curseforge:
            print(f"[CurseForge] GET {prepared_url}", flush=True)
            self._cf_debug(f"GET {prepared_url}")

        try:
            if is_curseforge and self.cf_session is not None:
                response = self._cf_get(
                    url,
                    params=params,
                    headers=merged,
                    timeout=timeout,
                )
            else:
                response = self.session.get(
                    url,
                    params=params,
                    headers=merged,
                    proxies=self.proxies,
                    timeout=timeout,
                )
        except requests.exceptions.Timeout as exc:
            if is_curseforge:
                self._cf_debug(
                    f"TIMEOUT {type(exc).__name__} {prepared_url}: {exc}"
                )
                print(
                    "Сработал таймаут, попытка повторится",
                    flush=True,
                )
            logger.warning(
                "Сработал таймаут, попытка повторится: %s", exc
            )
            raise
        except requests.exceptions.RequestException as exc:
            if is_curseforge:
                self._cf_debug(
                    f"ERROR {type(exc).__name__} {prepared_url}: {exc}"
                )
                print(f"[CurseForge] ERROR {prepared_url}: {exc}", flush=True)
                logger.warning("CurseForge connection failed: %s", exc)
                # A configured global proxy may be dead; the Worker itself is
                # reachable directly, so retry the request without it.
                if self.proxies:
                    try:
                        response = self.session.get(
                            url,
                            params=params,
                            headers=merged,
                            proxies={},
                            timeout=timeout,
                        )
                    except requests.exceptions.Timeout:
                        self._cf_debug(
                            f"RETRY TIMEOUT {prepared_url}"
                        )
                        raise
                    except requests.exceptions.RequestException as retry_exc:
                        self._cf_debug(
                            f"RETRY ERROR {type(retry_exc).__name__} "
                            f"{prepared_url}: {retry_exc}"
                        )
                        raise MarketError(
                            f"Нет связи с CurseForge: {retry_exc}"
                        ) from retry_exc
                else:
                    raise MarketError(
                        f"Нет связи с CurseForge: {exc}"
                    ) from exc
            else:
                raise MarketError(
                    "Нет связи с интернетом или сервер недоступен."
                ) from exc
        except Exception as exc:
            if is_curseforge:
                self._cf_debug(
                    f"CF ERROR {type(exc).__name__} {prepared_url}: {exc}"
                )
                if "Timeout" in type(exc).__name__:
                    logger.warning("Сработал таймаут, попытка повторится")
                raise MarketError(
                    f"Нет связи с CurseForge: {exc}"
                ) from exc
            raise

        if is_curseforge:
            body = response.text[:800].replace("\n", " ")
            self._cf_debug(
                f"STATUS {response.status_code} {prepared_url} BODY {body}"
            )
            print(
                f"[CurseForge] {response.status_code} {prepared_url}",
                flush=True,
            )
        if response.status_code == 403 and is_curseforge:
            raise MarketError("Cloudflare Worker отклонил запрос (403).")
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

    def curseforge_project(self, project_id: str) -> MarketProject:
        """Load full CurseForge project details (HTML body and screenshots)."""
        payload = self._json(self._cf(f"/mods/{int(project_id)}"))
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, Mapping):
            raise MarketError("Проект CurseForge не найден.")
        screenshots = [
            item
            for item in (data.get("screenshots") or ())
            if isinstance(item, Mapping)
        ]
        authors = data.get("authors") or []
        author = (
            str(authors[0].get("name"))
            if authors and isinstance(authors[0], Mapping)
            else "CurseForge"
        )
        latest = data.get("latestFiles") or []
        versions: list[str] = []
        loaders: list[str] = []
        for item in latest:
            if not isinstance(item, Mapping):
                continue
            for value in item.get("gameVersions") or ():
                if not isinstance(value, str):
                    continue
                if value.lower() in {"forge", "fabric", "quilt", "neoforge"}:
                    if value not in loaders:
                        loaders.append(value)
                elif not value.startswith(("Client", "Server")):
                    if value not in versions:
                        versions.append(value)
        body = str(data.get("description") or "")
        if not body:
            try:
                description_payload = self._json(
                    self._cf(f"/mods/{int(project_id)}/description")
                )
                body = str(
                    description_payload.get("data") or ""
                    if isinstance(description_payload, Mapping)
                    else ""
                )
            except MarketError:
                body = ""
        raw = dict(data)
        raw["screenshots"] = screenshots
        raw["gallery"] = screenshots
        return MarketProject(
            id=str(data.get("id") or project_id),
            slug=str(data.get("slug") or ""),
            name=str(data.get("name") or "Без названия"),
            author=author,
            description=str(data.get("summary") or ""),
            icon_url=str((data.get("logo") or {}).get("thumbnailUrl") or "")
            if isinstance(data.get("logo"), Mapping)
            else "",
            downloads=int(data.get("downloadCount") or 0),
            source="curseforge",
            body=body,
            game_versions=tuple(versions),
            loaders=tuple(loaders),
            raw=raw,
        )

    def curseforge_latest_file(self, project_id: int) -> Mapping[str, Any] | None:
        try:
            payload = self._json(self._cf(f"/mods/{project_id}"))
        except MarketError:
            return None
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, Mapping):
            return None
        files = data.get("latestFiles") or []
        return files[0] if files and isinstance(files[0], Mapping) else None

    def curseforge_file(self, project_id: int, file_id: int) -> Mapping[str, Any] | None:
        try:
            payload = self._json(
                self._cf(f"/mods/{project_id}/files/{file_id}")
            )
        except MarketError:
            return None
        data = payload.get("data") if isinstance(payload, Mapping) else None
        return data if isinstance(data, Mapping) else None

    def curseforge_versions(self, project_id: str) -> list[MarketVersion]:
        """Return CurseForge file versions without requiring a client API key."""
        try:
            payload = self._json(
                self._cf(f"/mods/{int(project_id)}/files"),
                params={"pageSize": 50},
            )
        except (MarketError, TypeError, ValueError):
            return []
        rows = payload.get("data", []) if isinstance(payload, Mapping) else []
        versions: list[MarketVersion] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            hashes = row.get("hashes") or []
            sha1 = ""
            if isinstance(hashes, list):
                sha1 = next(
                    (
                        str(item.get("value") or "")
                        for item in hashes
                        if isinstance(item, Mapping) and int(item.get("algo") or 0) == 1
                    ),
                    "",
                )
            game_versions = tuple(
                str(item)
                for item in (row.get("gameVersions") or ())
                if isinstance(item, str) and not item.startswith(("Client", "Server"))
            )
            dependencies = tuple(
                MarketDependency(
                    project_id=str(item.get("modId") or ""),
                    dependency_type=(
                        "required"
                        if int(item.get("relationType") or 0) == 3
                        else "optional"
                    ),
                )
                for item in (row.get("dependencies") or ())
                if isinstance(item, Mapping) and item.get("modId")
            )
            release_type = {1: "release", 2: "beta", 3: "alpha"}.get(
                int(row.get("releaseType") or 0), "release"
            )
            versions.append(
                MarketVersion(
                    id=str(row.get("id") or ""),
                    project_id=str(project_id),
                    name=str(row.get("displayName") or ""),
                    version_number=str(row.get("displayName") or row.get("id") or ""),
                    filename=_safe_filename(
                        str(row.get("fileName") or f"curseforge-{project_id}.jar")
                    ),
                    url=str(row.get("downloadUrl") or ""),
                    sha1=sha1,
                    game_versions=game_versions,
                    loaders=tuple(
                        item
                        for item in game_versions
                        if item.lower() in {"forge", "fabric", "quilt", "neoforge"}
                    ),
                    dependencies=dependencies,
                    version_type=release_type,
                    published=str(row.get("fileDate") or ""),
                )
            )
        return versions

    def curseforge_modpack_file(self, project: MarketProject) -> Mapping[str, Any] | None:
        files = project.raw.get("latestFiles") or []
        latest = next(
            (item for item in files if isinstance(item, Mapping) and item.get("downloadUrl")),
            None,
        )
        if latest is not None:
            return latest
        try:
            return self.curseforge_latest_file(int(project.id))
        except (MarketError, TypeError, ValueError):
            return None

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
        sha1: str = "",
        progress: Progress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        mods_dir.mkdir(parents=True, exist_ok=True)
        target = mods_dir / _safe_filename(filename)
        disabled = target.with_name(target.name + ".disabled")
        if disabled.is_file() and not target.exists():
            disabled.rename(target)
        try:
            return download_many_sync(
                [
                    DownloadItem(
                        url=url,
                        destination=target,
                        sha512=sha512,
                        sha1=sha1,
                    )
                ],
                progress=progress,
                cancel_event=cancel_event,
                proxy=(self.proxies or {}).get("https"),
            )[0]
        except DownloadCancelled as exc:
            raise InstallCancelled("Загрузка отменена.") from exc
        except Exception as exc:
            raise MarketError(f"Не удалось скачать файл: {exc}") from exc

    def download_files(
        self,
        items: list[DownloadItem],
        *,
        progress: Progress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[Path]:
        try:
            return download_many_sync(
                items,
                progress=progress,
                cancel_event=cancel_event,
                proxy=(self.proxies or {}).get("https"),
                limit=12,
            )
        except DownloadCancelled as exc:
            raise InstallCancelled("Загрузка отменена.") from exc
        except Exception as exc:
            raise MarketError(f"Не удалось скачать файлы: {exc}") from exc

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
        payload = self._json(self._cf("/mods/search"), params=params)
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
            try:
                chosen = self.curseforge_latest_file(int(project.id))
            except (MarketError, TypeError, ValueError):
                chosen = None
        if chosen is None:
            raise MarketError(
                "CurseForge не выдал прямую ссылку на файл. "
                "Скачайте мод на сайте CurseForge."
            )
        sha1 = ""
        for item in chosen.get("hashes") or ():
            if isinstance(item, Mapping) and int(item.get("algo") or 0) == 1:
                sha1 = str(item.get("value") or "")
                break
        path = self.download_file(
            str(chosen["downloadUrl"]),
            instance.path / "mods",
            str(chosen.get("fileName") or f"{project.slug}.jar"),
            sha1=sha1,
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



