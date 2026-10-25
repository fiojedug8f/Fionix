"""Inspect installed mods and exchange ``.fionixpack`` build manifests.

A pack is intentionally small: it stores the Minecraft/loader choice and the
identity of every enabled mod, not the binaries.  Import downloads Modrinth
mods again into a fresh isolated instance.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from src.core.launcher import (
    DISABLED_SUFFIX,
    Instance,
    LauncherError,
    LauncherService,
)

logger = logging.getLogger(__name__)

PACK_VERSION = "1.0"
PACK_EXTENSION = ".fionixpack"
MOD_METADATA_FILE = ".fionix_mods.json"
_METADATA_LOCK = threading.RLock()
Progress = Callable[[int, str, str], None]


class PackError(LauncherError):
    """Invalid or unsupported .fionixpack file."""


def _emit(progress: Progress | None, percent: int, title: str, detail: str = "") -> None:
    if progress is not None:
        progress(max(0, min(100, int(percent))), title, detail)


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        from src.core.launcher import InstallCancelled

        raise InstallCancelled("Импорт отменён пользователем.")


def _metadata_path(instance: Instance) -> Path:
    return instance.path / MOD_METADATA_FILE


def _read_metadata(instance: Instance) -> dict[str, dict[str, Any]]:
    path = _metadata_path(instance)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, Mapping):
            result[key] = dict(value)
    return result


def _write_metadata(instance: Instance, entries: Mapping[str, Mapping[str, Any]]) -> None:
    path = _metadata_path(instance)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(entries, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp.replace(path)
    except OSError as exc:
        logger.warning("Could not write mod metadata: %s", exc)
        temp.unlink(missing_ok=True)


def record_installed_mod(
    instance: Instance,
    *,
    name: str,
    version: str,
    source: str,
    filename: str,
    project_id: str = "",
) -> None:
    with _METADATA_LOCK:
        entries = _read_metadata(instance)
        entries[filename] = {
            "name": name,
            "version": version,
            "source": source,
            "filename": filename,
            "project_id": project_id,
            "installed_at": datetime.now().isoformat(timespec="seconds"),
        }
        _write_metadata(instance, entries)


def installed_mods(instance: Instance) -> list[dict[str, str]]:
    mods_dir = instance.path / "mods"
    if not mods_dir.is_dir():
        return []
    metadata = _read_metadata(instance)
    result: list[dict[str, str]] = []
    for path in sorted(mods_dir.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.name.endswith(DISABLED_SUFFIX):
            continue
        entry = metadata.get(path.name, {})
        name = str(entry.get("name") or _guess_name(path.name))
        version = str(entry.get("version") or "")
        source = str(entry.get("source") or "local")
        result.append(
            {
                "name": name,
                "version": version,
                "source": source,
                "filename": path.name,
            }
        )
    return result


def _guess_name(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[-_+]?(mc)?\d+(\.\d+)+.*$", "", stem, flags=re.IGNORECASE)
    return stem.replace("_", " ").replace("-", " ").strip() or Path(filename).stem


def export_pack(instance: Instance, target: Path) -> Path:
    target = Path(target)
    if target.suffix.lower() != PACK_EXTENSION:
        target = target.with_suffix(PACK_EXTENSION)
    payload = {
        "version": PACK_VERSION,
        "name": instance.name,
        "mc_version": instance.version,
        "loader": instance.loader,
        "mods": [
            {
                "name": mod["name"],
                "version": mod["version"],
                "source": mod["source"],
            }
            for mod in installed_mods(instance)
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def read_pack(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackError("Не удалось прочитать .fionixpack: файл повреждён.") from exc
    if not isinstance(raw, Mapping):
        raise PackError("Некорректный .fionixpack.")
    version = str(raw.get("version") or "")
    mc_version = str(raw.get("mc_version") or "").strip()
    loader = str(raw.get("loader") or "vanilla").lower()
    if version != PACK_VERSION:
        raise PackError(f"Неподдерживаемая версия пака: {version or '—'}.")
    if not mc_version:
        raise PackError("В паке не указана версия Minecraft.")
    if loader not in {"vanilla", "fabric", "forge", "neoforge", "quilt", "optifine"}:
        raise PackError("В паке указано неизвестное ядро.")
    mods = raw.get("mods")
    if not isinstance(mods, list):
        raise PackError("В паке отсутствует список модов.")
    cleaned = []
    for item in mods:
        if not isinstance(item, Mapping):
            continue
        cleaned.append(
            {
                "name": str(item.get("name") or "").strip(),
                "version": str(item.get("version") or "").strip(),
                "source": str(item.get("source") or "local").strip().lower(),
            }
        )
    return {
        "version": version,
        "name": str(raw.get("name") or f"Импорт {mc_version}")[:80],
        "mc_version": mc_version,
        "loader": loader,
        "mods": cleaned,
    }


def import_pack(
    service: LauncherService,
    market,
    pack_path: Path,
    *,
    progress: Progress | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[Instance, list[str]]:
    from src.core.market_api import MarketAPI, MarketError

    payload = read_pack(pack_path)
    loader = payload["loader"]
    if loader == "optifine":
        raise PackError("OptiFine нельзя установить автоматически из пака.")
    _emit(progress, 2, "Импорт сборки", payload["name"])
    instance = service.create_instance(
        payload["mc_version"],
        loader,
        progress=lambda p, t, d: _emit(progress, 2 + int(p * 48 / 100), t, d),
        cancel_event=cancel_event,
    )
    if instance.name != payload["name"]:
        instance.name = payload["name"]
        instance.save()

    api = market
    mods = payload["mods"]
    skipped: list[str] = []
    total = max(1, len(mods))
    for index, mod in enumerate(mods, start=1):
        _check_cancel(cancel_event)
        name = mod["name"]
        source = mod["source"]
        start = 50 + int(48 * (index - 1) / total)
        if source != "modrinth":
            skipped.append(f"{name} ({source}: только Modrinth)")
            continue
        _emit(progress, start, "Загрузка модов", name)
        try:
            api.install_modrinth_spec(
                instance,
                name,
                mod["version"],
                progress=lambda p, t, d, base=start, span=int(48 / total): _emit(
                    progress, base + int(p * span / 100), t, d
                ),
                cancel_event=cancel_event,
            )
        except MarketError as exc:
            skipped.append(f"{name}: {exc}")
            logger.warning("Could not import %s: %s", name, exc)
    _emit(progress, 100, "Импорт завершён", instance.name)
    return instance, skipped
