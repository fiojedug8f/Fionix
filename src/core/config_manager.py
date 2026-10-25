"""Persistent application settings for Fionix.

The manager owns ``%APPDATA%/Fionix/config.json`` and the ``instances``
folder.  It is intentionally free of UI code so it can be reused by the CLI,
tests or a future headless updater.

Guarantees
----------
* First launch creates the whole data layout and a default ``config.json``.
* Saving is atomic (temporary file + :func:`os.replace`), so a crash during a
  write cannot leave a half-written config behind.
* Broken JSON is moved aside instead of being lost, then defaults are
  recreated.
* Values coming from disk are sanitised and clamped before use.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.app_paths import default_data_dir, ensure_data_layout

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
THEMES = ("dark", "midnight", "light")
PAGES = ("home", "store", "settings")

MIN_MEMORY_MB = 1024
MAX_MEMORY_MB = 16384
DEFAULT_MEMORY_MB = 4096


def _defaults() -> dict[str, Any]:
    """Return a fresh copy of the built-in settings tree."""
    return {
        "schema_version": SCHEMA_VERSION,
        "theme": "dark",
        "accent": "",
        "text_color": "",
        "panel_color": "",
        "auto_contrast": True,
        "show_snapshots": True,
        "language": "ru",
        "video_volume": 35,
        "memory_mb": DEFAULT_MEMORY_MB,
        "instances_path": "",
        "last_page": "home",
        "player": {"name": "Гость"},
        "java": {"path": "", "auto": True},
        "proxy": {
            "enabled": False,
            "host": "",
            "port": 8080,
            "username": "",
            "password": "",
        },
        "curseforge_key": "",
        "background": {"mode": "asset", "path": ""},
        "premium": {"key": "", "active": False},
        "window": {
            "width": 1360,
            "height": 860,
            "x": None,
            "y": None,
            "maximized": False,
        },
    }


def _as_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _as_int(value: Any, default: int, low: int, high: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _as_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any, default: str = "", *, strip: bool = True) -> str:
    if not isinstance(value, str):
        return default
    return value.strip() if strip else value


def _merge(defaults: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively overlay ``overrides`` on ``defaults`` (non-mutating)."""
    result = copy.deepcopy(defaults)
    for key, value in overrides.items():
        if key not in result:
            continue
        if isinstance(result[key], dict) and isinstance(value, Mapping):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _sanitize(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge untrusted data into the schema and clamp every value."""
    data = _merge(_defaults(), raw or {})

    theme = data.get("theme")
    if theme not in THEMES:
        theme = "dark"

    page = data.get("last_page")
    if page not in PAGES:
        page = "home"

    player = data.get("player") if isinstance(data.get("player"), Mapping) else {}
    java = data.get("java") if isinstance(data.get("java"), Mapping) else {}
    proxy = data.get("proxy") if isinstance(data.get("proxy"), Mapping) else {}
    window = data.get("window") if isinstance(data.get("window"), Mapping) else {}
    background = data.get("background") if isinstance(data.get("background"), Mapping) else {}
    premium = data.get("premium") if isinstance(data.get("premium"), Mapping) else {}

    username = _as_str(player.get("name"), "Гость") or "Гость"

    port = _as_int(proxy.get("port"), 8080, 1, 65535)

    width = _as_int(window.get("width"), 1360, 1024, 7680)
    height = _as_int(window.get("height"), 860, 680, 4320)

    accent = _as_str(data.get("accent")).lower()
    if accent and not re.fullmatch(r"#[0-9a-f]{6}", accent):
        accent = ""
    text_color = _as_str(data.get("text_color")).lower()
    if text_color and not re.fullmatch(r"#[0-9a-f]{6}", text_color):
        text_color = ""
    panel_color = _as_str(data.get("panel_color")).lower()
    if panel_color and not re.fullmatch(r"#[0-9a-f]{6}", panel_color):
        panel_color = ""

    bg_mode = _as_str(background.get("mode"), "asset").lower()
    if bg_mode not in {"asset", "image", "video"}:
        bg_mode = "asset"

    return {
        "schema_version": SCHEMA_VERSION,
        "theme": theme,
        "accent": accent,
        "text_color": text_color,
        "panel_color": panel_color,
        "auto_contrast": _as_bool(data.get("auto_contrast"), True),
        "show_snapshots": _as_bool(data.get("show_snapshots"), True),
        "language": "en" if str(data.get("language") or "") == "en" else "ru",
        "video_volume": _as_int(data.get("video_volume"), 35, 0, 100),
        "memory_mb": _as_int(
            data.get("memory_mb"), DEFAULT_MEMORY_MB, MIN_MEMORY_MB, MAX_MEMORY_MB
        ),
        "instances_path": _as_str(data.get("instances_path"))[:1024],
        "last_page": page,
        "player": {"name": username[:32]},
        "java": {
            "path": _as_str(java.get("path")),
            "auto": _as_bool(java.get("auto"), True),
        },
        "proxy": {
            "enabled": _as_bool(proxy.get("enabled"), False),
            "host": _as_str(proxy.get("host"))[:255],
            "port": port,
            "username": _as_str(proxy.get("username"))[:64],
            "password": _as_str(proxy.get("password"), strip=False)[:256],
        },
        "curseforge_key": _as_str(data.get("curseforge_key"))[:256],
        "background": {
            "mode": bg_mode,
            "path": _as_str(background.get("path"))[:2048],
        },
        "premium": {
            "key": _as_str(premium.get("key"))[:256],
            "active": _as_bool(premium.get("active"), False),
        },
        "window": {
            "width": width,
            "height": height,
            "x": _as_optional_int(window.get("x")),
            "y": _as_optional_int(window.get("y")),
            "maximized": _as_bool(window.get("maximized"), False),
        },
    }


class ConfigManager:
    """Load, validate and persist ``config.json``."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = ensure_data_layout(data_dir or default_data_dir())
        self.config_path = self.data_dir / "config.json"
        self.instances_dir = self.data_dir / "instances"
        self.first_run = False
        self.last_error: str | None = None
        self._data = _defaults()
        self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        if not self.config_path.exists():
            self.first_run = True
            self._data = _defaults()
            logger.info("First launch: creating %s", self.config_path)
            self.save()
            return

        raw: Mapping[str, Any] | None = None
        needs_repair = False
        try:
            with self.config_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, Mapping):
                raw = loaded
            else:
                needs_repair = True
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Cannot read config (%s); restoring defaults", exc)
            needs_repair = True

        if needs_repair:
            backup = self._backup_broken_config()
            if backup:
                logger.info("Broken config backed up to %s", backup)

        self._data = _sanitize(raw)
        if needs_repair:
            self.save()

    def _backup_broken_config(self) -> Path | None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.config_path.with_name(f"config.invalid-{stamp}.json")
        counter = 1
        while target.exists():
            target = self.config_path.with_name(
                f"config.invalid-{stamp}-{counter}.json"
            )
            counter += 1
        try:
            os.replace(self.config_path, target)
            return target
        except OSError as exc:
            logger.error("Could not back up broken config: %s", exc)
            return None

    # ------------------------------------------------------------------ save
    def save(self) -> bool:
        """Atomically write settings.  Returns ``True`` on success."""
        payload = json.dumps(self._data, ensure_ascii=False, indent=2) + "\n"
        temp_path = self.config_path.with_name(self.config_path.name + ".tmp")
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(3):
                try:
                    os.replace(temp_path, self.config_path)
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.05)
            self.last_error = None
            return True
        except OSError as exc:
            self.last_error = str(exc)
            logger.error("Cannot save config: %s", exc)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    # ------------------------------------------------------------------ data
    @property
    def data(self) -> dict[str, Any]:
        """A defensive copy of the full settings tree."""
        return copy.deepcopy(self._data)

    def __getitem__(self, key: str) -> Any:
        return copy.deepcopy(self._data[key])

    def get(self, key: str, default: Any = None) -> Any:
        return copy.deepcopy(self._data.get(key, default))

    def update(self, patch: Mapping[str, Any]) -> bool:
        """Deep-merge ``patch`` into settings, sanitise and save."""
        merged = _merge(self._data, patch)
        self._data = _sanitize(merged)
        return self.save()

    def reset(self) -> bool:
        self._data = _defaults()
        return self.save()

    # ----------------------------------------------------------- convenience
    @property
    def theme(self) -> str:
        return str(self._data["theme"])

    @theme.setter
    def theme(self, value: str) -> None:
        self.update({"theme": value})

    @property
    def memory_mb(self) -> int:
        return int(self._data["memory_mb"])

    @memory_mb.setter
    def memory_mb(self, value: int) -> None:
        self.update({"memory_mb": value})

    @property
    def last_page(self) -> str:
        return str(self._data["last_page"])

    @last_page.setter
    def last_page(self, value: str) -> None:
        self.update({"last_page": value})

    def set_window_state(
        self, width: int, height: int, x: int | None, y: int | None, maximized: bool
    ) -> bool:
        return self.update(
            {
                "window": {
                    "width": width,
                    "height": height,
                    "x": x,
                    "y": y,
                    "maximized": maximized,
                }
            }
        )

    def set_proxy(
        self,
        *,
        enabled: bool,
        host: str,
        port: int,
        username: str,
        password: str = "",
    ) -> bool:
        return self.update(
            {
                "proxy": {
                    "enabled": enabled,
                    "host": host,
                    "port": port,
                    "username": username,
                    "password": password,
                }
            }
        )

    @property
    def accent(self) -> str:
        return str(self._data.get("accent", ""))

    @accent.setter
    def accent(self, value: str) -> None:
        self.update({"accent": value})

    @property
    def text_color(self) -> str:
        return str(self._data.get("text_color", ""))

    @property
    def panel_color(self) -> str:
        return str(self._data.get("panel_color", ""))

    @property
    def auto_contrast(self) -> bool:
        return bool(self._data.get("auto_contrast", True))

    @property
    def instances_path(self) -> str:
        return str(self._data.get("instances_path", ""))

    @instances_path.setter
    def instances_path(self, value: str) -> None:
        self.update({"instances_path": value})

    @property
    def show_snapshots(self) -> bool:
        return bool(self._data.get("show_snapshots", True))

    @property
    def video_volume(self) -> int:
        return max(0, min(100, int(self._data.get("video_volume", 35))))

    @property
    def language(self) -> str:
        return "en" if self._data.get("language") == "en" else "ru"

    def premium_active(self) -> bool:
        return bool(self._data.get("premium", {}).get("active", False))
