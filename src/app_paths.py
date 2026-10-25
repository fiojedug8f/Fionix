"""Filesystem paths used by Fionix.

Two locations are deliberately kept apart:

* **Program folder** -- code, assets, bundled runtime files.  This folder is
  read-only for the application and may live anywhere the user installed the
  launcher.
* **Data folder** -- user generated files (``config.json`` and, later, game
  instances).  On Windows it is ``%APPDATA%/Fionix``.

``FIONIX_DATA_DIR`` can be used to override the data folder (handy for tests
and a future portable mode).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Fionix"


def is_frozen() -> bool:
    """Return ``True`` when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def program_dir() -> Path:
    """Directory that contains the executable (or the repository root)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # src/app_paths.py -> src -> repository root
    return Path(__file__).resolve().parents[2]


def resource_dir() -> Path:
    """Directory containing bundled resources (assets, fonts...)."""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    return Path(bundle_dir) if bundle_dir else program_dir()


def assets_dir() -> Path:
    return resource_dir() / "assets"


def asset_path(*parts: str) -> Path:
    return assets_dir().joinpath(*parts)


def default_data_dir() -> Path:
    """Per-user writable data directory for the launcher."""
    override = os.environ.get("FIONIX_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def ensure_data_layout(data_dir: Path | str | None = None) -> Path:
    """Create the data directory, ``instances`` and ``logs`` if missing."""
    root = Path(data_dir).expanduser() if data_dir else default_data_dir()
    (root / "instances").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    return root
