#!/usr/bin/env python3
"""Fionix launcher — development entry point.

Run from the project root::

    python main.py

Fionix includes accounts, the Modrinth/CurseForge market, .fionixpack
sharing, customization, updates and system tray integration.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``python main.py`` and ``python path/to/main.py`` without installing the
# package. PyInstaller sets sys.path itself.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app import run  # noqa: E402  (path bootstrap must happen first)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv))
