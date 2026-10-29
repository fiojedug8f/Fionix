"""Minecraft installation, Java runtime management and game launching.

Everything that touches the network, the file system of an instance or the
Java process lives here.  The UI layer only orchestrates worker threads and
renders the signals emitted by :class:`GameSession`.

Core scope
-------------
* Vanilla, Fabric, Forge, NeoForge and Quilt instances in
  ``instances/<Loader>_<version>``.
* Automatically managed Temurin JRE plus optional global Java override.
* Per-instance ``instance_config.json`` with loader, RAM and Java settings.
* Content listing and ``.disabled`` toggles for mods, packs, shaders and maps.
* ZIP backups and optional curated optimization mod sets.
* Account-aware offline/Yggdrasil launch via ``minecraft-launcher-lib``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

import requests
from minecraft_launcher_lib import command as mc_command
from minecraft_launcher_lib import install as mc_install
from minecraft_launcher_lib import mod_loader as mc_mod_loader
from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal

from src import __version__
from src.core.async_download import DownloadItem, download_many_sync
from src.core.config_manager import ConfigManager

logger = logging.getLogger(__name__)

INSTANCE_METADATA = "instance_config.json"
LEGACY_INSTANCE_METADATA = "instance.json"
BMCLAPI_BASE = "https://bmclapi2.bangbang93.com"
MOJANG_VERSION_MANIFEST = f"{BMCLAPI_BASE}/mc/game/version_manifest_v2.json"
_MOJANG_MIRROR_HOSTS = {
    "launchermeta.mojang.com",
    "piston-meta.mojang.com",
    "libraries.minecraft.net",
    "resources.download.minecraft.net",
    "launcher.mojang.com",
}
OPTIFINE_DOWNLOADS = "https://optifine.net/downloads"
ADOPTIUM_API = "https://api.adoptium.net/v3/assets/latest/{major}/hotspot"
MODRINTH_API = "https://api.modrinth.com/v2"
HTTP_HEADERS = {"User-Agent": f"Fionix/{__version__} (Minecraft launcher)"}

LOADER_LABELS = {
    "vanilla": "Vanilla",
    "fabric": "Fabric",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "quilt": "Quilt",
    "optifine": "OptiFine",
}
LOADER_FOLDERS = {
    "vanilla": "Vanilla",
    "fabric": "Fabric",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "quilt": "Quilt",
    "optifine": "OptiFine",
}
LOADER_ICONS = {
    "vanilla": "cube",
    "fabric": "fabric",
    "forge": "forge",
    "neoforge": "neoforge",
    "quilt": "quilt",
    "optifine": "optifine",
}
SUPPORTED_AUTO_LOADERS = ("vanilla", "fabric", "forge", "neoforge", "quilt")
DISABLED_SUFFIX = ".disabled"


@dataclass(frozen=True, slots=True)
class ContentCategory:
    key: str
    title: str
    folder: str
    icon: str
    description: str


@dataclass(frozen=True, slots=True)
class ContentFile:
    path: Path
    name: str
    enabled: bool
    size: int
    is_dir: bool

    @property
    def display_name(self) -> str:
        return self.name[: -len(DISABLED_SUFFIX)] if not self.enabled else self.name


OPTIMIZATION_MODS = {
    "fabric": (
        ("sodium", "Sodium"),
        ("lithium", "Lithium"),
        ("ferrite-core", "FerriteCore"),
    ),
    "forge": (
        ("embeddium", "Embeddium"),
        ("oculus", "Oculus"),
    ),
}

CONTENT_CATEGORIES = {
    "mods": ContentCategory(
        key="mods",
        title="Моды",
        folder="mods",
        icon="puzzle",
        description="Модификации, меняющие игру",
    ),
    "texturepacks": ContentCategory(
        key="texturepacks",
        title="Текстурпаки",
        folder="resourcepacks",
        icon="image",
        description="Наборы текстур и ресурсов",
    ),
    "shaders": ContentCategory(
        key="shaders",
        title="Шейдеры",
        folder="shaderpacks",
        icon="shader",
        description="Красивое освещение и графика",
    ),
    "maps": ContentCategory(
        key="maps",
        title="Карты",
        folder="saves",
        icon="map",
        description="Готовые миры для исследования",
    ),
}

POPULAR_RELEASES = (
    "1.21.1",
    "1.21",
    "1.20.1",
    "1.16.5",
    "1.12.2",
)

FALLBACK_RELEASES = (
    "1.21.4",
    "1.21.3",
    "1.21.1",
    "1.21",
    "1.20.6",
    "1.20.4",
    "1.20.1",
    "1.19.4",
    "1.18.2",
    "1.16.5",
    "1.12.2",
)

ProgressCallback = Callable[[int, str, str], None]

_LIBRARY_RUNTIME_LOCK = threading.Lock()
_LIBRARY_MIRROR_LOCK = threading.Lock()
_BMCLAPI_AVAILABLE: bool | None = None
_BMCLAPI_CHECKED_AT = 0.0


class LauncherError(Exception):
    """An error with a message that can be shown directly to the user."""


class InstallCancelled(LauncherError):
    """Raised when the user cancels an installation or Java download."""


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VersionEntry:
    version: str
    release_time: datetime | None = None
    version_type: str = "release"


@dataclass(frozen=True, slots=True)
class JavaRuntime:
    path: Path
    major: int
    source: str
    version: str = ""

    @property
    def is_managed(self) -> bool:
        return self.source == "Temurin"


@dataclass
class Instance:
    """A self-contained Minecraft directory and its metadata."""

    path: Path
    version: str
    name: str
    created_at: str
    java_major: int = 17
    playtime_seconds: int = 0
    last_played_at: str | None = None
    loader: str = "vanilla"
    loader_version: str = ""
    launch_version: str = ""
    memory_mb: int | None = None
    java_path: str = ""
    icon_path: str = ""
    modpack_name: str = ""
    modpack_author: str = ""
    modpack_version: str = ""
    modpack_source: str = ""
    modpack_project_id: str = ""
    pending: bool = False
    schema_version: int = 2

    @property
    def metadata_path(self) -> Path:
        return self.path / INSTANCE_METADATA

    @property
    def legacy_metadata_path(self) -> Path:
        return self.path / LEGACY_INSTANCE_METADATA

    @property
    def folder_name(self) -> str:
        return self.path.name

    @property
    def effective_launch_version(self) -> str:
        return self.launch_version or self.version

    @property
    def minecraft_jar(self) -> Path:
        version = self.effective_launch_version
        return self.path / "versions" / version / f"{version}.jar"

    @property
    def loader_name(self) -> str:
        return LOADER_LABELS.get(self.loader, "Vanilla")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "name": self.name,
            "version": self.version,
            "loader": self.loader,
            "loader_version": self.loader_version,
            "launch_version": self.effective_launch_version,
            "created_at": self.created_at,
            "last_played_at": self.last_played_at,
            "playtime_seconds": max(0, int(self.playtime_seconds)),
            "java_major": max(8, int(self.java_major)),
            "memory_mb": int(self.memory_mb) if self.memory_mb else None,
            "java_path": self.java_path,
            "icon_path": self.icon_path,
            "modpack_name": self.modpack_name,
            "modpack_author": self.modpack_author,
            "modpack_version": self.modpack_version,
            "modpack_source": self.modpack_source,
            "modpack_project_id": self.modpack_project_id,
            "pending": bool(self.pending),
        }

    def save(self) -> None:
        _atomic_write_json(self.metadata_path, self.to_dict())
        if self.legacy_metadata_path.exists():
            self.legacy_metadata_path.unlink(missing_ok=True)

    def add_playtime(self, seconds: int) -> None:
        self.playtime_seconds = max(0, int(self.playtime_seconds) + max(0, int(seconds)))

    @classmethod
    def load(cls, path: Path) -> "Instance":
        metadata_path = path / INSTANCE_METADATA
        if not metadata_path.is_file():
            metadata_path = path / LEGACY_INSTANCE_METADATA
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LauncherError(f"Повреждён файл экземпляра: {metadata_path}") from exc
        if not isinstance(raw, Mapping):
            raise LauncherError(f"Некорректный файл экземпляра: {metadata_path}")

        version = str(raw.get("version", "")).strip()
        if not version:
            raise LauncherError(f"В файле экземпляра нет версии: {metadata_path}")

        def _integer(key: str, default: int, low: int, high: int) -> int:
            try:
                value = int(raw.get(key, default))
            except (TypeError, ValueError):
                value = default
            return max(low, min(high, value))

        loader = str(raw.get("loader") or "vanilla").strip().lower()
        if loader not in LOADER_LABELS:
            loader = "vanilla"

        created_at = str(raw.get("created_at") or _now_iso())
        last_played = raw.get("last_played_at")
        if last_played is not None and not isinstance(last_played, str):
            last_played = None

        memory_raw = raw.get("memory_mb")
        memory_mb: int | None
        try:
            memory_mb = max(1024, min(16384, int(memory_raw))) if memory_raw is not None else None
        except (TypeError, ValueError):
            memory_mb = None

        launch_version = str(raw.get("launch_version") or version)
        return cls(
            path=path,
            version=version,
            name=str(raw.get("name") or f"{LOADER_LABELS[loader]} {version}")[:80],
            created_at=created_at,
            java_major=_integer("java_major", 17, 8, 99),
            playtime_seconds=_integer("playtime_seconds", 0, 0, 10**9),
            last_played_at=last_played,
            loader=loader,
            loader_version=str(raw.get("loader_version") or "")[:64],
            launch_version=launch_version[:128],
            memory_mb=memory_mb,
            java_path=str(raw.get("java_path") or "")[:1024],
            icon_path=str(raw.get("icon_path") or "")[:2048],
            modpack_name=str(raw.get("modpack_name") or "")[:128],
            modpack_author=str(raw.get("modpack_author") or "")[:128],
            modpack_version=str(raw.get("modpack_version") or "")[:128],
            modpack_source=str(raw.get("modpack_source") or "")[:32],
            modpack_project_id=str(raw.get("modpack_project_id") or "")[:128],
            pending=bool(raw.get("pending", False)),
            schema_version=2,
        )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _safe_rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("Could not remove %s: %s", path, exc)


def format_playtime(seconds: int) -> str:
    """Format seconds as a human readable Russian duration."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        if minutes:
            return f"{hours} ч {minutes:02d} мин"
        return f"{hours} ч"
    if minutes:
        return f"{minutes} мин"
    if seconds:
        return f"{seconds} сек"
    return "0 мин"


def format_last_played(value: str | None) -> str:
    if not value:
        return "Ещё не запускался"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return "—"
    today = datetime.now().date()
    if moment.date() == today:
        return f"Сегодня, {moment:%H:%M}"
    if moment.year == today.year:
        return f"{moment:%d.%m}, {moment:%H:%M}"
    return f"{moment:%d.%m.%Y}"


def offline_uuid(username: str) -> str:
    """The same fake UUID format the vanilla launcher uses in offline mode."""
    digest = hashlib.md5(f"OfflinePlayer:{username}".encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest, version=3))


def validate_version_id(version: str) -> str:
    version = (version or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version):
        raise LauncherError("Некорректный идентификатор версии Minecraft.")
    return version


def normalize_loader(loader: str) -> str:
    loader = (loader or "vanilla").strip().lower()
    if loader not in LOADER_LABELS:
        raise LauncherError("Неизвестное ядро сборки.")
    return loader


def loader_label(loader: str) -> str:
    return LOADER_LABELS.get(normalize_loader(loader), "Vanilla")


def _instance_folder(version: str, loader: str = "vanilla") -> str:
    loader = normalize_loader(loader)
    return f"{LOADER_FOLDERS[loader]}_{validate_version_id(version)}"


def _major_from_version_name(version: str) -> int:
    """Fallback Java requirement for older manifests without javaVersion."""
    try:
        pieces = version.split("-")[0].split(".")
        if len(pieces) >= 2:
            major_minor = (int(pieces[0]), int(pieces[1]))
            if major_minor >= (1, 18):
                return 17
            if major_minor == (1, 17):
                return 16
    except (ValueError, IndexError):
        pass
    return 8


def _parse_release_time(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


@contextmanager
def _library_manages_no_java():
    """Prevent minecraft-launcher-lib from installing Mojang JRE per instance.

    Fionix keeps one shared Temurin runtime in ``%APPDATA%/Fionix/runtime``.
    ``install_minecraft_version()`` otherwise downloads a Mojang runtime into
    every instance, which would waste hundreds of megabytes per build.
    """

    with _LIBRARY_RUNTIME_LOCK:
        original = getattr(mc_install, "install_jvm_runtime", None)
        if original is None:
            yield
            return

        def _skip(*_args: Any, **_kwargs: Any) -> None:
            logger.debug("Skipping bundled Minecraft Java runtime download")

        mc_install.install_jvm_runtime = _skip  # type: ignore[attr-defined]
        try:
            yield
        finally:
            mc_install.install_jvm_runtime = original  # type: ignore[attr-defined]


def bmclapi_url(url: str) -> str:
    """Route a Mojang URL through BMCLAPI's actual resource paths."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    path = parsed.path
    if host == "resources.download.minecraft.net":
        path = "/assets" + path
    elif host == "libraries.minecraft.net":
        path = "/maven" + path
    elif host not in _MOJANG_MIRROR_HOSTS:
        return url
    return urlunsplit(
        ("https", "bmclapi2.bangbang93.com", path, parsed.query, "")
    )


def bmclapi_available() -> bool:
    """Probe BMCLAPI once and cache the result to avoid per-file timeouts."""
    global _BMCLAPI_AVAILABLE, _BMCLAPI_CHECKED_AT
    now = time.monotonic()
    if _BMCLAPI_AVAILABLE is not None and now - _BMCLAPI_CHECKED_AT < 600:
        return _BMCLAPI_AVAILABLE
    try:
        response = requests.head(
            MOJANG_VERSION_MANIFEST,
            timeout=(3, 5),
            allow_redirects=True,
            headers=HTTP_HEADERS,
        )
        _BMCLAPI_AVAILABLE = response.status_code < 500
    except requests.RequestException:
        _BMCLAPI_AVAILABLE = False
    _BMCLAPI_CHECKED_AT = now
    return bool(_BMCLAPI_AVAILABLE)


@contextmanager
def _bmclapi_mirror():
    """Patch minecraft-launcher-lib URL resolution for the current install."""
    with _LIBRARY_MIRROR_LOCK:
        from minecraft_launcher_lib import _helper as lib_helper

        original_download = lib_helper.download_file
        original_install_requests = getattr(mc_install, "requests", None)

        def mirrored_download(
            url,
            path,
            callback=None,
            sha1=None,
            lzma_compressed=False,
            session=None,
            minecraft_directory=None,
            overwrite=False,
        ):
            if lzma_compressed:
                return original_download(
                    bmclapi_url(str(url)),
                    path,
                    callback or {},
                    sha1=sha1,
                    lzma_compressed=True,
                    session=session,
                    minecraft_directory=minecraft_directory,
                    overwrite=overwrite,
                )
            target = Path(path)
            if not bmclapi_available():
                return original_download(
                    str(url),
                    path,
                    callback or {},
                    sha1=sha1,
                    session=session,
                    minecraft_directory=minecraft_directory,
                    overwrite=overwrite,
                )
            if target.is_file() and not overwrite:
                if not sha1:
                    return False
                import hashlib

                digest = hashlib.sha1()
                with target.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() == sha1:
                    return False
            try:
                download_many_sync(
                    [
                        DownloadItem(
                            url=bmclapi_url(str(url)),
                            destination=target,
                            sha1=str(sha1 or ""),
                        )
                    ],
                    read_timeout=8,
                )
            except Exception as exc:
                global _BMCLAPI_AVAILABLE, _BMCLAPI_CHECKED_AT
                _BMCLAPI_AVAILABLE = False
                _BMCLAPI_CHECKED_AT = time.monotonic()
                logger.warning("BMCLAPI download failed, falling back to Mojang: %s", exc)
                return original_download(
                    str(url),
                    path,
                    callback or {},
                    sha1=sha1,
                    session=session,
                    minecraft_directory=minecraft_directory,
                    overwrite=overwrite,
                )
            return True

        class _MirrorRequests:
            def __getattr__(self, name):
                return getattr(original_install_requests, name)

            def get(self, url, *args, **kwargs):
                kwargs.setdefault("timeout", (5, 10))
                try:
                    return original_install_requests.get(
                        bmclapi_url(str(url)), *args, **kwargs
                    )
                except requests.RequestException as exc:
                    global _BMCLAPI_AVAILABLE, _BMCLAPI_CHECKED_AT
                    _BMCLAPI_AVAILABLE = False
                    _BMCLAPI_CHECKED_AT = time.monotonic()
                    logger.warning(
                        "BMCLAPI request failed, retrying Mojang: %s", exc
                    )
                    return original_install_requests.get(
                        str(url), *args, **kwargs
                    )

        lib_helper.download_file = mirrored_download  # type: ignore[attr-defined]
        mc_install.download_file = mirrored_download  # type: ignore[attr-defined]
        if original_install_requests is not None:
            mc_install.requests = _MirrorRequests()  # type: ignore[attr-defined]
        try:
            yield
        finally:
            lib_helper.download_file = original_download  # type: ignore[attr-defined]
            mc_install.download_file = original_download  # type: ignore[attr-defined]
            if original_install_requests is not None:
                mc_install.requests = original_install_requests  # type: ignore[attr-defined]


def _hidden_process_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


# ---------------------------------------------------------------------------
# Launcher service
# ---------------------------------------------------------------------------


class LauncherService:
    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        self.data_dir = config.data_dir
        self.runtime_dir = self.data_dir / "runtime"
        self._release_cache: list[VersionEntry] | None = None
        self._java_lock = threading.Lock()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.set_instances_dir(self._configured_instances_dir())

    def _configured_instances_dir(self) -> Path:
        raw = str(self.config.get("instances_path", "") or "").strip()
        if raw:
            try:
                return Path(raw).expanduser()
            except (OSError, ValueError):
                logger.warning("Invalid instances path: %s", raw)
        return self.data_dir / "instances"

    def set_instances_dir(self, path: Path | str) -> Path:
        path = Path(path).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        self.instances_dir = path
        self.staging_dir = path / ".staging"
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        return path

    def reload_instances_dir(self) -> Path:
        return self.set_instances_dir(self._configured_instances_dir())

    # ------------------------------------------------------------- HTTP
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

    def _http_get(self, url: str, *, timeout: tuple[int, int] = (10, 30), **kwargs: Any):
        return requests.get(
            url,
            headers=HTTP_HEADERS,
            proxies=self.proxies,
            timeout=timeout,
            **kwargs,
        )

    # ------------------------------------------------------ version list
    def fallback_versions(self) -> list[VersionEntry]:
        return [VersionEntry(version=version) for version in FALLBACK_RELEASES]

    def merge_catalog(self, fetched: Iterable[VersionEntry]) -> list[VersionEntry]:
        """Latest releases plus the pinned versions shown in the picker."""
        entries: dict[str, VersionEntry] = {}
        ordered: list[VersionEntry] = []
        for entry in fetched:
            if entry.version not in entries:
                entries[entry.version] = entry
                ordered.append(entry)
        for version in POPULAR_RELEASES:
            if version not in entries:
                entries[version] = VersionEntry(version=version)
                ordered.append(entries[version])
        return ordered

    def default_catalog(self) -> list[VersionEntry]:
        return self.merge_catalog(self.fallback_versions())

    def fetch_release_versions(self, timeout: tuple[int, int] = (8, 15)) -> list[VersionEntry]:
        """Fetch the Mojang version manifest, newest releases first."""
        global _BMCLAPI_AVAILABLE, _BMCLAPI_CHECKED_AT
        official = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
        if bmclapi_available():
            logger.info("Fetching Minecraft version manifest via BMCLAPI")
            try:
                response = self._http_get(MOJANG_VERSION_MANIFEST, timeout=timeout)
                response.raise_for_status()
            except requests.RequestException as exc:
                logger.warning(
                    "BMCLAPI manifest failed, falling back to Mojang: %s", exc
                )
                _BMCLAPI_AVAILABLE = False
                _BMCLAPI_CHECKED_AT = time.monotonic()
                response = self._http_get(official, timeout=timeout)
                response.raise_for_status()
        else:
            response = self._http_get(official, timeout=timeout)
            response.raise_for_status()
        payload = response.json()
        raw_versions = payload.get("versions", []) if isinstance(payload, Mapping) else []
        entries: list[VersionEntry] = []
        valid_types = {"release", "snapshot", "old_beta", "old_alpha"}
        for raw in raw_versions:
            if not isinstance(raw, Mapping):
                continue
            kind = str(raw.get("type") or "release").lower()
            if kind not in valid_types:
                continue
            version = raw.get("id")
            if not isinstance(version, str):
                continue
            try:
                validate_version_id(version)
            except LauncherError:
                continue
            entries.append(
                VersionEntry(
                    version=version,
                    release_time=_parse_release_time(raw.get("releaseTime")),
                    version_type=kind,
                )
            )
        entries.sort(
            key=lambda entry: (
                entry.release_time.timestamp() if entry.release_time else 0.0
            ),
            reverse=True,
        )
        if not entries:
            raise LauncherError("Mojang вернул пустой список версий.")
        self._release_cache = entries
        return entries

    # ---------------------------------------------------------- instances
    def list_instances(self) -> list[Instance]:
        result: list[Instance] = []
        try:
            children = list(self.instances_dir.iterdir())
        except OSError as exc:
            logger.warning("Cannot read instances directory: %s", exc)
            return result

        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not (child / INSTANCE_METADATA).is_file() and not (
                child / LEGACY_INSTANCE_METADATA
            ).is_file():
                continue
            try:
                instance = Instance.load(child)
                if not (child / INSTANCE_METADATA).is_file():
                    logger.info("Migrating legacy instance metadata for %s", child.name)
                    instance.save()
                result.append(instance)
            except (LauncherError, OSError) as exc:
                logger.warning("Skipping invalid instance %s: %s", child, exc)
        result.sort(key=lambda instance: (instance.last_played_at or instance.created_at), reverse=True)
        return result

    def get_instance(self, folder_name: str) -> Instance | None:
        path = self.instances_dir / folder_name
        if not (path / INSTANCE_METADATA).is_file() and not (
            path / LEGACY_INSTANCE_METADATA
        ).is_file():
            return None
        try:
            return Instance.load(path)
        except LauncherError:
            return None

    def instance_for(self, version: str, loader: str = "vanilla") -> Instance | None:
        loader = normalize_loader(loader)
        return self.get_instance(_instance_folder(version, loader))

    def instance_for_version(self, version: str) -> Instance | None:
        """Backward-compatible lookup for the original vanilla instances."""
        return self.instance_for(version, "vanilla")

    # ------------------------------------------------------------- install
    def create_instance(
        self,
        version: str,
        loader: str = "vanilla",
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
        *,
        optimize: bool = False,
        display_name: str | None = None,
        instance_folder: str | None = None,
        replace_existing: bool = False,
    ) -> Instance:
        version = validate_version_id(version)
        loader = normalize_loader(loader)
        label = loader_label(loader)

        if loader == "optifine":
            base = self.create_instance(
                version,
                "vanilla",
                progress=progress,
                cancel_event=cancel_event,
                optimize=optimize,
                display_name=display_name or f"OptiFine {version}",
                instance_folder=instance_folder,
                replace_existing=replace_existing,
            )
            self._install_optifine(base, progress, cancel_event)
            return base
        if loader not in SUPPORTED_AUTO_LOADERS:
            raise LauncherError(f"Установка ядра {label} пока не поддерживается.")

        if instance_folder is None:
            existing = self.instance_for(version, loader)
            if existing is not None:
                self._emit(progress, 100, "Экземпляр уже установлен", existing.name)
                return existing

        # Resolve the loader before touching the network for game files.
        mod_loader = None
        loader_version = ""
        if loader != "vanilla":
            self._emit(progress, 0, f"Проверка {label}", f"Minecraft {version}")
            try:
                mod_loader = mc_mod_loader.get_mod_loader(loader)
                if not mod_loader.is_minecraft_version_supported(version):
                    raise LauncherError(
                        f"{label} не поддерживает Minecraft {version}. "
                        "Выберите другую версию или ядро."
                    )
                loader_version = mod_loader.get_latest_loader_version(version)
            except LauncherError:
                raise
            except Exception as exc:
                logger.exception("%s preflight failed", label)
                raise LauncherError(
                    f"Не удалось получить данные {label} для Minecraft {version}. "
                    "Проверьте подключение к интернету."
                ) from exc

        folder = _instance_folder(version, loader)
        if instance_folder:
            safe_folder = "".join(
                ch if ch.isalnum() or ch in "-_" else "_" for ch in instance_folder
            ).strip("_")[:60]
            if not safe_folder:
                safe_folder = f"Modpack_{uuid.uuid4().hex[:8]}"
            folder = safe_folder
        final_path = self.instances_dir / folder
        if instance_folder and not replace_existing:
            counter = 2
            while final_path.exists():
                final_path = self.instances_dir / f"{folder}_{counter}"
                counter += 1
        staging_path = self.staging_dir / f"{folder}-{uuid.uuid4().hex}"
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        staging_path.mkdir(parents=True, exist_ok=True)

        self._emit(progress, 0, "Подготовка установки", f"Minecraft {version} · {label}")
        base_span = 70 if loader != "vanilla" else 99

        def base_progress(percent: int, title: str, detail: str) -> None:
            self._emit(progress, int(percent * base_span / 100), title, detail)

        callback = self._build_install_callback(base_progress, cancel_event)
        try:
            with _library_manages_no_java(), _bmclapi_mirror():
                mc_install.install_minecraft_version(version, str(staging_path), callback=callback)
                self._raise_if_cancelled(cancel_event)
                java_major = self._read_java_major(staging_path, version)
                launch_version = version

                if loader != "vanilla" and mod_loader is not None:
                    self._emit(progress, 71, f"Подготовка {label}", "Проверяем Java")
                    java = self.ensure_java(
                        java_major,
                        progress=lambda p, _t, d: self._emit(
                            progress, 72 + int(p * 10 / 100), "Подготовка Java", d
                        ),
                        cancel_event=cancel_event,
                    )
                    self._raise_if_cancelled(cancel_event)
                    self._emit(progress, 82, f"Установка {label}", "Загрузка установщика")

                    try:
                        loader_cb = self._build_loader_callback(
                            progress, cancel_event, label
                        )
                        launch_version = mod_loader.install(
                            version,
                            str(staging_path),
                            loader_version=loader_version,
                            callback=loader_cb,
                            java=str(self._installer_java(java)),
                        )
                    except LauncherError:
                        raise
                    except Exception as exc:
                        logger.exception("%s installation failed", label)
                        raise LauncherError(
                            f"Не удалось установить {label} для Minecraft {version}. "
                            "Проверьте подключение к интернету и лог Fionix."
                        ) from exc

                    if not launch_version:
                        raise LauncherError(f"{label} установлен без идентификатора версии.")
                    self._raise_if_cancelled(cancel_event)
                    self._emit(progress, 99, f"{label} установлен", "Завершаем настройку")

            # Standard folders are created upfront so content management and
            # backups work even before the player installs anything.
            for folder_name in ("mods", "resourcepacks", "shaderpacks", "saves", "config"):
                (staging_path / folder_name).mkdir(exist_ok=True)

            self._raise_if_cancelled(cancel_event)
            instance = Instance(
                path=staging_path,
                version=version,
                name=(display_name or f"{label} {version}")[:80],
                created_at=_now_iso(),
                java_major=java_major,
                loader=loader,
                loader_version=loader_version,
                launch_version=launch_version,
                memory_mb=self.config.memory_mb,
            )
            if optimize and loader in OPTIMIZATION_MODS:
                self.install_optimization(
                    instance,
                    progress=lambda p, t, d: self._emit(
                        progress, 89 + int(p * 10 / 100), t, d
                    ),
                    cancel_event=cancel_event,
                )
            instance.save()

            # Only touch the final directory once the download is complete.
            if final_path.exists():
                logger.info("Replacing incomplete instance directory %s", final_path)
                _safe_rmtree(final_path)
            os.replace(staging_path, final_path)
            instance.path = final_path

            self._emit(progress, 100, "Готово", f"{instance.name} создан")
            logger.info(
                "Installed %s %s into %s", loader, version, final_path
            )
            return instance
        except InstallCancelled:
            _safe_rmtree(staging_path)
            self._emit(progress, 0, "Установка отменена", "")
            raise
        except Exception as exc:
            _safe_rmtree(staging_path)
            if isinstance(exc, LauncherError):
                raise
            logger.exception("Minecraft installation failed")
            raise LauncherError(
                "Не удалось установить Minecraft. Проверьте подключение к интернету "
                "и свободное место на диске."
            ) from exc

    def _install_optifine(
        self,
        instance: Instance,
        progress: ProgressCallback | None,
        cancel_event: threading.Event | None,
    ) -> None:
        """Download the official OptiFine installer and run it through Java."""
        self._raise_if_cancelled(cancel_event)
        self._emit(progress, 91, "OptiFine", "Ищем официальный установщик")
        try:
            page = self._http_get(OPTIFINE_DOWNLOADS, timeout=(10, 25))
            page.raise_for_status()
            matches = re.findall(
                r"adloadx\?f=(OptiFine_[^\"'&<>]+\.jar)", page.text, re.IGNORECASE
            )
            candidates = [
                name
                for name in dict.fromkeys(matches)
                if f"_{instance.version}_" in name or name.endswith(f"_{instance.version}.jar")
            ]
            if not candidates:
                raise LauncherError(
                    f"На optifine.net пока нет установщика для Minecraft {instance.version}."
                )
            filename = candidates[0]
            download_page = self._http_get(
                f"https://optifine.net/adloadx?f={filename}", timeout=(10, 30)
            )
            download_page.raise_for_status()
            if download_page.content[:2] == b"PK":
                payload = download_page.content
            else:
                links = re.findall(
                    r"downloadx\?f=([^\"'&<>]+)", download_page.text, re.IGNORECASE
                )
                if not links:
                    raise LauncherError("optifine.net не выдал ссылку на скачивание.")
                response = self._http_get(
                    f"https://optifine.net/downloadx?f={links[0]}",
                    timeout=(10, 60),
                    stream=True,
                )
                response.raise_for_status()
                chunks = []
                for chunk in response.iter_content(1024 * 256):
                    self._raise_if_cancelled(cancel_event)
                    if chunk:
                        chunks.append(chunk)
                payload = b"".join(chunks)
            self._raise_if_cancelled(cancel_event)
            installer = instance.path / f"OptiFine_{instance.version}.jar"
            installer.write_bytes(payload)
            self._emit(progress, 95, "OptiFine", "Запускаем официальный установщик")
            java = self.ensure_java(instance.java_major, cancel_event=cancel_event)
            java_exe = self._installer_java(java)
            result = subprocess.run(
                [str(java_exe), "-jar", str(installer), "--install"],
                cwd=str(instance.path),
                capture_output=True,
                text=True,
                timeout=240,
                **_hidden_process_kwargs(),
            )
            self._raise_if_cancelled(cancel_event)
            if result.returncode == 0:
                versions_dir = instance.path / "versions"
                folders = sorted(
                    (
                        child.name
                        for child in versions_dir.iterdir()
                        if child.is_dir() and "optifine" in child.name.lower()
                    ),
                    reverse=True,
                ) if versions_dir.is_dir() else []
                if folders:
                    instance.launch_version = folders[0]
            else:
                # Some builds do not accept CLI flags.  Keep the official jar
                # as a Forge/Fabric mod so the user can still launch it.
                mods = instance.path / "mods"
                mods.mkdir(parents=True, exist_ok=True)
                shutil.copy2(installer, mods / installer.name)
                logger.warning("OptiFine installer returned %s; copied jar to mods", result.returncode)
            installer.unlink(missing_ok=True)
            instance.loader = "optifine"
            instance.name = f"OptiFine {instance.version}"
            instance.save()
            self._emit(progress, 100, "OptiFine установлен", instance.name)
        except LauncherError:
            raise
        except Exception as exc:
            logger.exception("OptiFine installation failed")
            raise LauncherError(
                f"Не удалось установить OptiFine для {instance.version}: {exc}"
            ) from exc

    def create_vanilla_instance(
        self,
        version: str,
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Instance:
        """Backward-compatible wrapper for the original vanilla API."""
        return self.create_instance(
            version, "vanilla", progress=progress, cancel_event=cancel_event
        )

    def _build_loader_callback(
        self,
        progress: ProgressCallback | None,
        cancel_event: threading.Event | None,
        label: str,
    ) -> dict[str, Callable[[Any], None]]:
        state: dict[str, Any] = {"detail": "", "maximum": 0, "last": 81}

        def check() -> None:
            self._raise_if_cancelled(cancel_event)

        def emit_title(detail: str = "") -> None:
            self._emit(progress, int(state["last"]), f"Установка {label}", detail)

        def set_status(status: str) -> None:
            check()
            state["detail"] = status
            emit_title(status)

        def set_max(maximum: int) -> None:
            check()
            state["maximum"] = max(0, int(maximum))

        def set_progress(current: int) -> None:
            check()
            maximum = int(state["maximum"])
            ratio = 0.0 if maximum <= 0 else min(1.0, max(0.0, current / maximum))
            percent = 82 + int(17 * ratio)
            if percent > int(state["last"]):
                state["last"] = percent
                emit_title(str(state["detail"]))

        return {"setStatus": set_status, "setMax": set_max, "setProgress": set_progress}

    def _installer_java(self, java: JavaRuntime) -> Path:
        if java.path.name.lower() == "javaw.exe":
            candidate = java.path.with_name("java.exe")
            if candidate.is_file():
                return candidate
        return java.path

    def _build_install_callback(
        self,
        progress: ProgressCallback | None,
        cancel_event: threading.Event | None,
    ) -> dict[str, Callable[[Any], None]]:
        state: dict[str, Any] = {
            "title": "Подготовка установки",
            "detail": "",
            "base": 0,
            "span": 5,
            "maximum": 0,
            "last_percent": -1,
        }

        def check() -> None:
            self._raise_if_cancelled(cancel_event)

        def set_status(status: str) -> None:
            check()
            old_title = str(state["title"])
            old_base = int(state["base"])
            state["detail"] = ""
            if status.startswith("Download Libraries"):
                state.update(title="Скачивание библиотек", base=5, span=40, maximum=0)
            elif status.startswith("Download Assets"):
                state.update(title="Скачивание ресурсов игры", base=45, span=45, maximum=0)
            elif status.startswith("Install java runtime"):
                return
            elif status.startswith("Installation complete"):
                state.update(title="Завершение установки", base=90, span=9)
                self._emit(progress, 99, "Завершение установки", "")
                return
            elif status.startswith("Download "):
                state["detail"] = Path(status[len("Download ") :]).name
            else:
                state["detail"] = status

            # File-level status messages are very frequent.  Only move the bar
            # when a new installation phase begins, not for every asset.
            if str(state["title"]) != old_title or int(state["base"]) != old_base:
                self._emit(
                    progress,
                    int(state["base"]),
                    str(state["title"]),
                    str(state["detail"]),
                )

        def set_max(maximum: int) -> None:
            check()
            state["maximum"] = max(0, int(maximum))

        def set_progress(current: int) -> None:
            check()
            base = int(state["base"])
            span = int(state["span"])
            maximum = int(state["maximum"])
            ratio = 0.0 if maximum <= 0 else min(1.0, max(0.0, current / maximum))
            percent = int(round(base + span * ratio))
            percent = max(0, min(100, percent))
            if percent != state["last_percent"]:
                state["last_percent"] = percent
                self._emit(progress, percent, str(state["title"]), str(state["detail"]))

        return {"setStatus": set_status, "setMax": set_max, "setProgress": set_progress}

    def _read_java_major(self, minecraft_dir: Path, version: str) -> int:
        json_path = minecraft_dir / "versions" / version / f"{version}.json"
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _major_from_version_name(version)
        java_version = data.get("javaVersion") if isinstance(data, Mapping) else None
        if isinstance(java_version, Mapping):
            try:
                major = int(java_version.get("majorVersion", 0))
                if 8 <= major <= 99:
                    return major
            except (TypeError, ValueError):
                pass
        return _major_from_version_name(version)

    # ---------------------------------------------------------------- Java
    def managed_java(self, major: int) -> JavaRuntime | None:
        target = self.runtime_dir / f"temurin-{int(major)}"
        metadata = target / ".fionix-runtime.json"
        if metadata.is_file():
            try:
                raw = json.loads(metadata.read_text(encoding="utf-8"))
                relative = Path(str(raw.get("launch_executable", "")))
                candidate = (target / relative).resolve()
                if target.resolve() in candidate.parents and candidate.is_file():
                    return JavaRuntime(
                        path=candidate,
                        major=int(raw.get("major", major)),
                        source=str(raw.get("source", "Temurin")),
                        version=str(raw.get("version", "")),
                    )
            except (OSError, ValueError, json.JSONDecodeError, TypeError):
                logger.warning("Ignoring invalid Java metadata at %s", metadata)

        java = self._find_runtime_executable(target)
        if java is not None:
            return JavaRuntime(path=java, major=int(major), source="Temurin")
        return None

    def _find_runtime_executable(self, root: Path) -> Path | None:
        if not root.is_dir():
            return None
        javaw = sorted(root.rglob("bin/javaw.exe"))
        if javaw:
            return javaw[0]
        java = sorted(root.rglob("bin/java.exe"))
        if java:
            return java[0]
        java = sorted(root.rglob("bin/java"))
        if java:
            return java[0]
        return None

    def _find_java_for_probe(self, root: Path) -> Path | None:
        if not root.is_dir():
            return None
        for pattern in ("bin/java.exe", "bin/java"):
            found = sorted(root.rglob(pattern))
            if found:
                return found[0]
        return None

    def configured_java(self, major: int | None = None) -> JavaRuntime | None:
        java = self.config.get("java", {})
        if bool(java.get("auto", True)):
            return None
        raw = str(java.get("path", "") or "").strip()
        if not raw:
            return None
        try:
            runtime = self.java_runtime_from_path(raw, major)
        except LauncherError:
            logger.warning("Configured global Java is invalid: %s", raw)
            return None
        return runtime

    def preferred_java(self, major: int) -> JavaRuntime | None:
        return self.configured_java(major) or self.managed_java(major)

    def ensure_java(
        self,
        major: int,
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> JavaRuntime:
        major = int(major)
        self._raise_if_cancelled(cancel_event)
        configured = self.configured_java(major)
        if configured is not None:
            self._emit(progress, 100, f"Java {configured.major} выбрана", str(configured.path))
            return configured
        runtime = self.managed_java(major)
        if runtime is not None:
            self._emit(progress, 100, f"Java {major} найдена", str(runtime.path))
            return runtime

        self._emit(progress, 0, f"Загрузка Java {major}", "Eclipse Temurin JRE")
        try:
            with self._java_lock:
                runtime = self.managed_java(major)
                if runtime is not None:
                    self._emit(progress, 100, f"Java {major} готова", str(runtime.path))
                    return runtime
                return self._download_temurin(major, progress, cancel_event)
        except InstallCancelled:
            raise
        except Exception as exc:
            logger.exception("Temurin download failed")
            system = self._find_system_java(major)
            if system is not None:
                logger.warning("Falling back to system Java %s", system.path)
                self._emit(progress, 100, "Используется системная Java", str(system.path))
                return system
            if isinstance(exc, LauncherError):
                raise
            raise LauncherError(
                f"Не удалось автоматически скачать Java {major}. "
                "Установите Eclipse Temurin вручную или проверьте подключение к интернету."
            ) from exc

    def _download_temurin(
        self,
        major: int,
        progress: ProgressCallback | None,
        cancel_event: threading.Event | None,
    ) -> JavaRuntime:
        platform_info = self._adoptium_platform()
        self._emit(progress, 1, f"Поиск Java {major}", "Eclipse Temurin")
        package = self._adoptium_package(major, platform_info)
        self._raise_if_cancelled(cancel_event)

        link = str(package.get("link", ""))
        expected_sha256 = str(package.get("checksum", "")).lower()
        size = int(package.get("size") or 0)
        if not link:
            raise LauncherError("Adoptium не вернул ссылку на Java.")

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.runtime_dir / f".temurin-{major}-{uuid.uuid4().hex}.download"
        extract_path = self.runtime_dir / f".temurin-{major}-{uuid.uuid4().hex}.extract"
        target = self.runtime_dir / f"temurin-{major}"
        digest = hashlib.sha256()
        downloaded = 0
        last_percent = -1

        try:
            self._emit(progress, 3, f"Скачивание Java {major}", "Eclipse Temurin JRE")
            with self._http_get(link, timeout=(15, 120), stream=True) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or size or 0)
                with archive_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=512 * 1024):
                        self._raise_if_cancelled(cancel_event)
                        if not chunk:
                            continue
                        handle.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        percent = 5 + int(70 * downloaded / total) if total else 20
                        percent = max(5, min(75, percent))
                        if percent != last_percent:
                            last_percent = percent
                            detail = (
                                f"{downloaded / (1024 * 1024):.1f} из "
                                f"{total / (1024 * 1024):.1f} МБ"
                                if total
                                else f"{downloaded / (1024 * 1024):.1f} МБ"
                            )
                            self._emit(progress, percent, f"Скачивание Java {major}", detail)

            actual_sha256 = digest.hexdigest()
            if expected_sha256 and actual_sha256 != expected_sha256:
                raise LauncherError("Контрольная сумма Java не совпала. Загрузка отменена.")

            self._raise_if_cancelled(cancel_event)
            self._emit(progress, 76, "Распаковка Java", "")
            extract_path.mkdir(parents=True, exist_ok=True)
            self._extract_archive(archive_path, extract_path, progress, cancel_event, major)

            probe = self._find_java_for_probe(extract_path)
            launch = self._find_runtime_executable(extract_path)
            if probe is None or launch is None:
                raise LauncherError("В архиве Java не найден исполняемый файл.")
            detected_major, detected_version = self._probe_java(probe)
            if detected_major is None:
                raise LauncherError("Не удалось проверить скачанную Java.")
            if detected_major != major:
                raise LauncherError(
                    f"Скачана Java {detected_major}, а требуется Java {major}."
                )

            self._raise_if_cancelled(cancel_event)
            if target.exists():
                _safe_rmtree(target)
            os.replace(extract_path, target)
            launch_relative = launch.relative_to(extract_path)
            metadata = {
                "schema_version": 1,
                "vendor": "Eclipse Temurin",
                "source": "Temurin",
                "major": major,
                "version": detected_version,
                "launch_executable": str(launch_relative).replace("\\", "/"),
                "installed_at": _now_iso(),
            }
            _atomic_write_json(target / ".fionix-runtime.json", metadata)
            self._emit(progress, 100, f"Java {major} готова", detected_version)
            logger.info("Installed Temurin Java %s (%s)", major, detected_version)
            return JavaRuntime(
                path=target / launch_relative,
                major=major,
                source="Temurin",
                version=detected_version,
            )
        finally:
            archive_path.unlink(missing_ok=True)
            _safe_rmtree(extract_path)

    def _adoptium_platform(self) -> tuple[str, str]:
        system = platform.system()
        if system == "Windows":
            os_name = "windows"
        elif system == "Darwin":
            os_name = "mac"
        elif system == "Linux":
            os_name = "linux"
        else:
            raise LauncherError(f"Автоматическая Java недоступна на {system}.")
        machine = platform.machine().lower()
        if machine in ("arm64", "aarch64"):
            arch = "aarch64"
        else:
            arch = "x64"
        return os_name, arch

    def _adoptium_package(self, major: int, platform_info: tuple[str, str]) -> Mapping[str, Any]:
        os_name, arch = platform_info
        for image_type in ("jre", "jdk"):
            params = {
                "architecture": arch,
                "image_type": image_type,
                "os": os_name,
                "vendor": "eclipse",
            }
            try:
                response = self._http_get(
                    ADOPTIUM_API.format(major=major), timeout=(10, 30), params=params
                )
                response.raise_for_status()
                assets = response.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Adoptium request failed: %s", exc)
                continue
            if isinstance(assets, list) and assets:
                for asset in assets:
                    try:
                        package = asset["binary"]["package"]
                        if package.get("link"):
                            return package
                    except (KeyError, TypeError):
                        continue
        raise LauncherError(
            f"Adoptium не предлагает Java {major} для {os_name}-{arch}."
        )

    def _extract_archive(
        self,
        archive: Path,
        destination: Path,
        progress: ProgressCallback | None,
        cancel_event: threading.Event | None,
        major: int,
    ) -> None:
        destination_resolved = destination.resolve()
        name = archive.name.lower()
        try:
            if name.endswith(".zip") or zipfile.is_zipfile(archive):
                with zipfile.ZipFile(archive) as zf:
                    members = zf.infolist()
                    total = max(1, len(members))
                    for index, member in enumerate(members):
                        self._raise_if_cancelled(cancel_event)
                        target = (destination / member.filename).resolve()
                        if destination_resolved not in target.parents and target != destination_resolved:
                            raise LauncherError("Архив Java содержит небезопасный путь.")
                        mode = (member.external_attr >> 16) & 0o170000
                        if mode == 0o120000:
                            continue
                        zf.extract(member, destination)
                        if index % 10 == 0:
                            self._emit(
                                progress,
                                76 + int(20 * index / total),
                                "Распаковка Java",
                                member.filename,
                            )
            elif tarfile.is_tarfile(archive):
                with tarfile.open(archive) as tf:
                    members = tf.getmembers()
                    total = max(1, len(members))
                    for index, member in enumerate(members):
                        self._raise_if_cancelled(cancel_event)
                        target = (destination / member.name).resolve()
                        if destination_resolved not in target.parents and target != destination_resolved:
                            raise LauncherError("Архив Java содержит небезопасный путь.")
                        if member.issym() or member.islnk():
                            continue
                        tf.extract(member, destination)
                        if index % 10 == 0:
                            self._emit(
                                progress,
                                76 + int(20 * index / total),
                                "Распаковка Java",
                                member.name,
                            )
            else:
                raise LauncherError("Неизвестный формат архива Java.")
        except (zipfile.BadZipFile, tarfile.TarError) as exc:
            raise LauncherError("Не удалось распаковать архив Java.") from exc

        for executable in destination.rglob("bin/java*"):
            if executable.is_file():
                try:
                    executable.chmod(executable.stat().st_mode | 0o755)
                except OSError:
                    pass
        self._emit(progress, 97, "Проверка Java", f"Java {major}")

    def _probe_java(self, executable: Path) -> tuple[int | None, str]:
        try:
            completed = subprocess.run(
                [str(executable), "-version"],
                capture_output=True,
                text=True,
                timeout=10,
                **_hidden_process_kwargs(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Java probe failed for %s: %s", executable, exc)
            return None, ""
        output = f"{completed.stdout}\n{completed.stderr}"
        match = re.search(r'version\s+"([^"]+)"', output)
        if not match:
            return None, ""
        version = match.group(1)
        if version.startswith("1."):
            try:
                return int(version.split(".")[1]), version
            except (IndexError, ValueError):
                return None, version
        try:
            return int(version.split(".")[0]), version
        except ValueError:
            return None, version

    def _find_system_java(self, major: int) -> JavaRuntime | None:
        candidates: list[Path] = []
        java_home = os.environ.get("JAVA_HOME", "").strip()
        if java_home:
            candidates.extend(
                [
                    Path(java_home) / "bin" / "java.exe",
                    Path(java_home) / "bin" / "java",
                ]
            )
        which_java = shutil.which("java")
        if which_java:
            candidates.append(Path(which_java))

        if sys.platform == "win32":
            roots = [
                os.environ.get("ProgramFiles", r"C:\Program Files"),
                os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                os.environ.get("LOCALAPPDATA", ""),
            ]
            patterns = (
                "Eclipse Adoptium/*/bin/java.exe",
                "Java/*/bin/java.exe",
                "Microsoft/jdk*/bin/java.exe",
            )
            for root in filter(None, roots):
                for pattern in patterns:
                    candidates.extend(Path(root).glob(pattern))

        seen: set[str] = set()
        for executable in candidates:
            try:
                key = str(executable.resolve()).lower()
            except OSError:
                continue
            if key in seen or not executable.is_file():
                continue
            seen.add(key)
            detected, version = self._probe_java(executable)
            if detected != major:
                continue
            launch = executable
            javaw = executable.with_name("javaw.exe")
            if javaw.is_file():
                launch = javaw
            return JavaRuntime(
                path=launch,
                major=major,
                source="System",
                version=version,
            )
        return None

    # ------------------------------------------------------- java selection
    def available_java_runtimes(self) -> list[JavaRuntime]:
        """Managed runtimes that can be offered in instance settings."""
        runtimes: list[JavaRuntime] = []
        for folder in sorted(self.runtime_dir.glob("temurin-*")):
            match = re.search(r"temurin-(\d+)$", folder.name)
            if not match:
                continue
            runtime = self.managed_java(int(match.group(1)))
            if runtime is not None:
                runtimes.append(runtime)
        runtimes.sort(key=lambda runtime: runtime.major)
        return runtimes

    def java_runtime_from_path(
        self, executable: str | Path, expected_major: int | None = None
    ) -> JavaRuntime:
        """Validate a user-selected Java executable and build a launch runtime."""
        path = Path(executable).expanduser()
        if not path.is_file():
            raise LauncherError("Выбранный файл Java не найден.")
        probe_path = path
        if path.name.lower() == "javaw.exe":
            sibling = path.with_name("java.exe")
            if sibling.is_file():
                probe_path = sibling
        major, version = self._probe_java(probe_path)
        if major is None:
            raise LauncherError(
                "Не удалось определить версию выбранной Java. "
                "Выберите java.exe из установленного JDK/JRE."
            )
        if expected_major is not None and major < int(expected_major):
            raise LauncherError(
                f"Выбрана Java {major}, но для этой сборки нужна Java "
                f"{expected_major} или новее."
            )
        launch_path = path
        if path.name.lower() == "java.exe":
            javaw = path.with_name("javaw.exe")
            if javaw.is_file():
                launch_path = javaw
        return JavaRuntime(
            path=launch_path, major=major, source="Пользовательская", version=version
        )

    def java_for_instance(self, instance: Instance) -> JavaRuntime | None:
        """Return a custom Java if configured; raise if it is no longer valid."""
        if not instance.java_path:
            return None
        return self.java_runtime_from_path(instance.java_path, instance.java_major)

    # ------------------------------------------------------------- launch
    def build_launch_command(
        self, instance: Instance, java: JavaRuntime, account: Any | None = None
    ) -> list[str]:
        memory = max(
            1024, min(16384, int(instance.memory_mb or self.config.memory_mb))
        )
        username = self._offline_username()
        account_uuid = offline_uuid(username)
        access_token = "0"
        user_type = "legacy"
        if account is not None:
            candidate = str(getattr(account, "username", "") or "").strip()
            if candidate:
                username = candidate[:16]
            candidate_uuid = str(getattr(account, "uuid", "") or "").strip()
            if candidate_uuid:
                account_uuid = candidate_uuid
            provider = str(getattr(account, "provider", "guest") or "guest")
            token = str(getattr(account, "access_token", "") or "")
            if token and provider in {"littleskin", "elyby", "microsoft"}:
                access_token = token
            if provider == "microsoft":
                user_type = "msa"
        jvm_arguments = [
            f"-Xmx{memory}M",
            f"-Xms{min(1024, memory)}M",
        ]
        proxy = self.config.get("proxy", {})
        if proxy.get("enabled") and str(proxy.get("host", "")).strip():
            host = str(proxy["host"]).strip()
            port = str(int(proxy.get("port", 8080) or 8080))
            for scheme in ("http", "https"):
                jvm_arguments.extend(
                    [
                        f"-D{scheme}.proxyHost={host}",
                        f"-D{scheme}.proxyPort={port}",
                    ]
                )
            if proxy.get("username"):
                jvm_arguments.extend(
                    [
                        f"-Dhttp.proxyUser={proxy.get('username', '')}",
                        f"-Dhttp.proxyPassword={proxy.get('password', '')}",
                        f"-Dhttps.proxyUser={proxy.get('username', '')}",
                        f"-Dhttps.proxyPassword={proxy.get('password', '')}",
                    ]
                )
        options = {
            "username": username,
            "uuid": account_uuid,
            "token": access_token,
            "userType": user_type,
            "executablePath": str(java.path),
            "defaultExecutablePath": str(java.path),
            "jvmArguments": jvm_arguments,
            "launcherName": "Fionix",
            "launcherVersion": __version__,
            "gameDirectory": str(instance.path),
            "customResolution": False,
            "enableLoggingConfig": False,
        }
        try:
            command = mc_command.get_minecraft_command(
                instance.effective_launch_version, str(instance.path), options
            )
        except Exception as exc:
            logger.exception("Could not build Minecraft launch command")
            raise LauncherError(
                "Не удалось подготовить команду запуска. Возможно, файлы экземпляра повреждены."
            ) from exc
        if not command:
            raise LauncherError("Пустая команда запуска Minecraft.")
        command[0] = str(java.path)
        logger.info(
            "Launching %s (%s) with Java %s",
            instance.effective_launch_version,
            instance.loader,
            java.path,
        )
        return command

    def _offline_username(self) -> str:
        raw = str(self.config.get("player", {}).get("name", "")).strip()
        if re.fullmatch(r"[A-Za-z0-9_]{3,16}", raw):
            return raw
        return "FionixPlayer"

    def create_game_session(
        self, instance: Instance, java: JavaRuntime, account: Any | None = None
    ) -> "GameSession":
        command = self.build_launch_command(instance, java, account)
        logs_dir = instance.path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"game-{datetime.now():%Y%m%d-%H%M%S}.log"
        return GameSession(instance, command, java, log_path)

    # ----------------------------------------------------------- content
    def content_category(self, key: str) -> ContentCategory:
        category = CONTENT_CATEGORIES.get(key)
        if category is None:
            raise LauncherError("Неизвестный раздел содержимого.")
        return category

    def content_dir(
        self, instance: Instance, key: str, *, create: bool = True
    ) -> Path:
        category = self.content_category(key)
        path = instance.path / category.folder
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def list_content(self, instance: Instance, key: str) -> list[ContentFile]:
        path = self.content_dir(instance, key, create=False)
        if not path.is_dir():
            return []
        result: list[ContentFile] = []
        try:
            entries = list(path.iterdir())
        except OSError as exc:
            logger.warning("Cannot list %s: %s", path, exc)
            return result

        for entry in entries:
            if entry.name.startswith("."):
                continue
            enabled = not entry.name.endswith(DISABLED_SUFFIX)
            try:
                size = entry.stat().st_size if entry.is_file() else 0
            except OSError:
                size = 0
            result.append(
                ContentFile(
                    path=entry,
                    name=entry.name,
                    enabled=enabled,
                    size=size,
                    is_dir=entry.is_dir(),
                )
            )
        result.sort(key=lambda item: (not item.enabled, item.display_name.lower()))
        return result

    def content_counts(self, instance: Instance) -> dict[str, int]:
        return {
            key: len(self.list_content(instance, key))
            for key in CONTENT_CATEGORIES
        }

    def toggle_content(
        self, instance: Instance, key: str, path: Path, enabled: bool
    ) -> Path:
        """Rename a content entry to/from the ``.disabled`` suffix."""
        root = self.content_dir(instance, key).resolve()
        path = Path(path)
        try:
            path_resolved = path.resolve()
        except OSError as exc:
            raise LauncherError(f"Не удалось открыть файл: {exc}") from exc
        if path_resolved.parent != root or not path_resolved.exists():
            raise LauncherError("Файл не относится к этому разделу экземпляра.")

        name = path_resolved.name
        is_disabled = name.endswith(DISABLED_SUFFIX)
        if enabled:
            if not is_disabled:
                return path_resolved
            target = path_resolved.with_name(name[: -len(DISABLED_SUFFIX)])
        else:
            if is_disabled:
                return path_resolved
            target = path_resolved.with_name(name + DISABLED_SUFFIX)
        if target.exists():
            raise LauncherError(
                f"Нельзя переименовать: уже существует {target.name}."
            )
        try:
            path_resolved.rename(target)
        except OSError as exc:
            raise LauncherError(f"Не удалось переименовать файл: {exc}") from exc
        logger.info("Content toggled: %s -> %s", path_resolved, target)
        return target

    # ------------------------------------------------------------- backup
    def create_backup(
        self,
        instance: Instance,
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        backups_dir = self.data_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backups_dir / f"{instance.folder_name}-{stamp}.zip"
        counter = 1
        while target.exists():
            target = backups_dir / f"{instance.folder_name}-{stamp}-{counter}.zip"
            counter += 1
        temp = target.with_name(target.name + ".tmp")

        files: list[Path] = []
        folders: list[Path] = []
        for folder_name in ("mods", "config"):
            folder = instance.path / folder_name
            if folder.is_dir():
                folders.append(folder)
                for path in folder.rglob("*"):
                    if path.is_file():
                        files.append(path)

        self._emit(progress, 1, "Создание бэкапа", instance.name)
        try:
            with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
                for folder in folders:
                    archive.write(folder, folder.relative_to(instance.path).as_posix() + "/")
                total = max(1, len(files))
                for index, path in enumerate(files, start=1):
                    self._raise_if_cancelled(cancel_event)
                    archive.write(path, path.relative_to(instance.path).as_posix())
                    self._emit(
                        progress,
                        min(99, 5 + int(93 * index / total)),
                        "Создание бэкапа",
                        str(path.relative_to(instance.path)),
                    )
                self._raise_if_cancelled(cancel_event)
            os.replace(temp, target)
        except InstallCancelled:
            temp.unlink(missing_ok=True)
            raise
        except (OSError, zipfile.BadZipFile) as exc:
            temp.unlink(missing_ok=True)
            logger.exception("Backup failed")
            raise LauncherError(f"Не удалось создать бэкап: {exc}") from exc
        self._emit(progress, 100, "Бэкап готов", target.name)
        return target

    # ----------------------------------------------------------- optimize
    def _install_optimization_mod(
        self,
        instance: Instance,
        slug: str,
        display_name: str,
        progress: ProgressCallback | None,
        cancel_event: threading.Event | None,
        *,
        base: int,
        span: int,
    ) -> Path:
        self._emit(progress, base, f"Поиск {display_name}", "Modrinth")
        try:
            response = self._http_get(
                f"{MODRINTH_API}/project/{slug}/version",
                params={
                    "game_versions": json.dumps([instance.version]),
                    "loaders": json.dumps([instance.loader]),
                },
                timeout=(10, 30),
            )
            response.raise_for_status()
            versions = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise LauncherError(
                f"Не удалось получить {display_name} с Modrinth. "
                "Проверьте подключение к интернету."
            ) from exc
        if not isinstance(versions, list) or not versions:
            raise LauncherError(
                f"Для {display_name} нет сборки под Minecraft {instance.version} "
                f"({instance.loader})."
            )

        versions.sort(key=lambda item: str(item.get("date_published", "")), reverse=True)
        release_versions = [
            item for item in versions if item.get("version_type") == "release"
        ]
        chosen = release_versions[0] if release_versions else versions[0]
        file_info = None
        for candidate in chosen.get("files", []):
            if candidate.get("primary"):
                file_info = candidate
                break
        if file_info is None and chosen.get("files"):
            file_info = chosen["files"][0]
        if not isinstance(file_info, Mapping):
            raise LauncherError(f"У {display_name} не найден файл для загрузки.")

        filename = Path(str(file_info.get("filename", ""))).name
        download_url = str(file_info.get("url", ""))
        if not filename or not download_url:
            raise LauncherError(f"У {display_name} нет ссылки на файл.")

        mods_dir = self.content_dir(instance, "mods")
        target = mods_dir / filename
        disabled = target.with_name(target.name + DISABLED_SUFFIX)
        if target.is_file():
            self._emit(progress, base + span, f"{display_name} уже установлен", filename)
            return target
        if disabled.is_file():
            try:
                disabled.rename(target)
            except OSError as exc:
                raise LauncherError(
                    f"Не удалось включить уже скачанный {display_name}: {exc}"
                ) from exc
            self._emit(progress, base + span, f"{display_name} включён", filename)
            return target

        expected_sha512 = str((file_info.get("hashes") or {}).get("sha512", "")).lower()
        size = int(file_info.get("size") or 0)
        temp = target.with_name(target.name + ".part")
        downloaded = 0
        last_percent = -1
        digest = hashlib.sha512()
        try:
            with self._http_get(download_url, stream=True, timeout=(15, 120)) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or size or 0)
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        self._raise_if_cancelled(cancel_event)
                        if not chunk:
                            continue
                        handle.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        ratio = downloaded / total if total else 0.3
                        percent = base + int(span * min(1.0, ratio))
                        percent = max(base, min(base + span, percent))
                        if percent != last_percent:
                            last_percent = percent
                            self._emit(
                                progress,
                                percent,
                                f"Загрузка {display_name}",
                                f"{downloaded / 1024 / 1024:.1f} МБ",
                            )
            self._raise_if_cancelled(cancel_event)
            if expected_sha512 and digest.hexdigest() != expected_sha512:
                raise LauncherError(
                    f"Контрольная сумма {display_name} не совпала."
                )
            os.replace(temp, target)
            try:
                from src.core.exporter import record_installed_mod

                record_installed_mod(
                    instance,
                    name=display_name,
                    version=str(chosen.get("version_number") or ""),
                    source="modrinth",
                    filename=target.name,
                    project_id=str(chosen.get("project_id") or ""),
                )
            except Exception:
                logger.debug("Could not record optimization metadata", exc_info=True)
        except InstallCancelled:
            temp.unlink(missing_ok=True)
            raise
        except LauncherError:
            temp.unlink(missing_ok=True)
            raise
        except (requests.RequestException, OSError) as exc:
            temp.unlink(missing_ok=True)
            logger.exception("Optimization mod download failed")
            raise LauncherError(
                f"Не удалось скачать {display_name}: {exc}"
            ) from exc
        self._emit(progress, base + span, f"{display_name} установлен", filename)
        return target

    def install_optimization(
        self,
        instance: Instance,
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[Path]:
        pairs = OPTIMIZATION_MODS.get(instance.loader)
        if not pairs:
            raise LauncherError(
                "Оптимизационные моды доступны для Fabric и Forge."
            )
        paths: list[Path] = []
        count = len(pairs)
        for index, (slug, display_name) in enumerate(pairs):
            base = 5 + int(88 * index / count)
            span = max(1, int(88 / count))
            paths.append(
                self._install_optimization_mod(
                    instance,
                    slug,
                    display_name,
                    progress,
                    cancel_event,
                    base=base,
                    span=span,
                )
            )
        self._emit(progress, 100, "Оптимизация установлена", instance.name)
        return paths

    # ------------------------------------------------------------- folders
    def delete_instance(self, instance: Instance) -> bool:
        """Permanently remove one instance directory after path validation."""
        instances_root = self.instances_dir.resolve()
        try:
            target = Path(instance.path).resolve()
        except OSError as exc:
            raise LauncherError(f"Не удалось получить путь экземпляра: {exc}") from exc
        if target == instances_root or instances_root not in target.parents:
            raise LauncherError("Отказано: путь экземпляра вне папки экземпляров.")
        if not target.is_dir():
            raise LauncherError("Папка экземпляра не найдена.")
        try:
            shutil.rmtree(target)
        except OSError as exc:
            logger.exception("Could not delete instance %s", target)
            raise LauncherError(f"Не удалось удалить экземпляр: {exc}") from exc
        logger.info("Deleted instance %s", target)
        return True

    def open_instance_folder(self, instance: Instance) -> None:
        path = instance.path
        if not path.is_dir():
            raise LauncherError("Папка экземпляра не найдена.")
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise LauncherError(f"Не удалось открыть папку: {exc}") from exc

    def open_runtime_folder(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(self.runtime_dir))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self.runtime_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", str(self.runtime_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise LauncherError(f"Не удалось открыть папку runtime: {exc}") from exc

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _emit(
        progress: ProgressCallback | None, percent: int, title: str, detail: str = ""
    ) -> None:
        if progress is not None:
            progress(max(0, min(100, int(percent))), title, detail)

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise InstallCancelled("Операция отменена пользователем.")


# ---------------------------------------------------------------------------
# Game process + playtime
# ---------------------------------------------------------------------------


class GameSession(QObject):
    """A running Minecraft process with a playtime timer.

    ``tick`` carries ``(session_seconds, total_playtime_seconds)``.
    """

    started = Signal()
    tick = Signal(int, int)
    finished = Signal(int, int)

    def __init__(
        self,
        instance: Instance,
        command: list[str],
        java: JavaRuntime,
        log_path: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.instance = instance
        self.command = command
        self.java = java
        self.log_path = log_path
        self._base_playtime = max(0, instance.playtime_seconds)
        self._session_seconds = 0
        self._finished = False
        self._start_error = ""
        self.user_stopped = False
        self._process: subprocess.Popen | None = None
        self._log_handle = None

        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)
        self._persist_timer = QTimer(self)
        self._persist_timer.setInterval(15_000)
        self._persist_timer.timeout.connect(self._persist_playtime)

    @property
    def process(self) -> subprocess.Popen | None:
        return self._process

    @property
    def error_message(self) -> str:
        return self._start_error

    @property
    def session_seconds(self) -> int:
        return self._session_seconds

    @property
    def total_playtime(self) -> int:
        return self._base_playtime + self._session_seconds

    def is_running(self) -> bool:
        return (
            not self._finished
            and self._process is not None
            and self._process.poll() is None
        )

    def start(self) -> bool:
        if not self.command:
            self._start_error = "Пустая команда запуска."
            return False
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = self.log_path.open("ab")
            header = (
                f"\n=== Fionix {__version__} · Minecraft {self.instance.version} · "
                f"{datetime.now():%Y-%m-%d %H:%M:%S} ===\n"
                f"Java: {self.java.path}\n"
            ).encode("utf-8")
            self._log_handle.write(header)
            self._log_handle.flush()
        except OSError as exc:
            logger.warning("Cannot write Minecraft log: %s", exc)
            self._log_handle = None

        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            kwargs.update(_hidden_process_kwargs())
        try:
            self._process = subprocess.Popen(
                self.command,
                cwd=str(self.instance.path),
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle if self._log_handle is not None else subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                **kwargs,
            )
        except OSError as exc:
            self._close_log()
            self._start_error = str(exc) or "Java не запустилась."
            logger.error("Minecraft did not start: %s", self._start_error)
            return False

        self._elapsed.start()
        self._timer.start()
        self._persist_timer.start()
        self.instance.last_played_at = _now_iso()
        self._save_instance_best_effort()
        self.started.emit()
        logger.info("Minecraft process started (pid %s)", self._process.pid)
        return True

    def stop(self, *, wait_ms: int = 0) -> None:
        if self._process is None or self._process.poll() is not None:
            return
        logger.info("Stopping Minecraft process")
        self.user_stopped = True
        try:
            self._process.terminate()
        except OSError:
            pass
        if wait_ms:
            try:
                self._process.wait(timeout=max(1, wait_ms) / 1000)
            except subprocess.TimeoutExpired:
                try:
                    self._process.kill()
                    self._process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if not self._finished:
                code = self._process.returncode if self._process else -1
                self._finish(code if code is not None else -1)
        else:
            QTimer.singleShot(4000, self._force_kill_if_running)

    def _force_kill_if_running(self) -> None:
        if self._process is not None and self._process.poll() is None:
            logger.warning("Minecraft did not close gracefully; killing it")
            try:
                self._process.kill()
            except OSError:
                pass

    def _on_tick(self) -> None:
        if self._finished:
            return
        if self._elapsed.isValid():
            self._session_seconds = max(0, int(self._elapsed.elapsed() // 1000))
            self.tick.emit(self._session_seconds, self.total_playtime)
        if self._process is not None:
            exit_code = self._process.poll()
            if exit_code is not None:
                self._finish(exit_code)

    def _persist_playtime(self) -> None:
        if self._finished:
            return
        if self._elapsed.isValid():
            self._session_seconds = max(0, int(self._elapsed.elapsed() // 1000))
        self.instance.playtime_seconds = self.total_playtime
        self._save_instance_best_effort()

    def _finish(self, exit_code: int) -> None:
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        self._persist_timer.stop()
        if self._elapsed.isValid():
            self._session_seconds = max(0, int(self._elapsed.elapsed() // 1000))
        self.instance.playtime_seconds = self.total_playtime
        self._save_instance_best_effort()
        self._close_log()
        logger.info(
            "Minecraft exited with code %s after %ss", exit_code, self._session_seconds
        )
        self.finished.emit(exit_code, self.total_playtime)

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def _save_instance_best_effort(self) -> None:
        try:
            self.instance.save()
        except OSError as exc:
            logger.error("Could not save instance playtime: %s", exc)
