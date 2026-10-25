"""Modrinth/CurseForge modpack resolution and installation."""

from __future__ import annotations

import json
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import tempfile
import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import requests

from src.core.launcher import Instance, LauncherError, LauncherService
from src.core.market_api import MarketAPI, MarketError, MarketProject

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModpackInfo:
    project: MarketProject
    name: str
    source: str
    version_id: str
    version_name: str
    mc_version: str
    loader: str
    loader_version: str
    archive: Path
    mod_files: tuple[str, ...] = ()
    description: str = ""
    files_manifest: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)


def _safe_relative(value: str) -> Path:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise MarketError("Архив сборки содержит небезопасный путь.")
    return Path(*path.parts)


def _loader_from_dependencies(deps: Mapping[str, Any]) -> tuple[str, str]:
    for key, loader in (
        ("fabric-loader", "fabric"),
        ("quilt-loader", "quilt"),
        ("forge", "forge"),
        ("neoforge", "neoforge"),
    ):
        if key in deps and deps[key]:
            return loader, str(deps[key])
    return "vanilla", ""


def _mrpack_info(project: MarketProject, archive: Path) -> ModpackInfo:
    try:
        with zipfile.ZipFile(archive) as zf:
            raw = zf.read("modrinth.index.json")
            index = json.loads(raw.decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise MarketError("Не удалось прочитать .mrpack сборку.") from exc
    if not isinstance(index, Mapping):
        raise MarketError("Некорректный modrinth.index.json.")
    deps = index.get("dependencies") or {}
    if not isinstance(deps, Mapping):
        deps = {}
    mc_version = str(deps.get("minecraft") or "")
    if not mc_version:
        raise MarketError("В сборке не указана версия Minecraft.")
    loader, loader_version = _loader_from_dependencies(deps)
    files = index.get("files") or []
    paths: list[str] = []
    for item in files:
        if isinstance(item, Mapping) and item.get("path"):
            paths.append(str(item["path"]))
    return ModpackInfo(
        project=project,
        name=str(index.get("name") or project.name),
        source="modrinth",
        version_id=str(index.get("versionId") or ""),
        version_name=str(index.get("versionId") or ""),
        mc_version=mc_version,
        loader=loader,
        loader_version=loader_version,
        archive=archive,
        mod_files=tuple(paths),
        description=project.description,
        files_manifest=tuple(item for item in files if isinstance(item, Mapping)),
    )


def _curseforge_info(project: MarketProject, archive: Path) -> ModpackInfo:
    try:
        with zipfile.ZipFile(archive) as zf:
            raw = zf.read("manifest.json")
            manifest = json.loads(raw.decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise MarketError("Не удалось прочитать сборку CurseForge.") from exc
    minecraft = manifest.get("minecraft") or {}
    mc_version = str(minecraft.get("version") or "")
    if not mc_version:
        raise MarketError("В сборке не указана версия Minecraft.")
    loader = "vanilla"
    loader_version = ""
    loaders = minecraft.get("modLoaders") or []
    if loaders and isinstance(loaders[0], Mapping):
        loader_id = str(loaders[0].get("id") or "")
        if "-" in loader_id:
            name, _, version = loader_id.partition("-")
            loader = name if name in {"forge", "fabric", "quilt", "neoforge"} else "vanilla"
            loader_version = version
    files = manifest.get("files") or []
    paths = [f"mods/CurseForge-{item.get('projectID')}-{item.get('fileID')}.jar" for item in files if isinstance(item, Mapping)]
    return ModpackInfo(
        project=project,
        name=str(manifest.get("name") or project.name),
        source="curseforge",
        version_id="",
        version_name=str(manifest.get("version") or ""),
        mc_version=mc_version,
        loader=loader,
        loader_version=loader_version,
        archive=archive,
        mod_files=tuple(paths),
        description=project.description,
        files_manifest=tuple(item for item in files if isinstance(item, Mapping)),
    )


def _make_temp_dir() -> Path:
    """Create a normal (non-0700) temp folder for Windows/Qt sandboxes."""
    base = Path(tempfile.gettempdir())
    path = base / f"fionix-modpack-{uuid.uuid4().hex}"
    path.mkdir(mode=0o777, parents=True)
    return path


def resolve_modpack(
    api: MarketAPI,
    project: MarketProject,
    progress=None,
    cancel_event: threading.Event | None = None,
) -> ModpackInfo:
    """Download the pack archive and read its manifest without installing it."""
    temp_dir = _make_temp_dir()
    try:
        if project.source == "curseforge":
            latest = api.curseforge_modpack_file(project)
            if not isinstance(latest, Mapping):
                raise MarketError("У сборки CurseForge нет загружаемого файла.")
            url = str(latest.get("downloadUrl") or "")
            filename = str(latest.get("fileName") or "modpack.zip")
            if not url:
                raise MarketError("CurseForge не вернул ссылку на сборку.")
            archive = api.download_file(
                url, temp_dir, filename, progress=progress, cancel_event=cancel_event
            )
            return _curseforge_info(project, archive)
        versions = api.modrinth_all_versions(project.id)
        version = next(
            (
                item
                for item in versions
                if item.filename.lower().endswith(".mrpack") and item.url
            ),
            None,
        )
        if version is None:
            raise MarketError("У сборки Modrinth нет .mrpack файла.")
        archive = api.download_file(
            version.url,
            temp_dir,
            version.filename,
            sha512=version.sha512,
            progress=progress,
            cancel_event=cancel_event,
        )
        return _mrpack_info(project, archive)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _extract_overrides(archive: Path, instance: Instance, prefix: str) -> None:
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if not name.startswith(prefix) or name.endswith("/"):
                    continue
                relative = _safe_relative(name[len(prefix):])
                target = instance.path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, target.open("wb") as target_file:
                    shutil.copyfileobj(source, target_file)
    except zipfile.BadZipFile as exc:
        raise MarketError("Повреждён архив сборки.") from exc


def install_modpack(
    service: LauncherService,
    api: MarketAPI,
    info: ModpackInfo,
    progress=None,
    cancel_event: threading.Event | None = None,
    *,
    instance_folder: str | None = None,
    display_name: str | None = None,
    replace_existing: bool = False,
) -> Instance:
    """Create a separate instance and install every file from the pack."""
    folder_slug = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in info.project.slug
    )
    instance = service.create_instance(
        info.mc_version,
        info.loader,
        progress=lambda p, t, d: _emit(progress, int(p * 0.32), t, d),
        cancel_event=cancel_event,
        optimize=False,
        display_name=display_name or info.name,
        instance_folder=instance_folder or f"Modpack_{folder_slug[:45]}",
        replace_existing=replace_existing,
    )
    if cancel_event is not None and cancel_event.is_set():
        raise LauncherError("Установка сборки отменена.")
    _emit(progress, 34, "Установка модов сборки", info.name)

    if info.source == "modrinth":
        _install_modrinth_files(api, info, instance, progress, cancel_event)
    else:
        _install_curseforge_files(api, info, instance, progress, cancel_event)

    _emit(progress, 94, "Распаковка overrides", info.name)
    if info.source == "modrinth":
        _extract_overrides(info.archive, instance, "overrides/")
    else:
        _extract_overrides(info.archive, instance, "overrides/")
    instance.modpack_name = info.project.name
    instance.modpack_author = info.project.author
    instance.modpack_version = info.version_name or info.version_id
    instance.modpack_source = info.source
    instance.modpack_project_id = str(info.project.id)
    instance.save()
    _emit(progress, 100, "Сборка установлена", instance.name)
    return instance


def _install_modrinth_files(
    api: MarketAPI,
    info: ModpackInfo,
    instance: Instance,
    progress,
    cancel_event,
) -> None:
    files = list(info.files_manifest)
    total = max(1, len(files))
    if not files:
        return
    lock = threading.Lock()
    completed = 0

    def download(item: Mapping[str, Any]) -> None:
        nonlocal completed
        if cancel_event is not None and cancel_event.is_set():
            raise LauncherError("Установка сборки отменена.")
        path = _safe_relative(str(item.get("path") or ""))
        destination = instance.path / path
        urls = item.get("downloads") or []
        if not urls:
            return
        hashes = item.get("hashes") or {}
        api.download_file(
            str(urls[0]),
            destination.parent,
            destination.name,
            sha512=str(hashes.get("sha512") or ""),
            cancel_event=cancel_event,
        )
        with lock:
            completed += 1
            _emit(
                progress,
                34 + int(completed * 56 / total),
                f"Моды: {completed} из {total}",
                path.name,
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download, item) for item in files]
        for future in as_completed(futures):
            future.result()


def _install_curseforge_files(
    api: MarketAPI,
    info: ModpackInfo,
    instance: Instance,
    progress,
    cancel_event,
) -> None:
    files = list(info.files_manifest)
    total = max(1, len(files))
    if not files:
        return
    lock = threading.Lock()
    completed = 0

    def download(item: Mapping[str, Any]) -> None:
        nonlocal completed
        if cancel_event is not None and cancel_event.is_set():
            raise LauncherError("Установка сборки отменена.")
        project_id = item.get("projectID")
        file_id = item.get("fileID")
        if not project_id or not file_id:
            return
        file_data = api.curseforge_file(int(project_id), int(file_id))
        url = str(file_data.get("downloadUrl") or "") if file_data else ""
        filename = str(file_data.get("fileName") or f"mod-{project_id}-{file_id}.jar") if file_data else ""
        if not url:
            logger.warning("CurseForge file %s/%s has no download API URL", project_id, file_id)
            return
        api.download_file(
            url,
            instance.path / "mods",
            filename,
            cancel_event=cancel_event,
        )
        with lock:
            completed += 1
            _emit(
                progress,
                34 + int(completed * 56 / total),
                f"Моды: {completed} из {total}",
                filename,
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download, item) for item in files]
        for future in as_completed(futures):
            future.result()


def _emit(progress, percent: int, title: str, detail: str) -> None:
    if progress is not None:
        progress(max(0, min(100, percent)), title, detail)
